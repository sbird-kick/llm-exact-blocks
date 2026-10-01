#!/usr/bin/env python3
"""Regenerate the English role banks from their clean templates and check every byte.

    python banks/make_role_banks.py                 # every role bank: check inputs, generate, check md5s
    python banks/make_role_banks.py subrole         # just one (any of the names in BANKS below)
    python banks/make_role_banks.py --check-only    # only compare <bank>/bank/ with its SHIP md5 file

A role bank is a bank where the ROLE of each operand (the minuend of a subtraction, the
dividend of a division) is fixed by the words of the story and never by its size or by
the order in which the two numbers are written. Each bank lives in its own folder with the
tool that made it:

    banks/<bank>/<tool>.py          the project's tool (writer validator, blind close, clean, gen, selftest)
    banks/<bank>/clean/*.json       the templates that blind verification kept (and the dropped ones, with reasons)
    banks/<bank>/CODE.md5           md5 of every shipped input
    banks/<bank>/SHIP_<NAME>.md5    md5 of the files `<tool>.py gen` writes, as the project recorded them

`<tool>.py gen` writes banks/<bank>/bank/dump/<NAME>.jsonl and banks/<bank>/bank/bank_census.json
(ignored by git). Each takes about a second, standard library only, and the bytes do not
depend on the machine or on PYTHONHASHSEED (every random draw is seeded by a string).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_banks import md5_of, read_ship  # noqa: E402

# name -> (tool, SHIP file); the order matters: subrole_g3 reads subrole/ (its stamped bank)
BANKS = {
    "subrole": ("subrole.py", "SHIP_SUBROLE.md5"),
}


def check_inputs(bank: str) -> int:
    d = os.path.join(HERE, bank)
    want = read_ship(os.path.join(d, "CODE.md5"))
    bad = [rel for rel in sorted(want) if not os.path.exists(os.path.join(d, rel))
           or md5_of(os.path.join(d, rel)) != want[rel]]
    print(f"   input check: {len(want) - len(bad)}/{len(want)} inputs match {bank}/CODE.md5")
    for rel in bad:
        print(f"   DIFFERS: {bank}/{rel}")
    return len(bad)


def check_outputs(bank: str) -> int:
    d = os.path.join(HERE, bank)
    tool, ship = BANKS[bank]
    want = read_ship(os.path.join(d, ship))
    bad = 0
    for rel, digest in sorted(want.items()):
        p = os.path.join(d, "bank", rel)
        got = md5_of(p) if os.path.exists(p) else "missing"
        ok = got == digest
        bad += not ok
        print(f"   {'ok  ' if ok else 'BAD '} {bank}/bank/{rel} {got}" + ("" if ok else f" (want {digest})"))
    print(f"   md5 check: {len(want) - bad}/{len(want)} files match {bank}/{ship}")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("banks", nargs="*", help=f"any of {', '.join(BANKS)} (default: all)")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--skip-input-check", action="store_true", help="generate even if a template file changed")
    a = ap.parse_args(argv)
    names = a.banks or list(BANKS)
    unknown = [n for n in names if n not in BANKS]
    if unknown:
        ap.error(f"unknown bank(s) {unknown}; known: {list(BANKS)}")
    bad = 0
    for bank in names:
        tool, _ = BANKS[bank]
        print(f"== {bank}")
        if not a.check_only:
            if check_inputs(bank) and not a.skip_input_check:
                print("   refusing to generate from changed inputs (--skip-input-check overrides)")
                bad += 1
                continue
            r = subprocess.run([sys.executable, tool, "gen"], cwd=os.path.join(HERE, bank),
                               capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            out = (r.stdout + r.stderr).strip().splitlines()
            print("   " + (out[-1] if out else f"{tool} gen printed nothing"))
            if r.returncode != 0:
                print(f"   {tool} gen exit {r.returncode}")
                bad += 1
                continue
        bad += check_outputs(bank)
    print("ALL OK" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
