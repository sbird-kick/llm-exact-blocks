"""data/more/: md5s, sizes, train-only rows, manifests, the gold parse. CPU, numpy + pytest."""
import glob
import hashlib
import json
import os

import pytest

from defuse import data as D
from defuse import guard as G
from defuse import more as M
from defuse import reader_a as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MORE = os.path.join(ROOT, "data", "more")
WANT = dict(reversed(l.split()) for l in open(os.path.join(MORE, "MORE.md5")) if l.strip())
DATA_FILES = sorted(r for r in WANT if not r.endswith("MANIFEST.jsonl"))
SETS = {"ape210k": 95808, "math23k": 11676, "mathqa": 1622, "asdiv": 185, "mawps": 196, "selfcue_v1": 7270,
        "selfcue_v2": 6836, "selfcue_v3": 5495, "selfcue_v4": 7966, "selfcue_v5": 47237, "selfcue_v24": 6389,
        "bigbench_arith": 10516, "bbx": 5040, "wildbig": 1096}
FORBIDDEN = ("host1", "host1_none", "host1_right", "host_right", "host_none", "greedy_raw", "greedy_int", "greedy_ok",
             "near_dup_ref", "never_fit", "test_only", "dump_bank_eligible", "n_prompt_tokens", "text_raw",
             "manifest_split", "split", "orig_gold", "orig_qnums")
SEALED_WORDS = ("sealed", "wildbig_test", "wildbigtest", "gold_", "_test")


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def rows_of(rel):
    return [json.loads(l) for l in open(os.path.join(MORE, rel), encoding="utf-8") if l.strip()]


def test_md5s_and_sizes():
    on_disk = {os.path.relpath(p, MORE) for p in glob.glob(os.path.join(MORE, "**", "*.jsonl"), recursive=True)}
    assert on_disk == set(WANT) and len(WANT) == 40
    for rel, h in WANT.items():
        p = os.path.join(MORE, rel)
        assert md5(p) == h, rel
        assert os.path.getsize(p) < 25_000_000, rel
        assert not any(w in rel.lower() for w in SEALED_WORDS), rel


def test_manifest_is_train_only_and_matches_the_files():
    man = M.manifest()
    assert len(man) == sum(SETS.values()) == 207332
    assert {m["split"] for m in man.values()} == {"train"}
    n = 0
    seen = {}
    for rel in DATA_FILES:
        for r in rows_of(rel):
            n += 1
            m = man[r["row_id"]]
            assert m["split"] == "train" and m["file"] == rel and m["fold"] == r["fold"] in (1, 2, 3, 4), r["row_id"]
            assert m["family"] == r["family"] and m["n_runs"] == r["prov"]["n_runs"], r["row_id"]
            assert r["row_id"] not in seen, r["row_id"]
            seen[r["row_id"]] = rel
            assert r["status"] == "scored" and r["text"].endswith("The answer is")
            assert r["pool"]["gold_status"] == m["gold_status"]
            bad = [c for c in FORBIDDEN if c in r]
            assert not bad, (r["row_id"], bad)
    assert n == len(man)


def test_per_source_counts():
    man = M.manifest()
    got = {}
    for m in man.values():
        s = m["file"].split("/")[1]
        got[s] = got.get(s, 0) + 1
    assert got == SETS
    assert sum(1 for m in man.values() if m.get("thinking_subset")) == 3683


def test_no_row_of_data_wild_is_repeated_here():
    old = {json.loads(l)["row_id"] for l in open(os.path.join(ROOT, "data", "wild", "MANIFEST.jsonl"))}
    assert not old & set(M.manifest())


def test_loader_accepts_the_shipped_files_for_fitting():
    for rel in DATA_FILES:      # every file, so no folder or file name can trip guard.check_path for a student
        rows = D.load_rows(os.path.join(MORE, rel), fit=True)
        assert rows and all(r["fold"] in D.FIT_FOLDS for r in rows)


def test_concat_writes_only_checked_rows(tmp_path):
    out = tmp_path / "rows.jsonl"
    assert M.concat(str(out), sets=["mawps", "asdiv"]) == 196 + 185
    assert M.concat(str(out), per_file=3) == 3 * len(DATA_FILES)


def _copy_more(tmp_path, mutate):
    """a copy of two small sets with a tampered manifest, md5s re-written so only the manifest rule can object"""
    import shutil
    dst = tmp_path / "more"
    for rel in ("wild/mawps", "wild/asdiv"):
        shutil.copytree(os.path.join(MORE, rel), dst / rel)
    mp = dst / "wild" / "mawps" / "MANIFEST.jsonl"
    lines = [json.loads(l) for l in open(mp, encoding="utf-8")]
    mutate(lines)
    with open(mp, "w", encoding="utf-8") as f:
        for m in lines:
            f.write(json.dumps(m, sort_keys=True) + "\n")
    with open(dst / "MORE.md5", "w") as f:
        for p in sorted(glob.glob(str(dst / "**" / "*.jsonl"), recursive=True)):
            f.write("%s  %s\n" % (md5(p), os.path.relpath(p, dst)))
    return str(dst)


@pytest.mark.parametrize("bad", ["val", "test", "dropped"])
def test_refuses_a_row_that_is_not_train_in_the_manifest(tmp_path, bad):
    def mutate(lines):
        lines[0]["split"] = bad
    with pytest.raises(G.Refused):
        M.concat(str(tmp_path / "o.jsonl"), more=_copy_more(tmp_path, mutate))


def test_refuses_a_row_missing_from_the_manifest(tmp_path):
    with pytest.raises(G.Refused):
        M.concat(str(tmp_path / "o.jsonl"), more=_copy_more(tmp_path, lambda lines: lines.pop(0)))


def test_refuses_a_file_that_does_not_match_its_md5(tmp_path):
    d = _copy_more(tmp_path, lambda lines: None)
    p = os.path.join(d, "wild", "asdiv", "part_000.jsonl")
    open(p, "a").write("\n")
    with pytest.raises(SystemExit):
        M.concat(str(tmp_path / "o.jsonl"), more=d)


def test_gold_programs_parse_as_the_manifest_says_on_a_sample():
    """the package's parser reproduces gold_status on every row of the small sets and on every 20th row of the rest"""
    for rel in DATA_FILES:
        rows = rows_of(rel)
        step = 1 if len(rows) < 2500 else 20
        for r in rows[::step]:
            assert A.gold_tree(r)[1] == r["pool"]["gold_status"], r["row_id"]
