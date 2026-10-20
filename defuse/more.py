"""more.py -- the rows of data/more/ (wild + project-generated TRAIN rows), md5-checked, train-only. NEW CODE.

    python -m defuse.more --out runs/more/rows.jsonl                         # all 207,332 rows
    python -m defuse.more --out runs/more/rows.jsonl --sets mathqa asdiv     # only these sets
    python -m defuse.more --out runs/smoke/rows.jsonl --per-file 25         # the first 25 rows of each file (smoke)

Every file is checked against data/more/MORE.md5 first. Every row must be listed in the data/more/<kind>/<set>/MANIFEST.jsonl files with
`split` "train", in the file and with the fold the manifest records; anything else stops the run. The manifest is the
split of the project's in-force split rules (data/more/README.md); the rows' own `fold` (1-4) is a convenience for you:
pick one fold before you fit if you want a held-out number of your own.
"""
import argparse
import json
import os

from . import guard as G

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MORE = os.path.join(ROOT, "data", "more")


def manifest(more=MORE):
    """row_id -> manifest entry, from every data/more/<kind>/<set>/MANIFEST.jsonl (md5-checked by files())"""
    man = {}
    for rel in sorted(dict(reversed(l.split()) for l in open(os.path.join(more, "MORE.md5")) if l.strip())):
        if rel.endswith("MANIFEST.jsonl"):
            for line in open(os.path.join(more, rel), encoding="utf-8"):
                if line.strip():
                    m = json.loads(line)
                    if m["row_id"] in man:
                        raise G.Refused("REFUSE (defuse more): duplicate row id %s in the manifests" % m["row_id"])
                    man[m["row_id"]] = m
    return man


def files(more=MORE, sets=None):
    """md5-checked data files (relative paths), optionally only those of the named sets; the manifests are checked too"""
    want = dict(reversed(l.split()) for l in open(os.path.join(more, "MORE.md5")) if l.strip())
    out = []
    for rel, h in sorted(want.items()):
        if G.md5f(os.path.join(more, rel)) != h:
            raise SystemExit("REFUSE: %s does not match MORE.md5" % rel)
        if not rel.endswith("MANIFEST.jsonl") and (sets is None or rel.split("/")[1] in sets):
            out.append(rel)
    return out


def check_row(r, man, rel):
    """refuse a row that is not a train row of the shipped manifest (same id, same file, same fold)"""
    m = man.get(r["row_id"])
    if m is None:
        raise G.Refused("REFUSE (defuse more): row %s is not in the data/more/<kind>/<set>/MANIFEST.jsonl files" % r["row_id"])
    if m["split"] != "train":
        raise G.Refused("REFUSE (defuse more): row %s has split %s in the manifest; only train rows are used" % (r["row_id"], m["split"]))
    if m["file"] != rel or m["fold"] != r.get("fold") or r.get("fold") not in (1, 2, 3, 4):
        raise G.Refused("REFUSE (defuse more): row %s disagrees with the manifest (file / fold)" % r["row_id"])
    G.check_row_id(r["row_id"], r)


def iter_rows(more=MORE, sets=None, per_file=None):
    fl = files(more, sets)          # md5 of every file (the manifests too) first
    man = manifest(more)
    for rel in fl:
        k = 0
        for line in open(os.path.join(more, rel), encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            check_row(r, man, rel)
            yield line if line.endswith("\n") else line + "\n"
            k += 1
            if per_file and k >= per_file:
                break


def concat(out, sets=None, per_file=None, more=MORE):
    n = 0
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for line in iter_rows(more, sets, per_file):
            f.write(line)
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sets", nargs="*", default=None, help="set names (the folder names under data/more/wild and data/more/ours)")
    ap.add_argument("--per-file", type=int, default=0)
    a = ap.parse_args()
    n = concat(a.out, a.sets, a.per_file or None)
    print("wrote %d rows -> %s (md5 %s)" % (n, a.out, G.md5f(a.out)))


if __name__ == "__main__":
    main()
