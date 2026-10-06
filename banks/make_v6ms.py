#!/usr/bin/env python3
"""Regenerate bank v6ms (multi-step, 20 languages; the 9 closed rounds) from its templates and check every byte.

    python banks/make_v6ms.py                   # every round: check inputs, generate into a temporary folder, check md5s
    python banks/make_v6ms.py G3r01             # just one round (any of the names in ROUNDS below)
    python banks/make_v6ms.py --out DIR         # keep the rows: round R is written to DIR/R/ (must be empty or new)

Bank v6ms holds two- and three-step word problems written natively in 20 languages, each
template a small program over named slots (a chain of + - x /, a conditional, a max / min,
a rounding ...) that the generator executes exactly, storing every intermediate value in
the row. It is written in rounds; a round is one stratum in all 20 languages (20 writer
units, 8 templates each), blind-verified by executing the verifier's formula. Only the 9
rounds that were closed (verified and cleaned) are shipped:

    G1r01-G1r04  SL   straight-line chains of 2-3 steps, + - x /, signed: (A o1 B) o2 C, ((A o1 B) o2 C) o3 D ...
    G2r01        CB   conditionals: t = A o1 B; IF t cmp C THEN t o2 D ELSE ...
    G2r02        SEL  max / min selection: max(A, B) o C, min(A o1 B, C o1 D)
    G2r03        INT  ceil / floor / remainder: ceil((A o1 B) / C), (A o1 B) mod C ...
    G3r01        INV  unknown start or group size: (C o1 A) o2 B, (C - B) / A
    G3r02        CMQ  "how many more": (A o1 B) - C, always positive

Each round writes rows_le5.jsonl (rows with at most 5 written numerals) and rows_n6.jsonl
(more than 5). 42,268 rows in all; about 35 seconds per round, standard library only. The
rows are also shipped in data/banks/v6ms/ (see data/DATA_banks.md).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BANK = os.path.join(HERE, "v6ms")
ROUNDS = ["G1r01", "G1r02", "G1r03", "G1r04", "G2r01", "G2r02", "G2r03", "G3r01", "G3r02"]

sys.path.insert(0, HERE)
from make_banks import md5_of, read_ship  # noqa: E402


def check_inputs() -> int:
    want = read_ship(os.path.join(BANK, "CODE.md5"))
    bad = [rel for rel in sorted(want) if not os.path.exists(os.path.join(BANK, rel))
           or md5_of(os.path.join(BANK, rel)) != want[rel]]
    print(f"input check: {len(want) - len(bad)}/{len(want)} inputs match v6ms/CODE.md5")
    for rel in bad[:20]:
        print(f"   DIFFERS: v6ms/{rel}")
    return len(bad)


def round_units(rnd: str) -> list[str]:
    """The round's writer units that have an acceptance stamp, in manifest order."""
    man = json.load(open(os.path.join(BANK, "manifest", "units.json"), encoding="utf-8"))
    return [u["uid"] for u in man["writer_units"]
            if u["round"] == rnd and os.path.exists(os.path.join(BANK, "accept", u["uid"] + ".json"))]


def generate(rnd: str, out: str) -> int:
    units = round_units(rnd)
    cmd = [sys.executable, "v6ms.py", "gen", "--units", ",".join(units), "--out-dir", out]
    r = subprocess.run(cmd, cwd=BANK, capture_output=True, text=True,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    try:
        rep = json.load(open(os.path.join(out, "GEN_REPORT.json"), encoding="utf-8"))
        print(f"   {rnd}: {len(units)} writer units, {rep['rows']} rows ({rep['le5']} + {rep['n6']}), "
              f"skipped {rep['skipped']}, refused fills {sum(rep['refused'].values())}, "
              f"audit violations: {rep['audit']['violations'] or 'NONE'}")
    except (OSError, ValueError, KeyError):
        print((r.stdout + r.stderr).strip()[-2000:])
    return r.returncode


def check_round(rnd: str, out: str) -> int:
    want = {rel: d for rel, d in read_ship(os.path.join(BANK, "SHIP_V6MS.md5")).items() if rel.startswith(rnd + "/")}
    bad = 0
    for rel, digest in sorted(want.items()):
        p = os.path.join(out, os.path.basename(rel))
        got = md5_of(p) if os.path.exists(p) else "missing"
        ok = got == digest
        bad += not ok
        print(f"   {'ok  ' if ok else 'BAD '} {rel} {got}" + ("" if ok else f" (want {digest})"))
    return bad if want else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rounds", nargs="*", help=f"any of {', '.join(ROUNDS)} (default: all)")
    ap.add_argument("--out", help="keep the rows: round R goes to OUT/R/ (default: a temporary folder, deleted)")
    ap.add_argument("--skip-input-check", action="store_true", help="generate even if an input changed")
    a = ap.parse_args(argv)
    names = a.rounds or ROUNDS
    unknown = [r for r in names if r not in ROUNDS]
    if unknown:
        ap.error(f"unknown round(s) {unknown}; known: {ROUNDS}")
    if check_inputs() and not a.skip_input_check:
        print("refusing to generate from changed inputs (--skip-input-check overrides)")
        return 2
    tmp = None if a.out else tempfile.mkdtemp(prefix="v6ms_")
    base = os.path.abspath(a.out) if a.out else tmp
    bad = 0
    try:
        for rnd in names:
            out = os.path.join(base, rnd)
            if generate(rnd, out) != 0:
                print(f"   {rnd}: v6ms.py gen failed")
                bad += 1
                continue
            bad += check_round(rnd, out)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    n = 2 * len(names)
    print(f"md5 check: {n - bad}/{n} files match v6ms/SHIP_V6MS.md5" if bad <= n else f"{bad} problem(s)")
    print("ALL OK" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
