#!/usr/bin/env python3
"""CPU tests for what banks/ ships and for data_gen/show_prompts.py. Standard library only.

    python tests/test_banks_shipped.py          (or)      python -m pytest -q tests/test_banks_shipped.py

They check the shipped inputs against their md5 lists (fast: about 13 MB of files), and run
show_prompts.py on a handful of rows written for this test in the v5 row schema (not bank
rows). Regenerating the banks themselves takes minutes and is left to banks/make_banks.py
and banks/make_v5.py.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "banks"))
sys.path.insert(0, os.path.join(ROOT, "data_gen"))

import make_banks as MB  # noqa: E402
import show_prompts as SP  # noqa: E402


def test_bank_inputs_match_inputs_md5():
    want = MB.read_ship(os.path.join(ROOT, "banks", "INPUTS.md5"))
    need = {os.path.relpath(p, os.path.join(ROOT, "banks")) for p in MB.needed_inputs(os.path.join(ROOT, "banks"))}
    assert set(want) == need and len(need) == 185
    bad = [rel for rel in sorted(want) if MB.md5_of(os.path.join(ROOT, "banks", rel)) != want[rel]]
    assert not bad, bad


def test_v5_files_match_v5_code_md5():
    v5 = os.path.join(ROOT, "banks", "v5")
    want = MB.read_ship(os.path.join(v5, "V5_CODE.md5"))
    assert "clean/r1-16/index.json" in want and "gen_v5.py" in want
    assert sum(rel.startswith("clean/r1-16/") and rel.endswith(".json") for rel in want) == 26
    bad = [rel for rel in sorted(want) if MB.md5_of(os.path.join(v5, rel)) != want[rel]]
    assert not bad, bad


def test_v5_clean_files_join_to_the_project_file():
    import make_v5 as M5
    d = M5.join_clean()
    assert len(d["kept"]) == 4352 and len(d["dropped"]) == 448 and d["pending_units"] == []
    assert len({k["lang"] for k in d["kept"]}) == 25
    assert hashlib.md5(M5.dump(d).encode("utf-8")).hexdigest() == M5.CLEAN_MD5 == "e92b1741ff7d4cac752f18bf033f60e9"


def regen_role_bank(bank):
    """Run make_role_banks on one bank (inputs checked, gen run, SHIP md5s compared); about a second."""
    import make_role_banks as MR
    assert bank in MR.BANKS
    assert MR.main([bank]) == 0


def test_subrole_bank_regenerates():
    regen_role_bank("subrole")


def test_subrole_g3_bank_regenerates():
    regen_role_bank("subrole_g3")


def test_no_shipped_file_over_1mb():
    import subprocess
    try:
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        return  # not a git checkout: nothing to check
    big = [f for f in files if os.path.getsize(os.path.join(ROOT, f)) > 1_000_000 and f != "banks/v5/manifest_v5.json"]
    assert not big, big


def fake_row(tid, arm, n, variant, kind, rungs=(), positions=(), tags=(), lang="en", op="subtraction"):
    return dict(row_id=f"sg5:{lang}:A:1:{variant}:qlast:{kind}-0-{arm}", template_id=tid, lang=lang, op=op,
                op_short={"subtraction": "sub", "addition": "add"}[op], dist_arm=arm, n_numerals_written=n,
                variant=variant, kind=kind, d_rungs=list(rungs), d_positions=list(positions), d_tiers=[],
                tags=list(tags), text=f"text {tid} {arm} {variant} {kind}", a=9, b=4, ans=5, ds=[])


ROWS = [
    fake_row("W5-en-u01-01", "base", 2, "min_first", "pos"),
    fake_row("W5-en-u01-01", "T", 3, "sub_first", "neg", ["L2_time"], ["between"]),
    fake_row("W5-en-u01-01", "T+ex+sem", 5, "min_first", "pos", ["L2_time", "L0_kind", "L1_owner_sent"],
             ["between", "before", "after"]),
    fake_row("W5-ru-u02-03", "T", 3, "min_first", "pos", ["L3_list"], ["after"], ["numdep"], lang="ru"),
    fake_row("W5-ru-u02-04", "sem", 3, "min_first", "pos", ["L1_owner_sent"], ["before"], lang="ru", op="addition"),
]


def run(args):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "bank.jsonl")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ROWS))
        out = io.StringIO()
        rc = SP.main(["--bank", p] + args, out=out)
        return rc, out.getvalue()


def test_show_template_variants():
    rc, out = run(["--template", "W5-en-u01-01"])
    assert rc == 0 and out.strip().endswith("3 row(s) shown")


def test_show_filters():
    assert run(["--lang", "ru", "-n", "0"])[1].strip().endswith("2 row(s) shown")
    assert run(["--numerals", "3", "-n", "0"])[1].strip().endswith("3 row(s) shown")
    assert run(["--rung", "L0_kind", "-n", "0"])[1].strip().endswith("1 row(s) shown")
    assert run(["--position", "before", "-n", "0"])[1].strip().endswith("2 row(s) shown")
    assert run(["--tag", "numdep", "-n", "0"])[1].strip().endswith("1 row(s) shown")
    assert run(["--tag", "none", "-n", "0"])[1].strip().endswith("4 row(s) shown")
    assert run(["--op", "add", "-n", "0"])[1].strip().endswith("1 row(s) shown")
    assert run(["--random", "-n", "2"])[1].strip().endswith("2 row(s) shown")


def test_show_count():
    rc, out = run(["--count", "lang,dist_arm"])
    lines = out.strip().splitlines()
    assert rc == 0 and lines[-1].split() == ["5", "total"] and len(lines) == 6


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok    {name}")
            except AssertionError as e:
                fails += 1
                print(f"  FAIL  {name}: {e}")
    print(f"{'0 fail' if not fails else f'{fails} fail'}")
    sys.exit(1 if fails else 0)
