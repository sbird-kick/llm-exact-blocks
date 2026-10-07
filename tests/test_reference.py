"""The 1.7B reference file and the side-by-side table in defuse.evaluate. CPU, numpy + pytest, synthetic records."""
import collections
import json
import os

from defuse import evaluate as EV

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "data", "wild", "reference", "qwen3-1.7b_h100.json")
MAN = os.path.join(ROOT, "data", "wild", "MANIFEST.jsonl")


def ref():
    return json.load(open(REF))


def test_reference_covers_exactly_the_shipped_rows():
    R = ref()
    man = collections.Counter("%s|%d" % (m["set"], m["fold"]) for m in (json.loads(l) for l in open(MAN)))
    assert {k: c["rows"] for k, c in R["cells"].items()} == dict(man)
    assert R["rows"] == sum(man.values()) == 7497
    for c in R["cells"].values():                                        # internal consistency, n/total style
        assert sum(b["rows"] for b in c["steps"].values()) == c["rows"]
        assert sum(b["host_right"] for b in c["steps"].values()) == c["HR"]
        assert c["broken"] <= c["HR"] and c["fixed"] <= c["rows"] - c["HR"] and c["fires"] <= c["rows"]
        for g in ("gate_no_probe", "gate_project"):
            assert c[g]["fires"] <= c["fires"] and c[g]["broken"] <= c["broken"]
    assert "H100" in R["hardware"] and R["host"] == "Qwen3-1.7B"


def recs_for(cell, n, seed=0):
    s, k = cell.split("|")
    out = []
    for i in range(n):
        hr = (i + seed) % 3 == 0
        fire = i % 5 == 0
        out.append(dict(row_id="we:%s:train:syn-%s-%d" % (s, k, i), fold=int(k), n_numerals=3, host1=None if i == 7 else "1",
                        host1_none=(i == 7), host1_right=hr and i != 7, gold_value="1", gold_steps=1 + i % 4,
                        value24="1" if i % 2 else "2", fire=fire and i != 7, right=bool(i % 2),
                        lp={"20": -1.0, "24": -0.5, "28": -0.7}, nleaves={"20": 2, "24": 2, "28": 2}, steps24=1))
    return out


def test_same_cells_same_counts_are_not_flagged():
    R = ref()
    recs = recs_for("asdiv|2", R["cells"]["asdiv|2"]["rows"])
    t = EV.reference_table(recs, R, label="synthetic")
    assert "NOT THE SAME ROWS" not in t
    assert "| rows | %d | %d |" % (len(recs), R["cells"]["asdiv|2"]["rows"]) in t
    assert "H100" in t and "host labels" in t


def test_a_subset_is_flagged_and_foreign_rows_are_left_out():
    R = ref()
    recs = recs_for("mathqa|3", 200) + [dict(recs_for("asdiv|1", 1)[0], row_id="syn:other:1")]
    t = EV.reference_table(recs, R)
    assert "NOT THE SAME ROWS in 1 cell(s): mathqa|3 (yours 200, reference %d)" % R["cells"]["mathqa|3"]["rows"] in t
    assert "1 of your records are outside the reference's cells" in t


def test_no_reference_for_other_rows():
    t = EV.reference_table([dict(recs_for("asdiv|1", 1)[0], row_id="bank:v6ms:1")], ref())
    assert "reference not available" in t
