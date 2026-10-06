#!/usr/bin/env python3
"""Check (or rebuild) the generated training rows shipped in data/banks/.

    python banks/make_bank_data.py                     # fast: md5 of every shipped row file, and of the joined parts
    python banks/make_bank_data.py --rebuild           # regenerate every bank in a temporary folder and compare
    python banks/make_bank_data.py --rebuild v5div     # the same, for some banks only (names in BANKS below)
    python banks/make_bank_data.py --write [bank ...]  # regenerate and (re)write the files in data/banks/

data/banks/ holds the rows of the training banks, so that nobody has to run a generator to
train on them. Every file is plain JSON lines (one row per line), under 25 MB, and listed
with its md5 in data/banks/ROWS.md5. The rows are exactly what the bank's own generator
writes (its SHIP md5 file is checked first), with two derivations, both recorded here:

  * split: a file over 24 MB is cut at line boundaries into part_000.jsonl, part_001.jsonl, ...
    of about equal size; `cat part_*.jsonl` gives the generator's file back byte for byte
    (JOINS below holds its md5).
  * filter: divrole2's 640 reference rows (fold -1) are a held-out scoring set in the project
    and are left out; the shipped file is the generator's file with those lines removed (the
    other 5,248 lines unchanged and in order).

Regenerating takes about 7 minutes in all (v6ms is most of it), standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data", "banks")
ROWS_MD5 = os.path.join(DATA, "ROWS.md5")
MAX_PART = 24_000_000  # bytes; every shipped file stays under 25 MB

sys.path.insert(0, HERE)
from make_banks import md5_of, read_ship  # noqa: E402

BANKS = ["subrole", "divrole2", "v5x", "v5div", "v6ms"]
V5X_CHUNKS = ["C1", "C2", "C3", "C4", "C5", "C6"]
V6MS_ROUNDS = ["G1r01", "G1r02", "G1r03", "G1r04", "G2r01", "G2r02", "G2r03", "G3r01", "G3r02"]

# split files: the generator's file (as named in data/banks/ROWS.md5's comments) -> (its md5, its parts)
JOINS = {
    "v5div/signed_A_int.jsonl": ("ddaf2959b963641f15d7775a8989e8de",
                                 ["v5div/part_000.jsonl", "v5div/part_001.jsonl", "v5div/part_002.jsonl"]),
}
# filtered files: shipped file -> (the generator's file, its md5, the rule)
FILTERS = {
    "divrole2/DIVROLE2_folds0-4.jsonl": ("divrole2/bank/dump/DIVROLE2.jsonl", "a89f5e04e937784b7247caf6c02ce12b",
                                         "drop the rows with fold == -1"),
}


def md5_bytes(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def split_lines(raw: bytes, max_part: int = MAX_PART) -> list[bytes]:
    """Cut raw (JSON lines) into the fewest parts of at most max_part bytes, of about equal size, at line ends."""
    if len(raw) <= max_part:
        return [raw]
    if max(len(ln) for ln in raw.splitlines(keepends=True)) > max_part:
        raise ValueError("a single line is longer than max_part")
    n = -(-len(raw) // max_part)
    while True:
        # part k ends at the first line end at or after byte k * len / n
        cuts = [0] + [raw.index(b"\n", k * len(raw) // n) + 1 for k in range(1, n)] + [len(raw)]
        parts = [raw[a:b] for a, b in zip(cuts, cuts[1:]) if b > a]
        if all(len(p) <= max_part for p in parts):
            return parts
        n += 1


def drop_fold_minus_one(raw: bytes) -> bytes:
    keep = [ln for ln in raw.splitlines(keepends=True) if json.loads(ln)["fold"] != -1]
    return b"".join(keep)


def run(cmd: list[str], cwd: str) -> None:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    tail = (r.stdout + r.stderr).strip().splitlines()
    print("   " + (tail[-1] if tail else "(no output)"))
    if r.returncode != 0:
        raise SystemExit(f"FAILED ({r.returncode}): {' '.join(cmd)}")


def build(bank: str, tmp: str) -> dict[str, bytes]:
    """Regenerate one bank (its SHIP md5s are checked by its make script) and derive its data files."""
    py = sys.executable
    out: dict[str, bytes] = {}
    print(f"== {bank}")
    if bank in ("subrole", "divrole2"):
        # the role banks write into banks/<bank>/bank/ (ignored by git); make_role_banks checks their SHIP md5s
        run([py, "make_role_banks.py", bank], HERE)
        if bank == "subrole":
            out["subrole/SUBROLE.jsonl"] = open(os.path.join(HERE, "subrole", "bank", "dump", "SUBROLE.jsonl"), "rb").read()
        else:
            src, want, _ = FILTERS["divrole2/DIVROLE2_folds0-4.jsonl"]
            raw = open(os.path.join(HERE, src), "rb").read()
            assert md5_bytes(raw) == want, src
            out["divrole2/DIVROLE2_folds0-4.jsonl"] = drop_fold_minus_one(raw)
    elif bank == "v5x":
        run([py, "make_v5x.py", "--out", os.path.join(tmp, "v5x")], HERE)
        for c in V5X_CHUNKS:
            out[f"v5x/{c}.jsonl"] = open(os.path.join(tmp, "v5x", c, "signed_A_int.jsonl"), "rb").read()
    elif bank == "v5div":
        run([py, "make_v5div.py", "--out", os.path.join(tmp, "v5div")], HERE)
        raw = open(os.path.join(tmp, "v5div", "signed_A_int.jsonl"), "rb").read()
        want, names = JOINS["v5div/signed_A_int.jsonl"]
        assert md5_bytes(raw) == want
        parts = split_lines(raw)
        assert len(parts) == len(names) and b"".join(parts) == raw
        out.update(zip(names, parts))
    elif bank == "v6ms":
        run([py, "make_v6ms.py", "--out", os.path.join(tmp, "v6ms")], HERE)
        for r in V6MS_ROUNDS:
            for k in ("le5", "n6"):
                out[f"v6ms/{r}_{k}.jsonl"] = open(os.path.join(tmp, "v6ms", r, f"rows_{k}.jsonl"), "rb").read()
    else:
        raise SystemExit(f"unknown bank {bank}")
    return out


def check_shipped(banks: list[str]) -> int:
    want = read_ship(ROWS_MD5)
    sel = {rel: d for rel, d in want.items() if rel.split("/")[0] in banks}
    bad = 0
    for rel, digest in sorted(sel.items()):
        p = os.path.join(DATA, rel)
        got = md5_of(p) if os.path.exists(p) else "missing"
        size = os.path.getsize(p) if os.path.exists(p) else 0
        ok = got == digest and size < 25_000_000
        bad += not ok
        print(f"   {'ok  ' if ok else 'BAD '} data/banks/{rel} {got} {size:,} bytes" + ("" if ok else f" (want {digest})"))
    for joined, (digest, parts) in sorted(JOINS.items()):
        if joined.split("/")[0] not in banks:
            continue
        h = hashlib.md5()
        for rel in parts:
            p = os.path.join(DATA, rel)
            if os.path.exists(p):
                h.update(open(p, "rb").read())
        ok = h.hexdigest() == digest
        bad += not ok
        print(f"   {'ok  ' if ok else 'BAD '} joined {' + '.join(parts)} = {joined} {h.hexdigest()}")
    print(f"data check: {len(sel) - bad if bad <= len(sel) else 0}/{len(sel)} row files match data/banks/ROWS.md5"
          + ("" if not bad else f"; {bad} problem(s)"))
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("banks", nargs="*", help=f"any of {', '.join(BANKS)} (default: all)")
    ap.add_argument("--rebuild", action="store_true", help="regenerate and compare with data/banks/ROWS.md5")
    ap.add_argument("--write", action="store_true", help="regenerate and write the files into data/banks/")
    a = ap.parse_args(argv)
    names = a.banks or BANKS
    unknown = [b for b in names if b not in BANKS]
    if unknown:
        ap.error(f"unknown bank(s) {unknown}; known: {BANKS}")
    if not (a.rebuild or a.write):
        return 1 if check_shipped(names) else 0
    want = read_ship(ROWS_MD5) if os.path.exists(ROWS_MD5) else {}
    bad = 0
    tmp = tempfile.mkdtemp(prefix="bankdata_")
    try:
        for bank in names:
            files = build(bank, tmp)
            for rel, b in sorted(files.items()):
                assert len(b) < 25_000_000, rel
                got = md5_bytes(b)
                if a.write:
                    os.makedirs(os.path.dirname(os.path.join(DATA, rel)), exist_ok=True)
                    with open(os.path.join(DATA, rel), "wb") as fh:
                        fh.write(b)
                ok = want.get(rel) == got
                bad += not ok
                nrows = b.count(b"\n")
                print(f"   {'ok  ' if ok else 'NEW ' if a.write else 'BAD '} data/banks/{rel} {got} "
                      f"{nrows:,} rows {len(b):,} bytes")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if a.write:
        print("written; now check data/banks/ROWS.md5 (python banks/make_bank_data.py)")
        return 0
    print("ALL OK" if not bad else f"{bad} file(s) differ from data/banks/ROWS.md5")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
