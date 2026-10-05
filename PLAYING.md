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
- Cheat: `F2` (or `#fog`) lifts the fog of war: every monster, item, trap and wall of the
  level is drawn, live as you play. `F2` again brings the fog back and you see only what
  you've actually explored (the lifted view is never written into your map memory).
  While the fog is lifted, every item you carry or that lies on the level is fully
  identified (and stays identified), and `F3`/`F4` know where the stairs are.
- Cheat: the helper sees the whole level as it really is (every monster, every
  item truly identified, traps) and your inventory identified. `NETHACK_REVEAL= ./play`
  turns that off.
- `F3` / `F4` (or `#godown` / `#goup`) walk to the down / up stairs once you know where
  they are (with the fog lifted, you always do). Anything interesting stops the walk; press again.
- `F8` searches everything: type a few letters and pick with the arrows and Enter (or
  click). It finds NetHack's commands (from the game's own command table, with their keys),
  item actions ("quaff heal" quaffs your potion of healing), things on the map ("altar"
  travels there, via `#goto`), and the wrapper's own actions (snapshot, rewind, what now).
  Esc closes. Matching is fuzzy: words can be partial, letters can skip.
- `F9` copies the game screen (map, messages, status, inventory) to the clipboard as plain
  text.
- `F10` select mode: the screen freezes and the mouse goes back to the terminal, so a plain
  drag highlights text and Cmd-C copies it. `F10` or Esc returns to the game. (Without it,
  Shift-drag in Ghostty/cmux, kitty, WezTerm or Option-drag in iTerm2/Terminal selects too,
  but the game redrawing can clear the highlight.)
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
- Legend: the top of the helper pane lists every symbol on the map right now and what
  it is (monsters by name, items by class, doors, stairs, traps...).
- Beside the map: status (HP colored by how hurt you are, Pw, AC, Xp, gold, turn, level),
  your location as x/y, stats, hunger and conditions, then your inventory. Click an item
  for what you can do with it (Wield, Wear, Put on, Quaff, Read, Zap, Eat, Apply, Throw,
  Drop, Ask the helper...); click an action or press its key, Esc closes. When the game
  asks for an item, clicking one answers. The game's own two status lines are moved here
  from under the map. Game menus open over this panel. When the game asks for an item
  ("What do you want to drink? [h or ?*]"), the panel says so and marks the items that fit.
- Regions are outlined (game | helper, map | panel, legend | chat | input). Drag the
  game | helper line left or right to resize them (the game redraws to fit), and the
  legend | chat line up or down. Messages and the game's status lines stay over the map
  (80 columns), so they never run into the panel.
- Big map: open another split (cmux/Ghostty: Cmd-D) and run `./play --map` there. It
  mirrors the live map, with colors, axes and your position; Cmd + / Cmd - in that split
  zooms just it. When it's zoomed past the whole map it shows a window that follows you,
  and its axes number the part in view. ^C closes it.
- Axes: row numbers (y, 0 at the top) down the left and column numbers (x, 1 at the
  left) along the bottom, the same coordinates the helper uses; your row and column
  are highlighted.
- Don't die for good: `./play -X` (or `#exploremode` mid-game) is NetHack's explore mode;
  when you would die it asks `Die?` and you can say no. Explore games skip the high scores.
- Closing the terminal saves the game (NetHack saves on hangup).

Needs `uv` (runs the helper with `pyte`, a terminal emulator) and `claude` on PATH.

| Setting | Default |
|---|---|
| Game options | `nethackrc` (color, status highlights, menu colors, autopickup); set `NETHACKOPTIONS` to use your own |
| `NH_HELPER_MODEL` | `sonnet` |
| `NH_HELPER_WIDTH` | `40` columns (the game keeps at least 80) |
