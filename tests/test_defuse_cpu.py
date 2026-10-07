"""CPU tests for the defuse/ package. numpy + the standard library; no GPU, no model, no network, no real rows.

Every fixture is SYNTHETIC and generated here: small made-up word problems with a gold equation in the source
formats the parser knows (Ape210K-style infix, MathQA programs, ASDiv chained statements, MAWPS linear equations),
and planted "hidden states" in which the def-use structure is linearly readable plus noise. Nothing here is, or is
derived from, an evaluation row.

    python -m pytest -q tests/test_defuse_cpu.py
"""
import json
import math
import os
import sys
from fractions import Fraction

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from defuse import data as D          # noqa: E402
from defuse import evaluate as EV     # noqa: E402
from defuse import fit_b as FB        # noqa: E402
from defuse import gate as GT         # noqa: E402
from defuse import guard as G         # noqa: E402
from defuse import inventory as INV   # noqa: E402
from defuse import reader_a as A      # noqa: E402
from defuse import reader_b as B      # noqa: E402
from defuse import run as RUN         # noqa: E402
from defuse import dump as DUMP       # noqa: E402

R = 5


# ------------------------------------------------------------------ synthetic rows
def mk_row(rid, nums, kind, equation, gold, fold=1, text=None):
    nums = [str(x) for x in nums]
    return dict(row_id=rid, fold=fold, lang="en", status="scored",
                text=text or ("A story with " + ", ".join(nums) + " things. The answer is"),
                question=text or ("A story with " + ", ".join(nums) + " things."),
                numerals_written=nums,
                prov=dict(n_runs=len(nums), run_values=nums, gold_run_idx=[]),
                gold_frac=str(Fraction(gold)), annotation=dict(kind=kind, equation=equation))


def syn_program(rng, n_num):
    """a random 1-3 step program over the first numerals, with a distractor left over when n_num allows"""
    vals = [int(rng.integers(2, 60)) for _ in range(n_num)]
    k = int(rng.integers(2, min(3, n_num) + 1)) if n_num >= 2 else 1
    used = list(range(k))
    expr = str(vals[used[0]])
    for j in used[1:]:
        op = ["+", "-", "*"][int(rng.integers(0, 3))]
        expr = "(%s%s%d)" % (expr, op, vals[j])
    if rng.random() < 0.3:
        expr = "(%s*2)" % expr                      # a hidden constant from the 20-value vocabulary
    gold = eval(expr)                               # noqa: S307  (made-up integer arithmetic only)
    return vals, "x=" + expr, gold


def syn_rows(n, seed=0, folds=(1, 2, 3, 4)):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        vals, eq, gold = syn_program(rng, int(rng.integers(2, 5)))
        rows.append(mk_row("syn:%04d" % i, vals, "ape210k", eq, gold, fold=folds[i % len(folds)]))
    return rows


def syn_states(rows, d=24, seed=1, noise=0.3):
    """planted states: H_run_last carries USED / PARENT / SIDE / DEPTH codes of each numeral, H_space the step count
    and root operator, plus Gaussian noise; A_space is small random attention mass"""
    rng = np.random.default_rng(seed)
    E = {k: rng.normal(size=(8, d)) for k in ("used", "parent", "side", "depth", "steps", "root", "const")}
    n = len(rows)
    HL = rng.normal(size=(n, R, 3, d)) * noise
    HS = rng.normal(size=(n, 3, d)) * noise
    AS = rng.random(size=(n, R, 2, 2)).astype(np.float32)
    meta = []
    for i, r in enumerate(rows):
        t, s = A.gold_tree(r)
        assert s == "exec_exact", (r, s)
        tg = A.targets_from_tree(t, r, R)
        T = tg["per_run"]
        for k in range(R):
            if T["used"][k] >= 0:
                HL[i, k] += E["used"][int(T["used"][k])]
            if T["parent"][k] >= 0:
                HL[i, k] += E["parent"][int(T["parent"][k])]
            if T["side"][k] >= 0:
                HL[i, k] += E["side"][int(T["side"][k])]
            if T["depth"][k] >= 0:
                HL[i, k] += 0.5 * E["depth"][int(T["depth"][k])]
        HS[i] += E["steps"][tg["steps"]] + E["root"][tg["root"]]
        for c in np.nonzero(tg["consts"])[0]:
            HS[i] += E["const"][c % 8]
        meta.append(dict(row_id=r["row_id"], n_runs=len(r["prov"]["run_values"]), run_values=r["prov"]["run_values"]))
    return dict(meta=meta, layers=[20, 24, 28], space_layers=[20, 24, 28], H_run_last=HL.astype(np.float32),
                H_space=HS.astype(np.float32), A_space=AS, run_mask=np.ones((n, R), bool))


# ------------------------------------------------------------------ programs and the gold-equation parser
def test_gold_tree_formats_execute_exactly():
    cases = [
        (mk_row("t:1", [12, 5, 3], "ape210k", "x=(12-5)*3", 21), 21, 2),
        (mk_row("t:2", [12], "ape210k", "x=12/2", 6), 6, 1),                              # 2 = a vocabulary constant
        (mk_row("t:3", [4, 5], "mathqa", "multiply(n0,n1)|add(#0,const_100)", 120), 120, 2),
        (mk_row("t:4", [3, 4, 2], "asdiv", "3+4=7; 7*2=14", 14), 14, 2),                  # chained statements
        (mk_row("t:5", [3, 4], "mawps", "X=3+4", 7), 7, 1),
        (mk_row("t:6", [40, 25], "ape210k", "x=40*25%", 10), 10, 1),                      # percent as a unary op
    ]
    for r, v, steps in cases:
        t, s = A.gold_tree(r)
        assert s == "exec_exact", (r["annotation"], s)
        assert A.execute(t) == Fraction(v)
        assert A.n_steps(t) == steps
    t, s = A.gold_tree(mk_row("t:7", [3], "ape210k", "", 3))
    assert t is None and s == "no_equation"
    t, s = A.gold_tree(mk_row("t:8", [3, 4], "ape210k", "x=3+4", 8))
    assert s == "exec_mismatch"


def test_canon_is_commutative_and_targets_are_per_numeral():
    a = ("b", "add", ("n", 0, Fraction(2)), ("n", 1, Fraction(3)))
    b = ("b", "add", ("n", 1, Fraction(3)), ("n", 0, Fraction(2)))
    assert A.canon(a) == A.canon(b)
    r = mk_row("t:9", [12, 5, 3, 99], "ape210k", "x=(12-5)*3", 21)             # 99 is a distractor
    t, _ = A.gold_tree(r)
    tg = A.targets_from_tree(t, r, R)
    T = tg["per_run"]
    assert list(T["used"][:4]) == [1, 1, 1, 0]
    assert [A.PARENT_CLASSES[i] for i in T["parent"][:3]] == ["sub", "sub", "mul"]
    assert list(T["side"][:3]) == [0, 1, -1]                                  # minuend, subtrahend, no -/÷ ancestor
    assert list(T["depth"][:3]) == [2, 2, 1]
    assert tg["n_steps"] == 2 and A.ROOT_CLASSES[tg["root"]] == "mul" and tg["decodable"]
    assert INV.tkey(r) == INV.tkey(mk_row("t:10", [1, 2, 3, 4], "ape210k", "x=1", 1))   # numbers masked


def test_du_ag_never_fires_on_host_silent_rows():
    p = ("b", "sub", ("n", 0, Fraction(12)), ("n", 1, Fraction(5)))
    progs = {20: p, 24: p, 28: p}
    vals = [Fraction(12), Fraction(5)]
    assert A.du_ag(progs, "12", False, vals)["fire"]                      # host echoes a prompt number
    assert A.du_ag(progs, "40", False, vals)["fire"]                      # host wrote some other number
    assert not A.du_ag(progs, "7", False, vals)["fire"]                   # host agrees: nothing to do
    assert not A.du_ag(progs, None, True, vals)["fire"]                   # host silent: never fire
    q = ("b", "add", ("n", 0, Fraction(12)), ("n", 1, Fraction(5)))
    assert not A.du_ag({20: p, 24: q, 28: p}, "40", False, vals)["fire"]  # layers disagree


def test_reader_a_decoder_recovers_an_oracle_program():
    """the ported decoder (tests/test_reader_a_decode.py checks it against the pinned file in detail)"""
    r = dict(row_id="syn:x", numerals_written=["40", "120", "32"], prov=dict(n_runs=3, run_values=["40", "120", "32"]),
             annotation=dict(kind="mathqa linear_formula", equation="subtract(n1,n0)|divide(#0,n2)|"), gold_frac="5/2")
    t, st = A.gold_tree(r)
    tg = A.targets_from_tree(t, r, 5)
    bt, score, info = A.decode(A.oracle_P(tg, r, 5))
    assert st == "exec_exact" and A.canon(bt) == A.canon(t) == "((120 - 40) / 32)" and A.execute(bt) == Fraction(5, 2)
    assert info["n_leaves"] == 3 and score > -1.0


# ------------------------------------------------------------------ reader A heads
def test_reader_a_heads_read_planted_structure():
    rows = syn_rows(160, seed=3, folds=(1, 2, 3, 4, 5))
    st = syn_states(rows)
    fit_idx = [i for i, r in enumerate(rows) if r["fold"] != 5]
    test_idx = [i for i, r in enumerate(rows) if r["fold"] == 5]
    asm = A.assemble(rows, st, list(range(len(rows))), 24, R)
    heads = A.fit_reader(asm, fit_idx, {i: rows[i]["fold"] for i in fit_idx}, lams=[1.0, 10.0])
    assert {"used", "parent", "side", "steps", "root"} <= set(heads)
    ok = n = 0
    for i in test_idx:
        P = A.predict_row(heads, asm, i)
        T = asm["tg"][i][2]["per_run"]
        for k in P["leafable"]:
            n += 1
            ok += int(np.argmax(P["run"][k]["used"])) == int(T["used"][k])
    assert n > 0 and ok / n > 0.9, (ok, n)


# ------------------------------------------------------------------ reader B
def test_reader_b_gradients_match_finite_differences():
    assert B._gradcheck(np.random.default_rng(0)) < 1e-4


def test_reader_b_tokens_round_trip_and_state_round_trip():
    r = mk_row("t:11", [12, 5, 3], "ape210k", "x=(12-5)*3", 21)
    t, _ = A.gold_tree(r)
    toks = B.prefix_tokens(t, r, R)
    rv = {k: (k, A.numeral_values(r)[k]) for k in range(3)}
    back = B.tokens_to_tree([(k, (min(v) if k == "ptr" else v)) for k, v in toks], rv)
    assert A.canon(back) == A.canon(t)
    m = B.ReaderB(8, dg=6, de=3, seed=0)
    m2 = B.ReaderB.from_state(m.state())
    assert all(np.allclose(m.p[k], m2.p[k]) for k in m.p)


def test_fit_b_refuses_held_out_folds_and_flat_grids():
    rows = syn_rows(40, seed=5)
    st = syn_states(rows, d=12)
    asm = A.assemble(rows, st, list(range(len(rows))), 24, R)
    with pytest.raises(SystemExit):
        FB.make_rows_by_fold(asm, [1, 2, 3, 5] * 10)
    rbf = FB.make_rows_by_fold(asm, [r["fold"] for r in rows])
    assert len(rbf((1, 2, 3, 4))) == 40
    # a one-epoch untrained grid reads nothing on fold 4: the project's driver refuses a flat grid loudly
    grid = dict(FB.F2_GRID, l2=(1e-3,), lr=(1e-3, 3e-3), epochs=(1,), val_cap=10, dg=6, de=3)
    try:
        FB.run_fitb(rbf, str(_tmp("fitb")), 24, grid=grid)
    except SystemExit as e:
        assert "flat grid" in str(e)


def test_reader_b_end_to_end_decode_record():
    rows = syn_rows(48, seed=7)
    st = syn_states(rows, d=12)
    asms = {L: A.assemble(rows, st, list(range(len(rows))), L, R) for L in A.LAYERS}
    rbf = FB.make_rows_by_fold(asms[24], [r["fold"] for r in rows])
    data = rbf((1, 2, 3, 4))
    m = B.ReaderB(12, dg=8, de=4, seed=0, l2=1e-3)
    hist = m.fit([x[:4] for x in data], epochs=6, stats=FB.b_stats(data), lr=3e-3, clip=1.0)
    assert hist[-1] < hist[0]                                               # it learns
    models = {L: m for L in A.LAYERS}
    rec = FB.decode_record(models, asms, 0, rows[0], dict(host1="1", host1_none=False, host1_right=False), fold=1)
    for k in ("canon", "lp", "nleaves", "steps24", "value24", "fire", "right", "gold_steps", "host1_right"):
        assert k in rec
    if rec["fire"]:
        assert rec["right"] == (Fraction(rec["value24"]) == Fraction(rows[0]["gold_frac"]))


# ------------------------------------------------------------------ the gate and the R1 ledger
def syn_records(n, seed, folds):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        hr = bool(rng.random() < 0.5)
        fire = bool(rng.random() < 0.5)
        good = bool(rng.random() < 0.6)                                     # the reader's program is right
        right = good if fire else hr
        lp = -0.2 if good else -2.5
        lp += rng.normal() * 0.6
        st = int(rng.integers(1, 4))
        out.append(dict(row_id="r:%d:%d" % (seed, i), fold=folds[i % len(folds)], fire=fire, right=right,
                        host1_right=hr, n_numerals=int(rng.integers(2, 5)), steps24=st,
                        lp={"20": lp, "24": lp, "28": lp}, nleaves={"20": st + 1, "24": st + 1, "28": st + 1}))
    return out


def test_ledger_words_follow_r1():
    rows = [dict(row_id=str(i), host1_right=i < 200, fire=True, right=not (i < 3)) for i in range(400)]
    d = GT.ledger(rows)
    assert (d["HR"], d["broken"], d["bar"], d["r1"]) == (200, 3, 2, "NEITHER")
    rows = [dict(x, right=not (int(x["row_id"]) < 2)) for x in rows]
    assert GT.ledger(rows)["r1"] == "SUCCESS"
    rows = [dict(x, right=not (int(x["row_id"]) < 11)) for x in rows]
    assert GT.ledger(rows)["r1"] == "FAILURE"


def test_gate_is_fitted_on_folds_1_to_4_and_meets_its_budget_there():
    oof = syn_records(1200, 11, (1, 2, 3, 4))
    g = GT.fit_gate(oof, 0.01, side="b")
    assert g["oof_broken"] <= g["budget"] == math.floor(0.01 * g["oof_HR"])
    with pytest.raises(SystemExit):
        GT.fit_gate(syn_records(50, 12, (1, 5)), 0.01, side="b")
    held = syn_records(600, 13, (5,))
    ids = GT.apply_gate(held, g)
    gated = GT.ledger(held, lambda x: x["row_id"] in ids)
    ungated = GT.ledger(held)
    assert gated["broken"] < ungated["broken"] and gated["fires"] <= ungated["fires"]
    txt = EV.ledger_table(held, g)
    assert "broken / host-right" in txt and "/" in txt


def test_state_probe_ridge_ranks_planted_signal():
    rng = np.random.default_rng(2)
    n, d = 400, 10
    y = rng.random(n) < 0.4
    X = rng.normal(size=(n, d)); X[:, 0] += 1.5 * y
    fold = np.array([1 + (i % 5) for i in range(n)])
    info, sc = GT.fit_arm(X, y, fold)
    assert info["oof_auroc_folds1_4"] > 0.8 and np.isfinite(sc).all()


# ------------------------------------------------------------------ fold discipline
def _tmp(name):
    p = os.path.join(os.environ.get("PYTEST_TMP", "/tmp"), "defuse_selftest_%d" % os.getpid(), name)
    os.makedirs(p, exist_ok=True)
    return p


def test_loader_refuses_held_out_folds_and_blocklisted_ids():
    d = _tmp("rows")
    p = os.path.join(d, "rows.jsonl")
    rows = syn_rows(6, seed=1, folds=(1, 2, 3, 4, 5, 6))
    with open(p, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    with pytest.raises(G.Refused):
        D.load_rows(p, fit=True)
    assert len(D.load_rows(p, fit=False)) == 6
    with open(p, "w") as f:
        for r in rows[:4]:
            f.write(json.dumps(r) + "\n")
    assert len(D.load_rows(p, fit=True)) == 4
    with open(os.path.join(d, "HELDOUT_IDS.txt"), "w") as f:
        f.write(rows[2]["row_id"] + "\n")
    with pytest.raises(G.Refused):
        D.load_rows(p, fit=True)
    os.remove(os.path.join(d, "HELDOUT_IDS.txt"))
    G.set_blocklist(None)
    with pytest.raises(G.Refused):
        G.check_path("data/mgsm_rows.jsonl")
    with pytest.raises(G.Refused):
        G.check_row_id("x", dict(fold=5))
    with G.scoring_pass():
        assert G.check_row_id("x", dict(fold=5))


def test_dump_rows_join_checks_run_values():
    rows = syn_rows(8, seed=2)
    st = syn_states(rows, d=8)
    got = D.rows_in_dump_order(st, list(reversed(rows)))
    assert [r["row_id"] for r in got] == [r["row_id"] for r in rows]
    st["meta"][0] = dict(st["meta"][0], run_values=["999"] * len(st["meta"][0]["run_values"]))
    with pytest.raises(SystemExit):
        D.rows_in_dump_order(st, rows)
    st2 = D.relabel_layers(syn_states(rows, d=8) | dict(layers=[16, 19, 22], space_layers=[16, 19, 22]), {16: 20, 19: 24, 22: 28})
    assert st2["layers"] == [20, 24, 28] and st2["real_layers"] == [16, 19, 22]


# ------------------------------------------------------------------ the dumper's locators (no torch needed)
class FakeTok:
    def __init__(self, pieces):
        self.pieces = pieces

    def decode(self, ids):
        return "".join(self.pieces[i] for i in ids)


def test_locators_single_digit_and_grouped():
    qwen = FakeTok(["Tom", " has", " ", "1", "2", " apples", " and", " ", "5", "²"])
    assert DUMP.digit_runs_single(qwen, list(range(10))) == [[3, 4], [8]]           # a superscript is not a digit
    llama = FakeTok(["Tom", " has", " ", "123", "4", " apples", " and", " ", "56", "."])
    assert DUMP.digit_runs_single(llama, list(range(10))) == [[4]]                   # why Llama needs --locator grouped
    assert DUMP.digit_runs_grouped(llama, list(range(10))) == [[3, 4], [8]]


def test_host_fields_from_greedy_text_and_steps_table():
    r = mk_row("t:12", [3, 4], "ape210k", "x=3+4", 7)
    assert RUN.host_fields(dict(greedy_raw=" 7 apples"), r) == dict(host1="7", host1_none=False, host1_right=True)
    assert RUN.host_fields(dict(greedy_raw=" seven"), r)["host1_none"]
    assert RUN.host_fields(dict(greedy_raw=" 1,234.5"), r)["host1"] == str(Fraction("1234.5"))
    recs = [dict(row_id="a", gold_steps=1, value24="7", gold_value="7", host1_right=False, fire=True, right=True),
            dict(row_id="b", gold_steps=2, value24="5", gold_value="7", host1_right=True, fire=False, right=True),
            dict(row_id="c", gold_steps=None, value24=None, gold_value="1", host1_right=False, fire=False, right=False)]
    txt = EV.steps_table(recs)
    assert "| 1 | 1 | 1/1 | 0/1 | 1/1 |" in txt and "| all | 3 | 1/3 | 1/3 | 2/3 |" in txt


def test_bank_row_adapter_fills_def_use_fields():
    from defuse import bank_rows as BR
    r = dict(row_id="b:1", text="A shop has 88 buns, bakes 42 more and sells 41. How many are left? The answer is",
             answer_cue="The answer is", ans=89, annotation=dict(kind="v6ms infix", equation="x=(88+42)-41"),
             prov=dict(n_runs=3, gold_run_idx=[0, 1, 2]), v6=dict(tmpl_fold=3))
    x = BR.to_defuse_row(r, ("v6", "tmpl_fold"), heldout_value=5)
    assert x["numerals_written"] == ["88", "42", "41"] and x["gold_frac"] == "89" and x["fold"] == 3
    t, s = A.gold_tree(x)
    assert s == "exec_exact" and A.n_steps(t) == 2 and r["annotation"]["kind"] == "v6ms infix"   # input untouched
    assert BR.to_defuse_row(r, ("v6", "tmpl_fold"), heldout_value=3)["fold"] == 5
    with pytest.raises(SystemExit):
        BR.to_defuse_row(r, ("v6", "tmpl_fold"), heldout_value=None)
