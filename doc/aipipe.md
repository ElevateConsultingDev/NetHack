# aipipe: controller channel

This fork adds a structured control channel so an external program (an
autopilot, an LLM agent, a test harness) can see the game exactly as the
player can and send keys, while the normal tty display keeps working for a
human watching or playing.

## Build and run

```sh
sh sys/unix/setup.sh sys/unix/hints/macosx10.14
make WANT_SOURCE_INSTALL=1 all          # installs into ./playground
NETHACK_CONTROL=/tmp/nh.sock ./playground/nethack -u Name
```

The controller must already be listening on the Unix socket. Without
`NETHACK_CONTROL`, or if the connection fails, the game is stock NetHack.
Keep the path short: macOS limits socket paths to 104 bytes.

## Protocol

Newline-delimited JSON in both directions.

**Game to controller:** one `state` line each time the game waits for a key.

```json
{"type":"state","seq":12,"last_input":"controller",
 "context":{"kind":"yn","more":0,"prompt":"What do you want to eat? [gh or ?*]","choices":""},
 "messages":["You see here a lichen corpse."],
 "player":{"x":37,"y":8},
 "status":{"hp":16,"hpmax":16,"pw":1,"pwmax":1,"ac":3,"xlvl":1,"exp":0,"gold":0,
           "dlvl":1,"dungeon":"The Dungeons of Doom","turn":42,"str":17,...,
           "hunger":"","encumbrance":"","alignment":"lawful","role":"Knight",
           "race":"human","conditions":[]},
 "map":["<79 chars per row, 21 rows: the screen map as displayed>", ...],
 "cells":[{"x":37,"y":8,"kind":"you","name":"knight"},
          {"x":38,"y":8,"kind":"pet","name":"pony"},
          {"x":40,"y":6,"kind":"feature","name":"staircase down"}, ...],
 "inventory":[{"letter":"a","class":")","text":"a +1 long sword (weapon in hand)","worn":1}, ...]}
```

- `context.kind`: `command` (the main prompt), `yn` (a single-key question
  with `prompt` and allowed `choices`; object prompts like "What do you want
  to eat? [gh or ?*]" arrive this way), `getlin` (a line of text), `menu`
  (with `how`: none/one/any and `items`: `key`, `text`, `selectable`,
  `selected`), `extcmd` (the `#` extended command prompt), `more`
  (a `--More--` to dismiss), or `key` (any other single keypress).
  `more` is also a flag, set when a `--More--` is showing inside a menu.
- `map` rows are the characters on screen; `cells` names everything on the
  map that isn't plain floor, wall or corridor, as `;` would describe it:
  monsters (`monster`, `pet`, `you`, `invisible`), `object` (the
  appearance until identified), `trap`, `feature` (doors, stairs, altars...).
- `inventory` text is the game's own inventory line.
- Nothing hidden from the player is sent: object names follow what's
  identified, and inventory text is rendered without marking items seen.

**Controller to game:** `{"keys":"..."}`. The keys go into a queue and are
read as if typed. JSON escapes work (`"\u001b"` is Esc, `"\r"` is Enter).
Keys typed at the terminal are always accepted too; `last_input` says who
sent the key that produced the current state.

## Code

- `src/aipipe.c`, `include/aipipe.h`: the channel.
- `win/tty/wintty.c` (`tty_nhgetch`): reads keys via `aipipe_getch()`.
- `win/tty/getline.c` (`xwaitforspace`): flags `--More--`.
- `src/windows.c` (`choose_windows`): calls `aipipe_install()`, which wraps
  the message, y/n, getlin, menu and extended-command window procedures to
  record context.
