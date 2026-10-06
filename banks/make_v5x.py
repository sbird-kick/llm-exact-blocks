#!/usr/bin/env python3
"""Regenerate bank v5x (all six chunks, C1-C6) from its per-language clean files and check every byte.

    python banks/make_v5x.py                    # every chunk: join clean/<C>/*.json, check its md5, v5x.py gen -> banks/v5x/bank/<C>/, check
    python banks/make_v5x.py C3                 # just one chunk (any of C1 ... C6)
    python banks/make_v5x.py --check-only       # only compare banks/v5x/bank/<C>/ with banks/v5x/SHIP_V5X_<C>.md5
    python banks/make_v5x.py --join-only        # only rebuild banks/v5x/clean/clean_v5x_<C>.json and check its md5

Bank v5x is bank v5 (wild-shaped distractors, add / sub / mul / div, the same row schema)
extended to the 36 languages of v3_61 that v5 lacks, with a question-form axis F0-F7. It was
written in 6 chunks of 6 languages, each blind-verified and cleaned on its own (every chunk
passed all eight of its go / no-go bars); each chunk has its own clean/<C>/ folder, its own
joined clean file and its own SHIP_V5X_<C>.md5, so the chunks are generated one at a time
(pair tables and story ids are per chunk, exactly as the project's tool does it).

v5x.py wraps the v5 tools in banks/v5/ (it edits none of them) and reads
banks/v5x/manifest/ (the unit specs; their forms and story ids enter the rows). The project
did not generate v5x rows itself, so the SHIP md5s were recorded for this repository: chunk
C1 on 2026-10-01, chunks C2-C6 on 2026-10-06, each identical under PYTHONHASHSEED=1 and 7,
and identical with the project's own (later) copy of v5x.py. About five seconds per chunk.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
V5X = os.path.join(HERE, "v5x")
# chunk -> md5 of its joined clean file (the project's clean_v5x_<C>.json, byte for byte)
CHUNKS = {
    "C1": "476b62cf4e7a4fd33c68c0bd8eedb32e",
    "C2": "52a9d6f1957ef3f58df267ada0a65430",
    "C3": "e4f1756c15e82da9764c56ad0e569888",
    "C4": "b5107319ab033f718001eb34fafd6e10",
    "C5": "b11bf9987116cdbb594a47ad557b3474",
    "C6": "8fef25989c1022817d7d4a89ddd74f61",
}
# kept for older callers: chunk C1's values
CHUNK = "C1"
SPLIT_DIR = os.path.join(V5X, "clean", CHUNK)
CLEAN = os.path.join(V5X, "clean", f"clean_v5x_{CHUNK}.json")
CLEAN_MD5 = CHUNKS[CHUNK]

sys.path.insert(0, HERE)
from clean_split import write_joined  # noqa: E402
from make_banks import md5_of, read_ship  # noqa: E402


def split_dir(chunk: str) -> str:
    return os.path.join(V5X, "clean", chunk)


def clean_path(chunk: str) -> str:
    return os.path.join(V5X, "clean", f"clean_v5x_{chunk}.json")


def ship_path(chunk: str) -> str:
    return os.path.join(V5X, f"SHIP_V5X_{chunk}.md5")


def check(out: str, ship: str) -> int:
    want = read_ship(ship)
    bad = 0
    for rel, digest in sorted(want.items()):
        p = os.path.join(out, rel)
        got = md5_of(p) if os.path.exists(p) else "missing"
        ok = got == digest
        bad += not ok
        print(f"   {'ok  ' if ok else 'BAD '} {os.path.relpath(p, HERE)} {got}" + ("" if ok else f" (want {digest})"))
    print(f"md5 check: {len(want) - bad}/{len(want)} files match {os.path.relpath(ship, HERE)}")
    return bad


def join(chunk: str) -> bool:
    got = write_joined(split_dir(chunk), clean_path(chunk))
    want = CHUNKS[chunk]
    print(f"clean file: joined {os.path.relpath(split_dir(chunk), HERE)}/*.json -> "
          f"{os.path.relpath(clean_path(chunk), HERE)} md5 {got} ({'ok' if got == want else 'EXPECTED ' + want})")
    return got == want


def gen(chunk: str, out: str) -> int:
    os.makedirs(out, exist_ok=True)
    log = os.path.join(out, "gen.log")
    cmd = [sys.executable, os.path.join(V5X, "v5x.py"), "gen", "--clean", clean_path(chunk), "--out-dir", out]
    print(f"== v5x {chunk}: generating into {os.path.relpath(out)}")
    with open(log, "w", encoding="utf-8") as fh:
        rc = subprocess.run(cmd, cwd=V5X, stdout=fh, stderr=subprocess.STDOUT,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")).returncode
    print(f"   v5x.py gen exit {rc}; log: {os.path.relpath(log)}")
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("chunks", nargs="*", help=f"any of {', '.join(CHUNKS)} (default: all)")
    ap.add_argument("--out", default=os.path.join(V5X, "bank"),
                    help="base folder: chunk <C> is written to <out>/<C>/ (default banks/v5x/bank)")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--join-only", action="store_true")
    a = ap.parse_args(argv)
    names = a.chunks or list(CHUNKS)
    unknown = [c for c in names if c not in CHUNKS]
    if unknown:
        ap.error(f"unknown chunk(s) {unknown}; known: {list(CHUNKS)}")
    bad = 0
    for chunk in names:
        out = os.path.join(a.out, chunk)
        if not a.check_only:
            if not join(chunk):
                return 2
            if a.join_only:
                continue
            if gen(chunk, out) != 0:
                bad += 1
                continue
        if not a.join_only:
            bad += check(out, ship_path(chunk))
    if not a.join_only:
        print("ALL OK" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
