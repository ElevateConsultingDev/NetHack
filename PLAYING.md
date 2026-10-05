# Playing

```sh
./play                          # builds into playground/ on first run
./play -u Dave -p Valkyrie      # arguments go to nethack
```

NetHack (curses interface) on the left, a Claude helper on the right.

Keys are Mac-style: ⌃ Control, ⌥ Option, ⇧ Shift. NetHack's Meta commands are Option
(⌥L loots, ⌥P prays); the wrapper's own shortcuts are ⌃G followed by a letter (⌃G alone shows them in the bottom
bar); NetHack only uses ⌃G in debug mode. Option has to send Alt: in Ghostty/cmux that's `macos-option-as-alt = true`
in `~/.config/ghostty/config` (iTerm2: Profiles > Keys > Left Option key: Esc+).

- `⌃]` (or `⌃G t`) switches typing between the game and the helper.
- In the helper: Enter asks, Esc goes back to the game, `^U` clears the line.
- Each question goes to `claude -p` (your Claude login, no tools) with the
  screen and your inventory, read from the game over the aipipe socket
  (`doc/aipipe.md`). The conversation continues for the session.
- Mouse: click a menu line to pick it, click `--More--` to continue, click the map
  to travel there, click the helper pane to type in it. The wheel pages a game
  menu (same as `>` and `<`) or scrolls the helper's answers.
- Cheat: `⌃G f` (or `#fog`) lifts the fog of war: every monster, item, trap and wall of the
  level is drawn, live as you play. `⌃G f` again brings the fog back and you see only what
  you've actually explored (the lifted view is never written into your map memory).
  While the fog is lifted, every item you carry or that lies on the level is fully
  identified (and stays identified), and `⌃G d`/`⌃G u` know where the stairs are.
- Cheat: the helper sees the whole level as it really is (every monster, every
  item truly identified, traps) and your inventory identified. `NETHACK_REVEAL= ./play`
  turns that off.
- `⌃G d` / `⌃G u` (or `#godown` / `#goup`) walk to the down / up stairs once you know where
  they are (with the fog lifted, you always do). Anything interesting stops the walk; press again.
- `⌃G k` searches everything: type a few letters and pick with the arrows and Enter (or
  click). It finds NetHack's commands (from the game's own command table, with their keys),
  item actions ("quaff heal" quaffs your potion of healing), things on the map ("altar"
  travels there, via `#goto`), and the wrapper's own actions (snapshot, rewind, what now).
  Esc closes. Matching is fuzzy: words can be partial, letters can skip.
- `⌃G c` copies the game screen (map, messages, status, inventory) to the clipboard as plain
  text.
- `⌃G v` select mode: the screen freezes; drag a rectangle (it highlights) and letting go
  copies exactly that rectangle's text to the clipboard. Drag again for more; `⌃G v` or
  Esc returns to the game.
- `⌃G w` asks the helper "what should I do right now?" without typing.
- Guard (`guard.py`, plain rules, no model): a dangerous key is held back with the
  reason in the helper pane; press it again to do it anyway. Covers eating cockatrice /
  chickatrice / Medusa / green slime corpses, eating while Satiated, praying when it
  isn't safe (uses the cheat's prayer timeout, luck and anger), putting on or wearing
  cursed or unknown-BUC items, and moving into a floating eye or bare-handed into a
  cockatrice.
- Warnings appear in the helper pane (yellow) when they start to apply: low HP, Weak or
  Fainting, turning to stone or slime, strangling, deadly illness, and dangerous monsters
  within 7 squares.
- Checkpoints (saved copies of your game you can go back to): one is taken on each new
  dungeon level and with `⌃G s`; `⌃G r` goes back to the latest. A checkpoint saves and
  restarts the game, so you'll see "Restoring save file..." for a moment. The newest 20
  per character are kept in `playground/snapshots/`.
- Saves list (`⌃G l`): every saved game and checkpoint, all characters, newest first.
  Enter loads the selected one (the game you're in is checkpointed first, so nothing is
  lost); `d` deletes it, `p` prunes that character to its newest 3 checkpoints (both ask
  for the same key again to confirm); `n` starts a new game (type a name). When you die
  or quit, the list opens on your character's checkpoints: Enter plays on from there,
  `q` quits.
- Beside the map: status (HP colored by how hurt you are, Pw, AC, Xp, gold, turn, level),
  your location as x/y, stats, carried weight and capacity, speed, xp for the next level,
  your god, hunger and conditions; with the cheat on (the default) also, in magenta, Luck,
  prayer timeout, nutrition, alignment record and your intrinsics. Then your inventory. Click an item
  for what you can do with it (Wield, Wear, Put on, Quaff, Read, Zap, Eat, Apply, Throw,
  Drop, Ask the helper...); click an action or press its key, Esc closes. When the game
  asks for an item, clicking one answers. The game's own two status lines are moved here
  from under the map. Game menus open over this panel. When the game asks for an item
  ("What do you want to drink? [h or ?*]"), the panel says so and marks the items that fit.
- Regions are outlined (game | helper, map | panel, legend | chat | input). Drag the
  game | helper line left or right to resize them (the game redraws to fit), and the
  legend | chat line up or down. Messages and the game's status lines stay over the map
  (80 columns), so they never run into the panel.
- Zoom: the wheel over the map (or `⌃G i` / `⌃G o`) zooms the map in and out: each square
  becomes a block of its character (2x, 4x, 6x), colors kept, centered on you; the axes
  number the part in view, and clicking a square travels there. Menus and cursor picks
  show the normal map. In Ghostty/cmux and WezTerm the zoomed map is drawn as a picture
  (kitty's graphics protocol, rendered with Pillow), so the characters are truly bigger,
  in small steps (1.25x, 1.5x, 1.75x, 2x, 2.5x, 3x, 3.5x, 4x); in kitty it uses kitty's scaled text instead. Elsewhere, character
  blocks.
- Axes: row numbers (y, 0 at the top) down the left and column numbers (x, 1 at the
  left) along the bottom, the same coordinates the helper uses; your row and column
  are highlighted.
- Don't die for good: `./play -X` (or `#exploremode` mid-game) is NetHack's explore mode;
  when you would die it asks `Die?` and you can say no. Explore games skip the high scores.
- Closing the terminal saves the game (NetHack saves on hangup).

Needs `uv` (runs the helper with `pyte`, a terminal emulator, and `pillow` for the zoomed map) and `claude` on PATH.

| Setting | Default |
|---|---|
| Game options | `nethackrc` (color, status highlights, menu colors, autopickup); set `NETHACKOPTIONS` to use your own |
| `NH_HELPER_MODEL` | `sonnet` |
| `NH_HELPER_WIDTH` | `40` columns (the game keeps at least 80) |
