#!/usr/bin/env python3
"""Regenerate bank v5x (PARTIAL: chunk C1 of 6) from its per-language clean files and check every byte.

    python banks/make_v5x.py                # join clean/C1/*.json, check the md5, run v5x.py gen -> banks/v5x/bank/C1/, check
    python banks/make_v5x.py --check-only   # only compare banks/v5x/bank/C1/ with banks/v5x/SHIP_V5X_C1.md5
    python banks/make_v5x.py --join-only    # only rebuild banks/v5x/clean/clean_v5x_C1.json and check its md5

Bank v5x is bank v5 (wild-shaped distractors, add / sub / mul / div, the same row schema)
extended to the 36 languages of v3_61 that v5 lacks, with a question-form axis F0-F7. It is
written in 6 chunks of 6 languages; only chunk C1 (bg cs hu ro sk sr: 274 kept templates of
288) has been verified and cleaned so far, so this bank is PARTIAL and its md5s will change
when later chunks are added (a later chunk gets its own clean/<chunk>/ folder and md5 file).

v5x.py wraps the v5 tools in banks/v5/ (it edits none of them) and reads
banks/v5x/manifest/ (the unit specs; their forms and story ids enter the rows). The rows
were generated twice for this repository, under PYTHONHASHSEED=1 and 7, and once with the
project's own copies of the v5 tools: identical bytes each time. About five seconds.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
V5X = os.path.join(HERE, "v5x")
CHUNK = "C1"
SPLIT_DIR = os.path.join(V5X, "clean", CHUNK)
CLEAN = os.path.join(V5X, "clean", f"clean_v5x_{CHUNK}.json")
CLEAN_MD5 = "476b62cf4e7a4fd33c68c0bd8eedb32e"

sys.path.insert(0, HERE)
from clean_split import write_joined  # noqa: E402
from make_banks import md5_of, read_ship  # noqa: E402


def check(out: str, ship_path: str) -> int:
    want = read_ship(ship_path)
    bad = 0
    for rel, digest in sorted(want.items()):
        p = os.path.join(out, rel)
        got = md5_of(p) if os.path.exists(p) else "missing"
        ok = got == digest
        bad += not ok
        print(f"   {'ok  ' if ok else 'BAD '} {os.path.relpath(p, HERE)} {got}" + ("" if ok else f" (want {digest})"))
    print(f"md5 check: {len(want) - bad}/{len(want)} files match {os.path.relpath(ship_path, HERE)}")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(V5X, "bank", CHUNK), help="where v5x.py gen writes the bank")
    ap.add_argument("--ship", default=os.path.join(V5X, f"SHIP_V5X_{CHUNK}.md5"))
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--join-only", action="store_true")
    a = ap.parse_args(argv)
    if not a.check_only:
        got = write_joined(SPLIT_DIR, CLEAN)
        print(f"clean file: joined {os.path.relpath(SPLIT_DIR, HERE)}/*.json -> {os.path.relpath(CLEAN, HERE)} md5 {got} "
              f"({'ok' if got == CLEAN_MD5 else 'EXPECTED ' + CLEAN_MD5})")
        if got != CLEAN_MD5:
            return 2
        if a.join_only:
            return 0
        os.makedirs(a.out, exist_ok=True)
        log = os.path.join(a.out, "gen.log")
        cmd = [sys.executable, os.path.join(V5X, "v5x.py"), "gen", "--clean", CLEAN, "--out-dir", a.out]
        print(f"== v5x {CHUNK}: generating into {os.path.relpath(a.out)}")
        with open(log, "w", encoding="utf-8") as fh:
            rc = subprocess.run(cmd, cwd=V5X, stdout=fh, stderr=subprocess.STDOUT,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")).returncode
        print(f"   v5x.py gen exit {rc}; log: {os.path.relpath(log)}")
        if rc != 0:
            return 1
    return 1 if check(a.out, a.ship) else 0


if __name__ == "__main__":
    sys.exit(main())
