# Conclusions: the brain's memory, as a tree

Each leaf holds 1 to 3 rules for one situation. The engine puts only the leaves matching the moment (monsters in view, hunger, depth, dungeon branch, escalation kind) into the brain's brief (`pilot.brain.recall`). `pilot.reflect` revises leaves after a batch, archiving each changed leaf first (`conclusions-archive/`). This file is the generated index; edit the leaves in `branches/`.

- `depth/dlvl-6-10`: At Dlvl 6+ with XL more than 3 below Dlvl, flee on sight from any difficulty 5+ monster; killer bees, tengu, and mixed h
- `dungeon/the-gnomish-mines`: In the Mines, dwarves, hobgoblins, spiders, ponies, orcs, and rats hit harder than difficulty suggests; retreat toward s
- `escalation/badly-hurt`: With 2+ hostiles adjacent, target or flee the most dangerous one; don't keep attacking a weaker adjacent monster (jackal
- `escalation/critical-hp`: At critical or badly hurt HP with a monster adjacent, never eat, quaff/use, check inventory, or rest (incl. rest-on-Elbe
- `escalation/failed-routine`: When step_away fails "nowhere further away to step," immediately fight the monster that triggered the consult (the real 
- `escalation/no-way-on`: No way on after searching walls/dead ends, blocked by a peaceful or monster: attack or push past the blocker at once; do
- `general`: Never fight a shopkeeper, watchman, priest, or guard: pay or flee, duck from a guard's hail (cumulative). Descend ~1 dlv
- `hunger/fainting`: When Fainting, seek and eat food immediately, don't idle through check-ins; praying again after several prior successful
- `hunger/weak`: When Weak, actively seek and eat a corpse or known food; don't just explore, wait, or rely on prayer to fix hunger (7+ c
- `monsters/floating-eye`: Never melee or stay adjacent; step back a full square before acting. If it blocks the only path, don't loop waiting: att
- `monsters/homunculus`: Flee immediately on sight, never engage even once in melee; its sleep bite lets it and other adjacent monsters land repe
- `monsters/killer-bee`: Flee at first sighting, don't melee; poisoned stings stack fast and neither Elbereth nor fighting through it reliably sa
- `monsters/werejackal`: Flee at first sight even at full HP. If a jackal and werejackal are both adjacent, treat the werejackal as the threat: f
