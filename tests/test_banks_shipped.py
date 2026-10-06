#!/usr/bin/env python3
"""CPU tests for what banks/ ships and for data_gen/show_prompts.py. Standard library only.

    python tests/test_banks_shipped.py          (or)      python -m pytest -q tests/test_banks_shipped.py

They check the shipped inputs against their md5 lists (fast: about 25 MB of files), the shipped
training rows in data/banks/ against data/banks/ROWS.md5, regenerate the small banks, and run
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


def test_divrole2_bank_regenerates():
    regen_role_bank("divrole2")


def test_v5x_inputs_and_join():
    """v5x (all six chunks): every shipped input matches CODE.md5, and each chunk's language files join byte for byte."""
    import clean_split as CS
    import make_v5x as MX
    v5x = os.path.join(ROOT, "banks", "v5x")
    want = MB.read_ship(os.path.join(v5x, "CODE.md5"))
    assert len(want) == 189
    bad = [rel for rel in sorted(want) if MB.md5_of(os.path.join(v5x, rel)) != want[rel]]
    assert not bad, bad
    kept_want = {"C1": (274, 14), "C2": (283, 5), "C3": (286, 2), "C4": (277, 11), "C5": (276, 12), "C6": (279, 9)}
    langs = set()
    for chunk, (n_kept, n_dropped) in kept_want.items():
        b, md5 = CS.join_clean(os.path.join(v5x, "clean", chunk))
        assert hashlib.md5(b).hexdigest() == md5 == MX.CHUNKS[chunk], chunk
        d = json.loads(b)
        assert len(d["kept"]) == n_kept and len(d["dropped"]) == n_dropped, chunk
        assert len({e["lang"] for e in d["kept"]}) == 6, chunk
        langs |= {e["lang"] for e in d["kept"]}
    assert len(langs) == 36


def test_abstainbank_templates_match_code_md5():
    d = os.path.join(ROOT, "banks", "abstainbank")
    want = MB.read_ship(os.path.join(d, "CODE.md5"))
    assert len(want) == 8
    bad = [rel for rel in sorted(want) if MB.md5_of(os.path.join(d, rel)) != want[rel]]
    assert not bad, bad
    kept = [e for rel in want for e in json.load(open(os.path.join(d, rel), encoding="utf-8"))["kept"]]
    assert len(kept) == 503 == len({e["template"]["id"] for e in kept})


def test_abstainbank_x_templates_match_and_join():
    import clean_split as CS
    d = os.path.join(ROOT, "banks", "abstainbank_x")
    want = MB.read_ship(os.path.join(d, "CODE.md5"))
    assert len(want) == 35
    bad = [rel for rel in sorted(want) if MB.md5_of(os.path.join(d, rel)) != want[rel]]
    assert not bad, bad
    ids = set()
    for rnd, md5_want, n_kept, n_dropped in (("X01r1", "d279cab3f4f278f1b85f065bdd2ae99d", 68, 28),
                                              ("X01r2", "9bfef48eb823d21734dff0777d198504", 80, 16),
                                              ("X01r3", "0e6f1806b01e16b34824f8f6c82d7fac", 83, 13),
                                              ("X01r4", "a3c22d2816d89ce01533ef9249656223", 73, 23),
                                              ("X01r5", "2b594934e8d539a5d195d6d7da6ba14b", 86, 10)):
        b, md5 = CS.join_clean(os.path.join(d, "clean", rnd))
        assert hashlib.md5(b).hexdigest() == md5 == md5_want, rnd
        j = json.loads(b)
        assert len(j["kept"]) == n_kept and len(j["dropped"]) == n_dropped, rnd
        ids |= {e["template"]["id"] for e in j["kept"]}
    assert len(ids) == 390


def test_audience_bank_v2_regenerates():
    """the demo audience bank v2 (about a second): inputs match CODE.md5, gen_audience_v2.py reproduces its md5s"""
    import subprocess
    d = os.path.join(ROOT, "banks", "audience")
    want = MB.read_ship(os.path.join(d, "CODE.md5"))
    assert len(want) == 8 and not [r for r in want if MB.md5_of(os.path.join(d, r)) != want[r]]
    with tempfile.TemporaryDirectory() as out:
        subprocess.run([sys.executable, "gen_audience_v2.py", "--final", "--audit", "audit.json", "--out", out],
                       cwd=d, check=True, capture_output=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        ship = MB.read_ship(os.path.join(d, "SHIP_AUDIENCE_V2.md5"))
        bad = [r for r in ship if MB.md5_of(os.path.join(out, r)) != ship[r]]
        assert len(ship) == 8 and not bad, bad


def test_v5x_regenerates():
    """about thirty seconds: for each of the six chunks, join, v5x.py gen, six md5s"""
    import make_v5x as MX
    with tempfile.TemporaryDirectory() as d:
        assert MX.main(["--out", d]) == 0


def test_v5div_inputs_and_regenerates():
    """about ten seconds: v5div's inputs match CODE.md5 and v5div.py gen reproduces the project's six md5s"""
    import make_v5div as MD
    want = MB.read_ship(os.path.join(ROOT, "banks", "v5div", "CODE.md5"))
    assert len(want) == 5 and "clean/R4.json" not in want
    assert not os.path.exists(os.path.join(ROOT, "banks", "v5div", "clean", "R4.json"))  # R4 is the project's fresh test set
    assert MD.main([]) == 0


def test_v6ms_inputs_and_one_round_regenerates():
    """about forty seconds: v6ms's 402 inputs match CODE.md5 and round G3r01 reproduces the project's two md5s
    (python banks/make_v6ms.py checks all nine rounds, about five minutes)"""
    import make_v6ms as M6
    want = MB.read_ship(os.path.join(ROOT, "banks", "v6ms", "CODE.md5"))
    assert len(want) == 402
    assert sum(r.startswith("writers/") for r in want) == 180 == sum(r.startswith("accept/") for r in want)
    ship = MB.read_ship(os.path.join(ROOT, "banks", "v6ms", "SHIP_V6MS.md5"))
    assert len(ship) == 18 and {r.split("/")[0] for r in ship} == set(M6.ROUNDS)
    assert M6.main(["G3r01"]) == 0


def test_bank_rows_shipped_match_md5():
    """data/banks/: every shipped row file matches data/banks/ROWS.md5, is under 25 MB, and the split parts join
    to the generator's file (about two seconds for ~370 MB)"""
    import make_bank_data as BD
    want = MB.read_ship(BD.ROWS_MD5)
    assert len(want) == 29
    assert {r.split("/")[0] for r in want} == set(BD.BANKS)
    assert BD.check_shipped(BD.BANKS) == 0


def test_divrole2_rows_are_the_bank_without_its_reference_fold():
    """the shipped divrole2 rows = the regenerated bank minus its 640 fold -1 (held-out reference) rows, byte for byte"""
    import make_bank_data as BD
    regen_role_bank("divrole2")
    src, md5_src, _ = BD.FILTERS["divrole2/DIVROLE2_folds0-4.jsonl"]
    raw = open(os.path.join(ROOT, "banks", src), "rb").read()
    assert hashlib.md5(raw).hexdigest() == md5_src
    kept = BD.drop_fold_minus_one(raw)
    assert raw.count(b"\n") - kept.count(b"\n") == 640 and kept.count(b"\n") == 5248
    want = MB.read_ship(BD.ROWS_MD5)["divrole2/DIVROLE2_folds0-4.jsonl"]
    assert hashlib.md5(kept).hexdigest() == want
    assert all(json.loads(ln)["fold"] in (0, 1, 2, 3, 4) for ln in kept.splitlines())


def test_no_shipped_file_over_1mb():
    import subprocess
    try:
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        return  # not a git checkout: nothing to check
    # the shipped training rows (data/banks/*.jsonl) are the one exception: each must stay under 25 MB
    rows = [f for f in files if f.startswith("data/banks/") and f.endswith(".jsonl")]
    big = [f for f in files if os.path.getsize(os.path.join(ROOT, f)) > 1_000_000
           and f != "banks/v5/manifest_v5.json" and f not in rows]
    assert not big, big
    too_big = [f for f in rows if os.path.getsize(os.path.join(ROOT, f)) >= 25_000_000]
    assert not too_big, too_big


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
