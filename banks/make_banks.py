#!/usr/bin/env python3
"""Regenerate the multilingual signed banks from their templates and check every byte.

    python banks/make_banks.py                    # all three banks -> banks/<bank>/, then the md5 check
    python banks/make_banks.py --banks v4wild     # one bank
    python banks/make_banks.py --check-only       # only compare banks/<bank>/ with SHIP.md5

Before generating it checks the 185 inputs (the generator and the template files in
verified/, distfact/, distfact2/ and writers_wild/) against INPUTS.md5, so a changed
template is named before it can move a bank md5 (--skip-input-check to generate anyway).

The banks land in banks/v3_61/, banks/v4/ and banks/v4wild/ (ignored by git), which is
also where the v5 tools look for the v4 banks.

Standard library only; about half a minute and 330 MB of output for all three banks.

The generator is deterministic (every random draw is keyed through blake2b, never through
Python's per-process hash), so the same templates give the same bytes on any machine and
any Python 3. SHIP.md5 lists the md5 of every file the generator writes for the three
banks; a regeneration that does not reproduce every one of them is not the bank.

The language lists are PINNED here rather than read from the directory: the generator
takes every template file it finds unless told otherwise, so a new language added to
verified/ later would otherwise silently change the bytes of "v3_61".
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

V3_61_LANGS = ("am ar bg bn bo cs de el en es eu fa fi fr gu ha he hi hu hy id is it ja ka kk km "
               "kn ko la lt ml mn mr ms my ne nl pa pl pt ro ru si sk sq sr sv sw ta te th tl tr "
               "uk ur uz vi yo zh zu").split()
V4_LANGS = "ar bn de el en es fa fr he hi id it ja ko nl pl pt ru sw ta th tr uk vi zh".split()

# bank -> generator arguments (relative to --root) and the files it writes
BANKS = {
    "v3_61": ["--bank-version", "v3", "--langs", ",".join(V3_61_LANGS)],
    "v4": ["--bank-version", "v4", "--langs", ",".join(V4_LANGS), "--pairs-out", "{out}/pairs.json"],
    "v4wild": ["--bank-version", "v4", "--src", "{root}/writers_wild", "--suffix", ".json",
               "--id-prefix", "sgw", "--pairs-out", "{out}/pairs.json"],
}


def needed_inputs(root: str) -> list[str]:
    """Every input the three banks read, as paths under root."""
    paths = [os.path.join(root, "gen_signed_bank_ml.py"),
             os.path.join(root, "writers_wild", "en_wild.json")]
    for code in V3_61_LANGS:
        paths.append(os.path.join(root, "verified", f"{code}.verified.json"))
        paths.append(os.path.join(root, "distfact", f"{code}.json"))
        paths.append(os.path.join(root, "distfact2", f"{code}.json"))
    return paths


def md5_of(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_ship(path: str) -> dict[str, str]:
    want = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                digest, rel = line.split(None, 1)
                want[rel] = digest
    return want


def check(out: str, banks, ship: dict[str, str], label: str = "SHIP.md5") -> int:
    bad = 0
    rels = [r for r in sorted(ship) if r.split("/")[0] in banks]
    for rel in rels:
        path = os.path.join(out, rel)
        got = md5_of(path) if os.path.exists(path) else "MISSING"
        ok = got == ship[rel]
        bad += not ok
        size = os.path.getsize(path) if os.path.exists(path) else 0
        print(f"  {'ok  ' if ok else 'FAIL'} {rel:<28} {size:>11,} B  {got}")
    print(f"md5 check: {len(rels) - bad}/{len(rels)} files match {label}")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=HERE,
                    help="directory holding gen_signed_bank_ml.py, verified/, distfact/, distfact2/, writers_wild/")
    ap.add_argument("--out", default=HERE, help="the banks are written to <out>/<bank>/")
    ap.add_argument("--ship", default=os.path.join(HERE, "SHIP.md5"))
    ap.add_argument("--inputs-md5", default=os.path.join(HERE, "INPUTS.md5"))
    ap.add_argument("--skip-input-check", action="store_true",
                    help="generate even if an input differs from INPUTS.md5 (the bank md5s will then say whether it mattered)")
    ap.add_argument("--banks", default=",".join(BANKS))
    ap.add_argument("--check-only", action="store_true")
    a = ap.parse_args(argv)
    banks = [b for b in a.banks.split(",") if b]
    unknown = set(banks) - set(BANKS)
    if unknown:
        raise SystemExit(f"unknown bank(s) {sorted(unknown)}; choose from {list(BANKS)}")
    ship = read_ship(a.ship)

    if not a.check_only:
        missing = [p for p in needed_inputs(a.root) if not os.path.exists(p)]
        if missing:
            print(f"{len(missing)} input file(s) missing under {a.root}; first few:")
            for p in missing[:8]:
                print("   ", os.path.relpath(p, a.root))
            print("See banks/README.md for which files belong here.")
            return 2
        if not a.skip_input_check and os.path.exists(a.inputs_md5):
            want = read_ship(a.inputs_md5)
            changed = [rel for rel in sorted(want)
                       if md5_of(os.path.join(a.root, rel)) != want[rel]]
            print(f"input check: {len(want) - len(changed)}/{len(want)} inputs match INPUTS.md5")
            if changed:
                for rel in changed[:8]:
                    print("    changed:", rel)
                print("A changed input gives a different bank; rerun with --skip-input-check to generate anyway.")
                return 2
        gen = os.path.join(a.root, "gen_signed_bank_ml.py")
        for bank in banks:
            out = os.path.join(a.out, bank)
            os.makedirs(out, exist_ok=True)
            args = [x.format(out=out, root=a.root) for x in BANKS[bank]]
            cmd = [sys.executable, gen, "--out-dir", out] + args
            print(f"== {bank}: generating into {os.path.relpath(out)}")
            log = os.path.join(out, "gen.log")
            with open(log, "w", encoding="utf-8") as fh:
                subprocess.run(cmd, check=True, stdout=fh, stderr=subprocess.STDOUT,
                               env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            print(f"   log: {os.path.relpath(log)}")
    return 1 if check(a.out, banks, ship) else 0


if __name__ == "__main__":
    sys.exit(main())
