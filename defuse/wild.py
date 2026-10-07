"""wild.py -- one rows file from the shipped wild rows (data/wild/), md5-checked. NEW CODE.

    python -m defuse.wild --out runs/q17/rows.jsonl                  # all 7,497 rows (folds 1-4)
    python -m defuse.wild --out runs/smoke/rows.jsonl --per-file 25   # the first 25 rows of each of the 8 files (smoke)

Every file is checked against data/wild/WILD.md5 first, and every row against the fold rule (folds 1-4 only), so the
rows file you dump is exactly the shipped one.
"""
import argparse
import glob
import json
import os

from . import guard as G

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WILD = os.path.join(ROOT, "data", "wild")


def files(wild=WILD):
    want = dict(reversed(l.split()) for l in open(os.path.join(wild, "WILD.md5")) if l.strip())
    out = sorted(glob.glob(os.path.join(wild, "*", "fold*.jsonl")))
    for p in out:
        rel = os.path.relpath(p, wild)
        if want.get(rel) != G.md5f(p):
            raise SystemExit("REFUSE: %s does not match WILD.md5 (%s)" % (rel, want.get(rel)))
    if len(out) != 8:
        raise SystemExit("REFUSE: expected the 8 shipped files, found %d" % len(out))
    return out


def concat(out, per_file=None, wild=WILD):
    n = 0
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for p in files(wild):
            k = 0
            for line in open(p, encoding="utf-8"):
                if not line.strip():
                    continue
                r = json.loads(line)
                G.check_row_id(r["row_id"], r)
                if r.get("fold") not in (1, 2, 3, 4):
                    raise SystemExit("REFUSE: %s has fold %s" % (r["row_id"], r.get("fold")))
                f.write(line if line.endswith("\n") else line + "\n")
                n += 1; k += 1
                if per_file and k >= per_file:
                    break
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-file", type=int, default=0, help="keep only the first N rows of each file (smoke tests)")
    a = ap.parse_args()
    n = concat(a.out, a.per_file or None)
    print("wrote %d rows -> %s (md5 %s)" % (n, a.out, G.md5f(a.out)))


if __name__ == "__main__":
    main()
