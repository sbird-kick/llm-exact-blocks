"""The shipped wild rows (data/wild/): md5s, folds 1-4 only, train split only, no host-outcome columns. CPU, numpy + pytest."""
import glob
import hashlib
import json
import os

import pytest

from defuse import data as D
from defuse import guard as G
from defuse import reader_a as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WILD = os.path.join(ROOT, "data", "wild")
FILES = sorted(glob.glob(os.path.join(WILD, "*", "fold*.jsonl")))
# columns that must never be shipped: host outcomes (regenerate on your host), eval links, the project's bookkeeping
FORBIDDEN = ("host1", "host1_none", "host1_right", "host_right", "host_none", "greedy_raw", "greedy_int", "greedy_ok",
             "near_dup_ref", "never_fit", "test_only", "dump_bank_eligible", "n_prompt_tokens", "text_raw")
EVAL_SETS = ("gsm8k", "mgsm", "afrimgsm", "svamp", "gsmplus", "gsmhard", "fresh")


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def rows_of(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def test_md5s_match_the_record():
    want = dict(reversed(l.split()) for l in open(os.path.join(WILD, "WILD.md5")) if l.strip())
    assert len(want) == 9 and sorted(want) == sorted([os.path.relpath(p, WILD) for p in FILES] + ["MANIFEST.jsonl"])
    for rel, h in want.items():
        assert md5(os.path.join(WILD, rel)) == h, rel


def test_only_folds_1_to_4_and_only_the_two_sets():
    assert {os.path.relpath(p, WILD) for p in FILES} == {"%s/fold%d.jsonl" % (s, k) for s in ("asdiv", "mathqa") for k in (1, 2, 3, 4)}
    n = 0
    for p in FILES:
        k = int(os.path.basename(p)[4])
        s = os.path.basename(os.path.dirname(p))
        for r in rows_of(p):
            n += 1
            assert r["fold"] == k and r["fold"] in (1, 2, 3, 4)
            assert r["source_set"] == s and r["row_id"].startswith("we:%s:" % s)
            assert r["source_split"] == ("train" if s == "mathqa" else "all")
            assert r["status"] == "scored" and r["text"].endswith("The answer is")
            assert not any(e in r["row_id"].lower() for e in EVAL_SETS)
            bad = [c for c in FORBIDDEN if c in r]
            assert not bad, (r["row_id"], bad)
            assert int(r["prov"]["n_runs"]) <= 5
    assert n == 7497


def test_manifest_lists_every_shipped_row_once():
    man = rows_of(os.path.join(WILD, "MANIFEST.jsonl"))
    ids = [m["row_id"] for m in man]
    assert len(ids) == len(set(ids)) == 7497
    shipped = {r["row_id"]: (os.path.relpath(p, WILD), r["fold"]) for p in FILES for r in rows_of(p)}
    assert {m["row_id"]: (m["file"], m["fold"]) for m in man} == shipped
    assert all(m["fold"] in (1, 2, 3, 4) for m in man)


def test_loader_accepts_the_shipped_files_for_fitting():
    for p in FILES:
        rows = D.load_rows(p, fit=True)
        assert rows and all(r["fold"] in D.FIT_FOLDS for r in rows)


def test_loader_refuses_fold_5_and_6(tmp_path):
    r = rows_of(FILES[0])[0]
    for k in (5, 6):
        p = tmp_path / ("rows_k%d.jsonl" % k)
        p.write_text(json.dumps(dict(r, fold=k)) + "\n", encoding="utf-8")
        with pytest.raises(G.Refused):
            D.load_rows(str(p), fit=True)


def test_gold_programs_parse_as_the_project_parsed_them():
    """the shipped gold_status is the project's; the package's parser must reproduce it on every row"""
    for p in FILES:
        for r in rows_of(p):
            assert A.gold_tree(r)[1] == r["pool"]["gold_status"], r["row_id"]
