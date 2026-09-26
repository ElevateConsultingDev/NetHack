# Conclusions: the brain's memory, as a tree

Each leaf holds 1 to 3 rules for one situation. The engine puts only the leaves matching the moment (monsters in view, hunger, depth, dungeon branch, escalation kind) into the brain's brief (`pilot.brain.recall`). `pilot.reflect` revises leaves after a batch, archiving each changed leaf first (`conclusions-archive/`). This file is the generated index; edit the leaves in `branches/`.

- `depth/dlvl-6-10`: At Dlvl 6+ with XL more than 3 below Dlvl, flee on sight from any difficulty 5+ monster: killer bees, jaguars, bugbears,
- `dungeon/the-gnomish-mines`: In the Mines, dwarves, hobgoblins, spiders, ponies, orcs, rats, and giant ants hit harder than difficulty suggests; retr
- `escalation/badly-hurt`: With 2+ hostiles adjacent (jackal/werejackal/coyote/kitten packs common), choose fight or flee only; never elbereth, it 
- `escalation/critical-hp`: At critical or badly hurt HP with any monster adjacent: only fight or flee (step_away/go_to). Never eat, use, quaff, pra
- `escalation/failed-routine`: When step_away fails "nowhere further away to step," fight the adjacent threat immediately; explore/go_down fallback sti
- `escalation/no-way-on`: No way on after searching walls/dead ends, blocked by a peaceful or monster (red mold, yellow mold, dwarf zombie, homunc
- `general`: Never fight a shopkeeper, watchman, priest, or guard: pay or flee, duck from a guard's hail (cumulative). Descend ~1 dlv
- `hunger/fainting`: When Fainting, eat any corpse or food in inventory immediately, don't pick_up/loot/explore first; if none available keep
- `hunger/weak`: When Weak, actively seek and eat a corpse or known food immediately; don't explore, wait, pick_up unrelated items, or re
- `monsters/floating-eye`: Never melee or stay adjacent; step back a full square before acting. If it blocks the only path, don't loop waiting: att
- `monsters/homunculus`: Flee immediately on sight, never melee, eat, or quaff while adjacent: even one turn triggers its sleep bite. If already 
- `monsters/killer-bee`: Flee at first sighting, don't melee; poisoned stings stack fast and neither Elbereth nor fighting through it reliably sa
- `monsters/werejackal`: Flee (step_away/go_to away) at first sight, alone or in a pack with jackals/coyotes/kittens; if flight fails, fight, nev
