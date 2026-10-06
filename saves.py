"""Saved games and checkpoints (snapshots) on disk, for helper.py's saves list.

NetHack keeps a saved game as playground/save/<uid><name>.Z; a checkpoint is a
copy of one in playground/snapshots/ named <save file>@<turn>-D<dlvl>.
"""
import os
import re
import time


def char_name(base):
    """'501Dave.Z' or '501Dave.Z@000735-D3' -> 'Dave'."""
    return re.sub(r"\.(Z|gz)$", "", re.sub(r"^\d+", "", base.split("@")[0]))


def snap_label(path):
    turn, dlvl = os.path.basename(path).rsplit("@", 1)[-1].split("-D")
    return f"Dlvl {dlvl}, turn {int(turn)}"


def snapshots(snaps_dir, save_name=None):
    """Checkpoint files for one save file name (or all), oldest first."""
    if not os.path.isdir(snaps_dir):
        return []
    files = [os.path.join(snaps_dir, f) for f in os.listdir(snaps_dir)
             if not f.endswith(".log") and (save_name is None or f.split("@")[0] == save_name)]
    return sorted(files, key=os.path.getmtime)


def listing(saves_dir, snaps_dir):
    """Every saved game and checkpoint, grouped by character, newest first."""
    items = []
    for f in os.listdir(saves_dir) if os.path.isdir(saves_dir) else []:
        p = os.path.join(saves_dir, f)
        items.append(dict(kind="save", path=p, base=f, char=char_name(f), what="saved game"))
    for p in snapshots(snaps_dir):
        base = os.path.basename(p).split("@")[0]
        items.append(dict(kind="snap", path=p, base=base, char=char_name(base), what=snap_label(p)))
    for i in items:
        i["mtime"] = os.path.getmtime(i["path"])
        i["when"] = time.strftime("%b %d %H:%M", time.localtime(i["mtime"]))
    return sorted(items, key=lambda i: (i["char"].lower(), -i["mtime"]))


def prune(snaps_dir, save_name, keep=3):
    """Delete all but the newest `keep` checkpoints of one save file name; how many went."""
    old = snapshots(snaps_dir, save_name)[:-keep] if keep else snapshots(snaps_dir, save_name)
    for p in old:
        remove(p)
    return len(old)


def remove(path):
    """Delete a save or checkpoint, and the game log kept beside a checkpoint."""
    os.unlink(path)
    if os.path.exists(path + ".log"):
        os.unlink(path + ".log")


if __name__ == "__main__":
    import tempfile
    d = tempfile.mkdtemp()
    sv, sn = os.path.join(d, "save"), os.path.join(d, "snaps")
    os.makedirs(sv)
    os.makedirs(sn)
    open(os.path.join(sv, "501Dave.Z"), "w").close()
    for n, turn in enumerate((1, 300, 735, 900)):
        p = os.path.join(sn, f"501Dave.Z@{turn:06d}-D{n + 1}")
        open(p, "w").close()
        os.utime(p, (1000 + n, 1000 + n))
    open(os.path.join(sn, "501Bob.Z@000010-D1"), "w").close()
    open(os.path.join(sn, "501Bob.Z@000010-D1.log"), "w").close()  # a checkpoint's log: not a save
    assert char_name("501Dave.Z@000735-D3") == "Dave"
    items = listing(sv, sn)
    assert [i["char"] for i in items] == ["Bob", "Dave", "Dave", "Dave", "Dave", "Dave"]
    assert items[2]["what"] == "Dlvl 4, turn 900"  # newest checkpoint first, after the save
    assert prune(sn, "501Dave.Z", keep=3) == 1 and len(snapshots(sn, "501Dave.Z")) == 3
    assert len(snapshots(sn, "501Bob.Z")) == 1
    remove(os.path.join(sn, "501Bob.Z@000010-D1"))
    assert not os.listdir(sn) or all(not f.startswith("501Bob") for f in os.listdir(sn))
    print("saves ok")
