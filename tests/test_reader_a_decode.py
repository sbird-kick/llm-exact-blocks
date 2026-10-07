"""Reader A's decoder against the pinned project file. CPU only (numpy + pytest), synthetic rows only.

tests/fixtures/reader_a_decode.json was written by running the PINNED `defuse_reader.py`
(md5 d2eb8b33672d3cb03c7f16c5dfede819) on synthetic rows (its own `_syn_rows` / `_syn_states`, seed 20261007): oracle
head outputs, the same outputs with Gaussian noise added (so the beam has to rank close programs), flat head outputs
(a negative control), the answer-only program search, and reader A fitted end to end on planted states
(tests/fixtures/reader_a_states.npz). Every check below asks the ported `defuse.reader_a` for the same output.
Program strings must be equal; beam scores equal to 1e-9 (the same float operations; the tolerance only allows for
a different libm on another machine).
"""
import json
import math
import os
from fractions import Fraction

import numpy as np
import pytest

from defuse import reader_a as A

HERE = os.path.dirname(os.path.abspath(__file__))
FX_PATH = os.path.join(HERE, "fixtures", "reader_a_decode.json")
NPZ_PATH = os.path.join(HERE, "fixtures", "reader_a_states.npz")


@pytest.fixture(scope="module")
def FX():
    return json.load(open(FX_PATH))


def P_from_json(d):
    return dict(leafable=d["leafable"],
                run={int(k): {h: np.array(v) for h, v in hd.items()} for k, hd in d["run"].items()},
                sib={tuple(int(x) for x in k.split(",")): np.array(v) for k, v in d["sib"].items()},
                steps=np.array(d["steps"]), root=np.array(d["root"]), consts=d["consts"],
                run_value={int(k): (int(ni), Fraction(v)) for k, (ni, v) in d["run_value"].items()})


def dec(res):
    t, s, info = res
    return dict(canon=None if t is None else A.canon(t), value=None if t is None else str(A.execute(t)),
                score=None if s == -math.inf else float(s), info=dict(info))


def same(got, want):
    assert got["canon"] == want["canon"] and got["value"] == want["value"] and got["info"] == want["info"]
    if want["score"] is None:
        assert got["score"] is None
    else:
        assert abs(got["score"] - want["score"]) <= 1e-9 * max(1.0, abs(want["score"]))


def oracle(FX, i):
    r = FX["rows"][i]
    t, st = A.gold_tree(r)
    assert st == "exec_exact"
    tg = A.targets_from_tree(t, r, 5)
    return t, tg, A.oracle_P(tg, r, 5)


def test_oracle_beam64_all_rows(FX):
    n = 0
    for e in FX["oracle"]:
        t, tg, P = oracle(FX, e["i"])
        assert tg["decodable"] == e["decodable"]
        if not e["decodable"]:
            continue
        assert A.canon(t) == e["gold"] and A.a_identifiable(t) == e["a_identifiable"]
        same(dec(A.decode(P)), e["beam64"]); n += 1
    assert n > 200


def test_oracle_beam256_subset(FX):
    es = [e for e in FX["oracle"] if e["decodable"]][:40]
    for e in es:
        _, _, P = oracle(FX, e["i"])
        same(dec(A.decode(P, beam=256)), e["beam256"])
    # the pinned selftest's own bar: every A-identifiable program is recovered from oracle heads
    ok = [e["beam256"]["canon"] == e["gold"] for e in FX["oracle"] if e["decodable"] and e["a_identifiable"]]
    assert ok and all(ok)


def test_noisy_heads_beam_ranking(FX):
    assert len(FX["noisy"]) == 80
    for e in FX["noisy"]:
        P = P_from_json(e["P"])
        same(dec(A.decode(P)), e["beam64"])
        same(dec(A.decode(P, beam=8)), e["beam8"])
        same(dec(A.decode(P, used_thr=0.3)), e["used_thr_03"])


def test_flat_heads_negative_control(FX):
    hits = 0
    for e in FX["flat"]:
        _, _, P = oracle(FX, e["i"])
        for k in P["run"]:
            for h in P["run"][k]:
                P["run"][k][h] = np.zeros_like(P["run"][k][h])
        for kk in P["sib"]:
            P["sib"][kk] = np.zeros(2)
        got = dec(A.decode(P, beam=256))
        same(got, e["beam256"])
        hits += got["canon"] == FX["oracle"][e["i"]]["gold"]
    assert hits < 0.3 * len(FX["flat"])


def test_search_programs_and_answer_targets(FX):
    for e in FX["search"][:90]:
        r = FX["rows"][e["i"]]
        s, ps, n = A.search_programs(r, Fraction(r["gold_frac"]), 5, **e["kw"])
        assert dict(steps=s, canon=sorted(A.canon(p) for p in ps), n_checked=n) == e["res"]
    for e in FX["answer_targets"]:
        at = A.answer_targets(FX["rows"][e["i"]], 5)
        got = None if at is None else [dict(w=w, steps=int(tg["steps"]), root=int(tg["root"]), decodable=bool(tg["decodable"]),
                                             used=[int(x) for x in tg["per_run"]["used"]]) for tg, w in at]
        assert got == e["res"]
        if got:
            assert abs(sum(x["w"] for x in got) - 1.0) < 1e-9


def test_host_program_line(FX):
    q = dict(numerals_written=["37", "53", "71"], prov=dict(n_runs=3, run_values=["37", "53", "71"]))
    n37, n53, n71 = ("n", 0, Fraction(37)), ("n", 1, Fraction(53)), ("n", 2, Fraction(71))
    gt = ("b", "mul", n37, n53)
    _, hp, _ = A.search_programs(q, Fraction(37 + 53), 5, max_consts=0)
    items = [(("b", "add", n53, n37), hp, gt), (gt, hp, gt), (("b", "sub", n71, n37), hp, gt), (gt, [], gt)]
    assert A.host_program_line(items) == FX["host_line"]


def test_fitted_end_to_end(FX):
    """reader A fitted on planted states (folds 1-4 of the fixture), decoded on its fold 5: same heads, same programs"""
    F = FX["fitted"]
    st = A.load_dump(NPZ_PATH)
    rows = F["rows"]
    J = list(range(len(rows)))
    fold = {int(k): v for k, v in F["fold"].items()}
    asm = A.assemble(rows, st, J, F["layer"], 5)
    heads = A.fit_reader(asm, F["train"], fold)
    assert A.head_accuracy_by_position(asm, heads, F["test"]) == F["head_accuracy"]
    for e in F["decode"]:
        got = dec(A.decode(A.predict_row(heads, asm, e["i"])))
        assert got["canon"] == e["canon"]
        if e["score"] is not None:
            assert abs(got["score"] - e["score"]) <= 1e-6 * max(1.0, abs(e["score"]))
    exact = sum(e["canon"] == e["gold"] for e in F["decode"])
    assert exact >= 0.7 * len(F["decode"])
