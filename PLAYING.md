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
- Cheat: `F2` (or `#reveal`) toggles seeing the whole level: every monster,
  item and wall, live as you play. Turn it off and your vision is normal again;
  what you saw stays on your map. While it is on, every item you carry or that
  lies on the level is fully identified (and stays identified).
- Cheat: the helper sees the whole level as it really is (every monster, every
  item truly identified, traps) and your inventory identified. `NETHACK_REVEAL= ./play`
  turns that off.
- `F3` / `F4` (or `#godown` / `#goup`) walk to the down / up stairs once you know where
  they are (with `F2` on, you always do). Anything interesting stops the walk; press again.
- `F5` asks the helper "what should I do right now?" without typing.
- Guard (`guard.py`, plain rules, no model): a dangerous key is held back with the
  reason in the helper pane; press it again to do it anyway. Covers eating cockatrice /
  chickatrice / Medusa / green slime corpses, eating while Satiated, praying when it
  isn't safe (uses the cheat's prayer timeout, luck and anger), putting on or wearing
  cursed or unknown-BUC items, and moving into a floating eye or bare-handed into a
  cockatrice.
- Warnings appear in the helper pane (yellow) when they start to apply: low HP, Weak or
  Fainting, turning to stone or slime, strangling, deadly illness, and dangerous monsters
  within 7 squares.
- Undo: a snapshot is taken on each new dungeon level (and with `F6`); `F7` rewinds to
  the latest one. When you die, the helper offers `F7` to rewind (`q` quits). A snapshot
  saves and restarts the game, so you'll see "Restoring save file..." for a moment. The
  last 10 per character are kept in `playground/snapshots/`.
- Your inventory stays visible to the right of the map (`perm_invent`); menus open over it.
- Don't die for good: `./play -X` (or `#exploremode` mid-game) is NetHack's explore mode;
  when you would die it asks `Die?` and you can say no. Explore games skip the high scores.
- Closing the terminal saves the game (NetHack saves on hangup).

Needs `uv` (runs the helper with `pyte`, a terminal emulator) and `claude` on PATH.

| Setting | Default |
|---|---|
| Game options | `nethackrc` (color, status highlights, menu colors, autopickup); set `NETHACKOPTIONS` to use your own |
| `NH_HELPER_MODEL` | `sonnet` |
| `NH_HELPER_WIDTH` | `40` columns (the game keeps at least 80) |
