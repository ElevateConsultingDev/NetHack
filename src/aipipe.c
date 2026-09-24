/* NetHack 3.6	aipipe.c	*/
/* Copyright (c) 2026.  NetHack may be freely redistributed.  See license. */

/*
 * aipipe: a structured control channel for an external controller.
 *
 * When NETHACK_CONTROL names a Unix-domain socket, the game connects to it
 * and, every time it waits for a key, sends one JSON line describing the
 * game as the player can see it: what is being asked (command, y/n, menu,
 * text, --More--), recent messages, status, position, the map, notable map
 * cells (monsters, objects, traps, features) and inventory.  The controller
 * answers with lines like {"keys":"h"}; those keys are fed to the game as if
 * typed.  Keys typed at the terminal keep working, so control can pass back
 * and forth.  Without NETHACK_CONTROL the game is unchanged.
 *
 * Hooks: tty_nhgetch() reads keys through aipipe_getch(); xwaitforspace()
 * marks --More--; choose_windows() calls aipipe_install(), which wraps a few
 * window procedures (messages, y/n, text prompts, menus) to record context.
 */

#include "hack.h"
#include "aipipe.h"

#ifdef TTY_GRAPHICS
#include "wintty.h"
#endif

#include <sys/types.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/select.h>
#include <unistd.h>
#include <errno.h>

extern const char *hu_stat[];  /* eat.c */
extern const char *const enc_stat[]; /* botl.c */

static int sock = -1;
static struct window_procs base; /* the real window port's procedures */

/* keys received from the controller, not yet consumed */
static char inq[BUFSZ * 4];
static int inq_len = 0, inq_pos = 0;
static char rbuf[BUFSZ * 4];
static int rlen = 0;
static const char *last_src = "none";
static long seq = 0;

/* what the game is asking for right now */
static const char *ctx_kind = (const char *) 0;
static char ctx_prompt[BUFSZ], ctx_choices[BUFSZ];
static int ctx_menu_how = 0;
static winid ctx_menu_win = WIN_ERR;
static boolean more_pending = FALSE; /* a --More-- is waiting (maybe in a menu) */

/* messages printed since the last snapshot */
#define AI_MAXMSG 30
static char msgs[AI_MAXMSG][BUFSZ];
static int nmsgs = 0;

/* ---------- output buffer ---------- */

static char *out = (char *) 0;
static size_t out_len = 0, out_cap = 0;

static void
put(s)
const char *s;
{
    size_t n = strlen(s);

    if (out_len + n + 1 > out_cap) {
        out_cap = (out_len + n + 1) * 2 + 4096;
        out = (char *) realloc(out, out_cap);
        if (!out)
            panic("aipipe: out of memory");
    }
    memcpy(out + out_len, s, n);
    out_len += n;
    out[out_len] = '\0';
}

static void
putc_json(c)
int c;
{
    char tmp[8];

    switch (c) {
    case '"': put("\\\""); break;
    case '\\': put("\\\\"); break;
    case '\n': put("\\n"); break;
    case '\r': put("\\r"); break;
    case '\t': put("\\t"); break;
    default:
        if ((unsigned char) c < 0x20 || (unsigned char) c >= 0x7f) {
            Sprintf(tmp, "\\u%04x", (unsigned char) c);
            put(tmp);
        } else {
            tmp[0] = (char) c;
            tmp[1] = '\0';
            put(tmp);
        }
    }
}

static void
put_str(s) /* a JSON string literal, or null */
const char *s;
{
    if (!s) {
        put("null");
        return;
    }
    put("\"");
    while (*s)
        putc_json(*s++);
    put("\"");
}

static void
put_kv_str(key, val, comma)
const char *key, *val;
boolean comma;
{
    if (comma)
        put(",");
    put_str(key);
    put(":");
    put_str(val);
}

static void
put_kv_int(key, val, comma)
const char *key;
long val;
boolean comma;
{
    char tmp[64];

    Sprintf(tmp, "%s\"%s\":%ld", comma ? "," : "", key, val);
    put(tmp);
}

static void
send_out()
{
    size_t off = 0;
    ssize_t n;

    put("\n");
    while (sock >= 0 && off < out_len) {
        n = write(sock, out + off, out_len - off);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0) { /* controller went away: carry on as a normal game */
            (void) close(sock);
            sock = -1;
            break;
        }
        off += (size_t) n;
    }
    out_len = 0;
}

/* ---------- context ---------- */

void
aipipe_more(on)
boolean on;
{
    more_pending = on;
}

void
aipipe_context(kind, prompt, choices)
const char *kind, *prompt, *choices;
{
    ctx_kind = kind;
    Strcpy(ctx_prompt, "");
    Strcpy(ctx_choices, "");
    if (prompt)
        (void) strncpy(ctx_prompt, prompt, BUFSZ - 1);
    if (choices)
        (void) strncpy(ctx_choices, choices, BUFSZ - 1);
}

/* ---------- snapshot pieces ---------- */

static void
put_status()
{
    char tmp[BUFSZ];
    int hp = Upolyd ? u.mh : u.uhp, hpmax = Upolyd ? u.mhmax : u.uhpmax;
    int cap = near_capacity();
    boolean first = TRUE;

    put(",\"status\":{");
    put_kv_int("hp", hp, FALSE);
    put_kv_int("hpmax", hpmax, TRUE);
    put_kv_int("pw", u.uen, TRUE);
    put_kv_int("pwmax", u.uenmax, TRUE);
    put_kv_int("ac", u.uac, TRUE);
    put_kv_int("xlvl", u.ulevel, TRUE);
    put_kv_int("exp", u.uexp, TRUE);
    put_kv_int("gold", money_cnt(invent), TRUE);
    put_kv_int("dlvl", depth(&u.uz), TRUE);
    put_kv_str("dungeon", dungeons[u.uz.dnum].dname, TRUE);
    put_kv_int("turn", moves, TRUE);
    put_kv_int("str", ACURR(A_STR), TRUE);
    put_kv_int("dex", ACURR(A_DEX), TRUE);
    put_kv_int("con", ACURR(A_CON), TRUE);
    put_kv_int("int", ACURR(A_INT), TRUE);
    put_kv_int("wis", ACURR(A_WIS), TRUE);
    put_kv_int("cha", ACURR(A_CHA), TRUE);
    Strcpy(tmp, hu_stat[u.uhs]);
    (void) trimspaces(tmp);
    put_kv_str("hunger", tmp, TRUE);
    put_kv_str("encumbrance", cap > 0 ? enc_stat[cap] : "", TRUE);
    put_kv_str("alignment",
               u.ualign.type == A_CHAOTIC ? "chaotic"
               : u.ualign.type == A_NEUTRAL ? "neutral" : "lawful", TRUE);
    put_kv_str("role", urole.name.m, TRUE);
    put_kv_str("race", urace.noun, TRUE);
    put(",\"conditions\":[");
#define COND(test, name) \
    if (test) {                   \
        if (!first)               \
            put(",");             \
        put_str(name);            \
        first = FALSE;            \
    }
    COND(Blind, "Blind")
    COND(Confusion, "Conf")
    COND(Stunned, "Stun")
    COND(Hallucination, "Hallu")
    COND(Sick, "Sick")
    COND(Slimed, "Slime")
    COND(Stoned, "Stone")
    COND(Strangled, "Strngl")
    COND(Levitation, "Lev")
    COND(Flying, "Fly")
    COND(u.usteed != 0, "Ride")
#undef COND
    put("]}");
}

/* what a map glyph is, as the player could learn with ';' */
static const char *
glyph_desc(glyph, kind)
int glyph;
const char **kind;
{
    int otyp, idx;

    if (glyph_is_invisible(glyph)) {
        *kind = "invisible";
        return "remembered, unseen, creature";
    }
    if (glyph_is_monster(glyph)) {
        *kind = glyph_is_pet(glyph) ? "pet" : "monster";
        return mons[glyph_to_mon(glyph)].mname;
    }
    if (glyph_is_object(glyph)) {
        *kind = "object";
        otyp = glyph_to_obj(glyph);
        if (!objects[otyp].oc_name_known && OBJ_DESCR(objects[otyp]))
            return OBJ_DESCR(objects[otyp]);
        return OBJ_NAME(objects[otyp]);
    }
    if (glyph_is_trap(glyph)) {
        *kind = "trap";
        return defsyms[trap_to_defsym(glyph_to_trap(glyph))].explanation;
    }
    if (glyph_is_cmap(glyph)) {
        idx = glyph_to_cmap(glyph);
        if (is_cmap_wall(idx) || is_cmap_room(idx) || idx == S_corr
            || idx == S_litcorr)
            return (const char *) 0; /* plain terrain: the map row says it */
        *kind = "feature";
        return defsyms[idx].explanation;
    }
    return (const char *) 0;
}

static void
put_map()
{
    int x, y, glyph, ch, color;
    unsigned special;
    const char *desc, *kind;
    char row[COLNO + 1], tmp[64];
    boolean first = TRUE;

    put(",\"map\":[");
    for (y = 0; y < ROWNO; y++) {
        for (x = 1; x < COLNO; x++) {
            glyph = glyph_at(x, y);
            (void) mapglyph(glyph, &ch, &color, &special, x, y, 0);
            row[x - 1] = (ch >= 0x20 && ch < 0x7f) ? (char) ch : '?';
        }
        row[COLNO - 1] = '\0';
        if (y)
            put(",");
        put_str(row);
    }
    put("],\"cells\":[");
    for (y = 0; y < ROWNO; y++)
        for (x = 1; x < COLNO; x++) {
            kind = "";
            if (!(desc = glyph_desc(glyph_at(x, y), &kind)))
                continue;
            if (x == u.ux && y == u.uy && !strcmp(kind, "monster"))
                kind = "you";
            Sprintf(tmp, "%s{\"x\":%d,\"y\":%d", first ? "" : ",", x, y);
            put(tmp);
            put_kv_str("kind", kind, TRUE);
            put_kv_str("name", desc, TRUE);
            put("}");
            first = FALSE;
        }
    put("]");
}

static void
put_inventory()
{
    struct obj *otmp;
    char tmp[4];

    put(",\"inventory\":[");
    for (otmp = invent; otmp; otmp = otmp->nobj) {
        if (otmp != invent)
            put(",");
        tmp[0] = otmp->invlet;
        tmp[1] = '\0';
        put("{");
        put_kv_str("letter", tmp, FALSE);
        tmp[0] = def_oc_syms[(int) otmp->oclass].sym;
        put_kv_str("class", tmp, TRUE);
        /* distant_name() keeps doname() from marking the item as seen */
        put_kv_str("text", distant_name(otmp, doname), TRUE);
        put_kv_int("worn", otmp->owornmask != 0L, TRUE);
        put("}");
    }
    put("]");
}

static void
put_context()
{
    boolean first = TRUE;
    char tmp[2];

    put("\"context\":{");
    put_kv_str("kind", ctx_kind ? ctx_kind
                       : more_pending ? "more"
                       : (iflags.in_parse ? "command" : "key"), FALSE);
    put_kv_int("more", more_pending, TRUE);
    if (ctx_kind) {
        put_kv_str("prompt", ctx_prompt, TRUE);
        put_kv_str("choices", ctx_choices, TRUE);
    }
#ifdef TTY_GRAPHICS
    if (ctx_kind && !strcmp(ctx_kind, "menu") && ctx_menu_win != WIN_ERR
        && wins[ctx_menu_win]) {
        tty_menu_item *mi;

        put_kv_str("how", ctx_menu_how == PICK_NONE ? "none"
                   : ctx_menu_how == PICK_ONE ? "one" : "any", TRUE);
        put(",\"items\":[");
        for (mi = wins[ctx_menu_win]->mlist; mi; mi = mi->next) {
            if (!first)
                put(",");
            first = FALSE;
            tmp[0] = mi->selector;
            tmp[1] = '\0';
            put("{");
            put_kv_str("key", mi->selector ? tmp : (const char *) 0, FALSE);
            put_kv_str("text", mi->str, TRUE);
            put_kv_int("selectable", mi->identifier.a_void != 0, TRUE);
            put_kv_int("selected", mi->selected, TRUE);
            put("}");
        }
        put("]");
    }
#endif
    put("}");
}

static void
emit_state()
{
    int i;

    put("{\"type\":\"state\"");
    put_kv_int("seq", ++seq, TRUE);
    put_kv_str("last_input", last_src, TRUE);
    put(",");
    put_context();
    put(",\"messages\":[");
    for (i = 0; i < nmsgs; i++) {
        if (i)
            put(",");
        put_str(msgs[i]);
    }
    put("]");
    nmsgs = 0;
    if (program_state.in_moveloop) {
        put(",\"player\":{");
        put_kv_int("x", u.ux, FALSE);
        put_kv_int("y", u.uy, TRUE);
        put("}");
        put_status();
        put_map();
        put_inventory();
    }
    put("}");
    send_out();
}

/* ---------- input ---------- */

/* take {"keys":"..."} lines out of the read buffer and queue their keys */
static void
parse_lines()
{
    char *nl, *p, *line = rbuf;

    while ((nl = memchr(line, '\n', (size_t) (rlen - (line - rbuf)))) != 0) {
        *nl = '\0';
        if ((p = strstr(line, "\"keys\"")) != 0 && (p = index(p + 6, '"')) != 0) {
            for (++p; *p && *p != '"'; p++) {
                int c = (unsigned char) *p;

                if (c == '\\' && p[1]) {
                    ++p;
                    c = *p == 'n' ? '\n' : *p == 'r' ? '\r' : *p == 't' ? '\t'
                        : *p == 'e' ? '\033' : (unsigned char) *p;
                    if (*p == 'u' && p[1] && p[2] && p[3] && p[4]) {
                        char hex[5];

                        (void) strncpy(hex, p + 1, 4);
                        hex[4] = '\0';
                        c = (int) strtol(hex, (char **) 0, 16);
                        p += 4;
                    }
                }
                if (inq_pos == inq_len)
                    inq_pos = inq_len = 0;
                if (inq_len < (int) sizeof inq)
                    inq[inq_len++] = (char) c;
            }
        }
        line = nl + 1;
    }
    rlen -= (int) (line - rbuf);
    memmove(rbuf, line, (size_t) rlen);
}

int
aipipe_getch()
{
    fd_set rd;
    unsigned char c;
    int n, maxfd;

    if (sock < 0)
        return tgetch();
    if (inq_pos < inq_len) {
        last_src = "controller";
        return (unsigned char) inq[inq_pos++];
    }
    emit_state();
    for (;;) {
        if (sock < 0)
            return tgetch();
        FD_ZERO(&rd);
        FD_SET(0, &rd);
        FD_SET(sock, &rd);
        maxfd = sock > 0 ? sock : 0;
        if (select(maxfd + 1, &rd, (fd_set *) 0, (fd_set *) 0,
                   (struct timeval *) 0) < 0) {
            if (errno == EINTR)
                continue;
            return EOF;
        }
        if (FD_ISSET(sock, &rd)) {
            n = (int) read(sock, rbuf + rlen, sizeof rbuf - (size_t) rlen - 1);
            if (n <= 0) {
                (void) close(sock);
                sock = -1;
                continue;
            }
            rlen += n;
            parse_lines();
            if (inq_pos < inq_len) {
                last_src = "controller";
                return (unsigned char) inq[inq_pos++];
            }
        }
        if (FD_ISSET(0, &rd)) {
            if (read(0, &c, 1) == 1) {
                last_src = "terminal";
                return c;
            }
            return EOF;
        }
    }
}

/* ---------- window procedure wrappers ---------- */

static void
ai_putstr(window, attr, str)
winid window;
int attr;
const char *str;
{
    if (window == WIN_MESSAGE && str && *str) {
        if (nmsgs == AI_MAXMSG) {
            memmove(msgs[0], msgs[1], sizeof msgs[0] * (AI_MAXMSG - 1));
            nmsgs--;
        }
        (void) strncpy(msgs[nmsgs], str, BUFSZ - 1);
        msgs[nmsgs++][BUFSZ - 1] = '\0';
    }
    (*base.win_putstr)(window, attr, str);
}

static char
ai_yn_function(query, resp, def)
const char *query, *resp;
char def;
{
    char r;
    const char *saved = ctx_kind;

    aipipe_context("yn", query, resp);
    r = (*base.win_yn_function)(query, resp, def);
    ctx_kind = saved;
    return r;
}

static void
ai_getlin(query, bufp)
const char *query;
char *bufp;
{
    const char *saved = ctx_kind;

    aipipe_context("getlin", query, (const char *) 0);
    (*base.win_getlin)(query, bufp);
    ctx_kind = saved;
}

static int
ai_select_menu(window, how, menu_list)
winid window;
int how;
menu_item **menu_list;
{
    int r;
    const char *saved = ctx_kind;

    aipipe_context("menu", (const char *) 0, (const char *) 0);
    ctx_menu_win = window;
    ctx_menu_how = how;
    r = (*base.win_select_menu)(window, how, menu_list);
    ctx_menu_win = WIN_ERR;
    ctx_kind = saved;
    return r;
}

static int
ai_get_ext_cmd()
{
    int r;
    const char *saved = ctx_kind;

    aipipe_context("extcmd", "#", (const char *) 0);
    r = (*base.win_get_ext_cmd)();
    ctx_kind = saved;
    return r;
}

void
aipipe_install()
{
    const char *path = getenv("NETHACK_CONTROL");
    struct sockaddr_un addr;

    if (!path || !*path)
        return;
    if (sock < 0) {
        if ((sock = socket(AF_UNIX, SOCK_STREAM, 0)) < 0)
            return;
        (void) memset(&addr, 0, sizeof addr);
        addr.sun_family = AF_UNIX;
        (void) strncpy(addr.sun_path, path, sizeof addr.sun_path - 1);
        if (connect(sock, (struct sockaddr *) &addr, sizeof addr) < 0) {
            (void) close(sock);
            sock = -1;
            return;
        }
    }
    base = windowprocs;
    windowprocs.win_putstr = ai_putstr;
    windowprocs.win_yn_function = ai_yn_function;
    windowprocs.win_getlin = ai_getlin;
    windowprocs.win_select_menu = ai_select_menu;
    windowprocs.win_get_ext_cmd = ai_get_ext_cmd;
}

/*aipipe.c*/
