# Playing

```sh
./play                          # builds into playground/ on first run
./play -u Dave -p Valkyrie      # arguments go to nethack
```

NetHack (curses interface) on the left, a Claude helper on the right.

- `^]` or `F1` switches typing between the game and the helper.
- In the helper: Enter asks, Esc goes back to the game, `^U` clears the line.
- Each question goes to `claude -p` (your Claude login, no tools) with the
  screen and your inventory, read from the game over the aipipe socket
  (`doc/aipipe.md`). The conversation continues for the session.
- Mouse: click a menu line to pick it, click `--More--` to continue, click the map
  to travel there, click the helper pane to type in it. The wheel pages a game
  menu (same as `>` and `<`) or scrolls the helper's answers.
- Cheat: `F2` (or `#reveal`) maps the current level and its traps, like a
  scroll of magic mapping that also finds traps.
- Cheat: the helper sees the whole level as it really is (every monster, every
  item truly identified, traps) and your inventory identified. `NETHACK_REVEAL= ./play`
  turns that off.
- Closing the terminal saves the game (NetHack saves on hangup).

Needs `uv` (runs the helper with `pyte`, a terminal emulator) and `claude` on PATH.

| Setting | Default |
|---|---|
| Game options | `nethackrc` (color, status highlights, menu colors, autopickup); set `NETHACKOPTIONS` to use your own |
| `NH_HELPER_MODEL` | `sonnet` |
| `NH_HELPER_WIDTH` | `40` columns (the game keeps at least 80) |
