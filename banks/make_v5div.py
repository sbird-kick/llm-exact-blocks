#!/usr/bin/env python3
"""Regenerate bank v5div (division, dividend smaller in half the rows) from its clean templates and check every byte.

    python banks/make_v5div.py                  # check inputs, generate into a temporary folder, check md5s, delete it
    python banks/make_v5div.py --out DIR        # the same, and keep the bank in DIR (DIR must be empty or new)

Bank v5div is the division counterpart of v5's signed subtraction: in 25 languages, every
division template is filled with the dividend larger in half the rows and smaller in the
other half (the answer is then a fraction or a percentage below 100), and with the
dividend written first in half and second in half. So neither "the bigger number is the
dividend" nor "the first number is the dividend" beats a coin. Four kinds of division:
share (an amount split equally), rate (an amount per unit of time or distance), ratio
(what fraction of ...) and pct (what percent of ...); three shapes; v5's distractor arms.

The inputs are v5div/v5div.py and the clean files of chunks P1 (the pilot), R1, R2 and R3
(851 kept templates, 24 rows each = 20,424 rows, 66.6 MB); v5div.py imports the v5 tools in
banks/v5/. Generation takes about ten seconds, standard library only, and its bytes do not
depend on PYTHONHASHSEED. The generated rows are also shipped, split in parts, in
data/banks/v5div/ (see data/DATA_banks.md and banks/make_bank_data.py).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BANK = os.path.join(HERE, "v5div")
CLEAN = ["clean/P1.json", "clean/R1.json", "clean/R2.json", "clean/R3.json"]

sys.path.insert(0, HERE)
from make_banks import md5_of, read_ship  # noqa: E402


def check_inputs() -> int:
    want = read_ship(os.path.join(BANK, "CODE.md5"))
    bad = [rel for rel in sorted(want) if not os.path.exists(os.path.join(BANK, rel))
           or md5_of(os.path.join(BANK, rel)) != want[rel]]
    print(f"input check: {len(want) - len(bad)}/{len(want)} inputs match v5div/CODE.md5")
    for rel in bad:
        print(f"   DIFFERS: v5div/{rel}")
    return len(bad)


def check_outputs(out: str) -> int:
    want = read_ship(os.path.join(BANK, "SHIP_V5DIV.md5"))
    bad = 0
    for rel, digest in sorted(want.items()):
        p = os.path.join(out, rel)
        got = md5_of(p) if os.path.exists(p) else "missing"
        ok = got == digest
        bad += not ok
        print(f"   {'ok  ' if ok else 'BAD '} {rel} {got}" + ("" if ok else f" (want {digest})"))
    print(f"md5 check: {len(want) - bad}/{len(want)} files match v5div/SHIP_V5DIV.md5")
    return bad


def generate(out: str) -> int:
    """Run v5div.py gen into `out` (which must be empty or new); returns its exit code."""
    cmd = [sys.executable, "v5div.py", "gen", "--clean", ",".join(CLEAN), "--out-dir", out]
    r = subprocess.run(cmd, cwd=BANK, capture_output=True, text=True,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    lines = (r.stdout + r.stderr).strip().splitlines()
    print("   " + (lines[-1] if lines else "v5div.py gen printed nothing"))
    return r.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", help="keep the generated bank here (default: a temporary folder, deleted afterwards)")
    ap.add_argument("--skip-input-check", action="store_true", help="generate even if an input changed")
    a = ap.parse_args(argv)
    if check_inputs() and not a.skip_input_check:
        print("refusing to generate from changed inputs (--skip-input-check overrides)")
        return 2
    tmp = None if a.out else tempfile.mkdtemp(prefix="v5div_")
    out = os.path.abspath(a.out) if a.out else os.path.join(tmp, "bank")
    try:
        print(f"== v5div: generating into {out}")
        rc = generate(out)
        if rc != 0:
            print(f"v5div.py gen exit {rc}")
            return 1
        bad = check_outputs(out)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
