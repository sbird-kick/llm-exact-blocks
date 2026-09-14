#!/usr/bin/env python3
"""CPU-only tests. No GPU, no model download, no network.

    python -m pytest -q tests/test_cpu.py      (or)      python tests/test_cpu.py

The model test builds a RANDOMLY INITIALISED four-layer Qwen3 with d=64 from a config
object, so it exercises the real hook plumbing of the real architecture in about a second.
The tokenizer tests run against the cached Qwen3 tokenizer when one is present -- which is
the only way to check the claim the whole design rests on, that Qwen3 gives every digit its
own token -- and fall back to a character-level stub when it is not.
"""
from __future__ import annotations

import argparse
import os
import random
import sys

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exact_block import numerals                                       # noqa: E402
from exact_block.block import CalcBlock, build_batch, spans_from_logits  # noqa: E402
from exact_block.calc import (OPS, Calc, columns, decode_places,        # noqa: E402
                              exact_answer, place_routing, resolve_carry)
from exact_block.data import (TEMPLATES, generate, make_problem,        # noqa: E402
                              roles_of, split_of)


class StubTok:
    """A character-level stand-in: one token per character, id = ord(c)."""
    pad_token_id = 0

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [ord(c) for c in text]}

    def decode(self, ids):
        return "".join(chr(i) for i in ids)


def qwen_tokenizer():
    """The cached Qwen3 tokenizer, or None. Never downloads."""
    try:
        from transformers import AutoTokenizer
        return AutoTokenizer.from_pretrained("Qwen/Qwen3-1.7B", local_files_only=True)
    except Exception:
        return None


# ----------------------------------------------------------------- the calculator
def test_calc_matches_python_ints():
    rng = random.Random(0)
    dmax = 16
    calc = Calc(dmax=dmax, ops=OPS)
    cases = []
    for _ in range(400):
        da, db = rng.randint(1, dmax), rng.randint(1, dmax)
        a = rng.randrange(10 ** (da - 1), 10 ** da)
        b = rng.randrange(10 ** (db - 1), 10 ** db)
        op = rng.choice(OPS)
        if op == "sub" and a < b:
            a, b = b, a
        cases.append((a, b, op))
    # the carry and borrow edges, by hand rather than by luck
    cases += [(999999999999999, 1, "add"), (1000000000000000, 1, "sub"),
              (10, 3, "sub"), (5, 5, "sub"), (9999999999999999, 9999999999999999, "mul"),
              (1, 1, "mul"), (10 ** 15, 10 ** 15, "add")]

    A = torch.zeros(len(cases), dmax, 10)
    B = torch.zeros(len(cases), dmax, 10)
    idx = torch.zeros(len(cases), dtype=torch.long)
    for i, (a, b, op) in enumerate(cases):
        for k, v in enumerate(numerals.digits_lsd(a, dmax)):
            A[i, k, v] = 1.0
        for k, v in enumerate(numerals.digits_lsd(b, dmax)):
            B[i, k, v] = 1.0
        idx[i] = OPS.index(op)
    R, refused = calc(A, B, idx)
    got = decode_places(R)
    assert R.shape == (len(cases), 2 * dmax, 10)
    for i, (a, b, op) in enumerate(cases):
        assert float(refused[i]) == 0.0, (a, b, op)
        assert got[i] == exact_answer(a, b, op), (a, b, op, got[i])
    print(f"  calc exact on {len(cases)} random + edge cases")


def test_calc_refuses_negative_and_overflow():
    dmax = 4
    calc = Calc(dmax=dmax, ops=OPS)
    A = torch.zeros(2, dmax, 10)
    B = torch.zeros(2, dmax, 10)
    for i, (a, b) in enumerate([(3, 10), (10, 3)]):     # 3 - 10 < 0 ; 10 - 3 >= 0
        for k, v in enumerate(numerals.digits_lsd(a, dmax)):
            A[i, k, v] = 1.0
        for k, v in enumerate(numerals.digits_lsd(b, dmax)):
            B[i, k, v] = 1.0
    _, refused = calc(A, B, torch.tensor([OPS.index("sub")] * 2))
    assert float(refused[0]) == 1.0 and float(refused[1]) == 0.0, refused
    # an over-wide result is the same signal with the opposite sign
    digits, carry = resolve_carry(torch.tensor([[9.0, 9.0], [1.0, 0.0]]))
    assert float(carry[0]) == 0.0 and float(carry[1]) == 0.0
    _, carry2 = resolve_carry(torch.tensor([[99.0, 99.0]]))
    assert float(carry2[0]) > 0
    print("  calc refuses a negative difference and reports an overflow carry")


def test_place_routing_is_schoolbook():
    M = place_routing(4)
    for i in range(4):
        for j in range(4):
            assert float(M[i, j, i + j]) == 1.0
            assert float(M[i, j].sum()) == 1.0
    a = torch.tensor([[3.0, 2.0, 0.0, 0.0]])            # 23
    b = torch.tensor([[4.0, 1.0, 0.0, 0.0]])            # 14
    d, c = resolve_carry(columns(a, b, "mul", M))
    assert decode_places(torch.nn.functional.one_hot(d.long(), 10).float()) == [23 * 14]
    assert float(c[0]) == 0.0
    print("  place routing k == i + j reproduces schoolbook multiplication")


# ---------------------------------------------------------------------- the locator
def test_locator_runs_and_lanes():
    tok = qwen_tokenizer() or StubTok()
    which = "Qwen3" if not isinstance(tok, StubTok) else "stub char tokenizer"
    text = "The vault held 90310 coins before 472 were withdrawn, leaving"
    ids = tok(text, add_special_tokens=False)["input_ids"]
    runs = numerals.digit_runs(tok, ids)
    assert len(runs) == 2, runs
    assert numerals.run_value(tok, ids, runs[0]) == 90310
    assert numerals.run_value(tok, ids, runs[1]) == 472
    if not isinstance(tok, StubTok):
        assert len(runs[0]) == 5 and len(runs[1]) == 3, (
            "Qwen3 must give every digit its own token; the whole block assumes it")
    lanes = numerals.lanes_lsd(runs[1], 16)
    assert lanes[:3] == list(reversed(runs[1])) and lanes[3:] == [-1] * 13, lanes
    assert numerals.digits_lsd(472, 5) == [2, 7, 4, 0, 0]
    print(f"  locator: two runs, LSD lanes, exact values ({which})")


def test_spans_from_logits():
    #        pos: 0    1    2    3    4    5   (p0 = 6, so nothing after it is read)
    tags = [0, 1, 1, 0, 2, 2, 1]
    logits = torch.full((1, len(tags), 3), -5.0)
    for j, t in enumerate(tags):
        logits[0, j, t] = 5.0
    a, b, fail = spans_from_logits(logits, torch.tensor([6]), 16)
    assert float(fail[0]) == 0.0
    assert a[0, :2].tolist() == [2, 1] and a[0, 2] == -1      # LSD first
    assert b[0, :2].tolist() == [5, 4] and b[0, 2] == -1
    logits[0, 4, 2] = -5.0
    logits[0, 5, 2] = -5.0                                    # no B run at all -> fail
    _, _, fail2 = spans_from_logits(logits, torch.tensor([6]), 16)
    assert float(fail2[0]) == 1.0
    print("  tagger decode: longest run per class, LSD lanes, failure is a refusal")


# ------------------------------------------------------------------------ the corpus
def test_corpus_shapes():
    for op, tmpls in TEMPLATES.items():
        for t in tmpls:
            prose = t
            for slot in ("{a}", "{b}", "{d1}", "{d2}"):
                prose = prose.replace(slot, "")
            assert not any(c.isdigit() for c in prose), (op, t)   # a literal digit = a run
            roles = roles_of(t)
            if op == "off":
                assert set(roles) == {"d"}, (t, roles)
            else:
                assert roles.count("a") == 1 and roles.count("b") == 1, (t, roles)
    rows = generate("train", ("4x4", "8x4"), OPS, 20, 30, seed=0)
    assert len(rows) == 20 * 2 * 3 + 30
    for p in rows:
        if p.op == "off":
            continue
        assert exact_answer(p.a, p.b, p.op) == p.ans
        assert p.completion == f" {p.ans}\n"
        assert split_of(p.op, p.a, p.b) == "train"
        assert str(p.a) in p.prompt and str(p.b) in p.prompt
    # a few reversed templates really do render b before a
    assert any(p.roles.index("b") < p.roles.index("a") for p in rows if p.op == "sub")
    # splits cannot share an operand pair
    tr = {(p.op, p.a, p.b) for p in rows if p.op != "off"}
    te = {(p.op, p.a, p.b)
          for p in generate("test", ("4x4", "8x4"), OPS, 20, 0, seed=0) if p.op != "off"}
    assert not (tr & te)
    assert make_problem("sub", "4x4", random.Random(1), "val").a >= \
        make_problem("sub", "4x4", random.Random(1), "val").b
    print(f"  corpus: {len(rows)} rows, no literal digits, splits problem-disjoint")


# ------------------------------------------------------------------------- the block
def tiny_model():
    from transformers import Qwen3Config, Qwen3ForCausalLM
    cfg = Qwen3Config(vocab_size=256, hidden_size=64, intermediate_size=128,
                      num_hidden_layers=4, num_attention_heads=4,
                      num_key_value_heads=2, head_dim=16, max_position_embeddings=512)
    torch.manual_seed(0)
    m = Qwen3ForCausalLM(cfg).eval().requires_grad_(False)
    return m


def problems_for_test():
    from exact_block.data import Problem
    return [Problem(op="add", a=41, b=27, ans=68,
                    prompt="add 41 to 27, giving", completion=" 68\n",
                    roles=["a", "b"], cell="2x2", tmpl=0),
            Problem(op="mul", a=8, b=305, ans=2440,
                    prompt="the 305 spares aside, 8 crates of 305 is",
                    completion=" 2440\n", roles=["d", "a", "b"], cell="1x3", tmpl=0)]


def test_build_batch_positions():
    tok = StubTok()
    ids, attn, ctx = build_batch(tok, problems_for_test(), dmax=4)
    assert ids.shape[0] == 2 and ctx["a_pos"].shape == (2, 4)
    assert ctx["w_pos"].shape == (2, 8)
    row = problems_for_test()[0]
    pid = tok(row.prompt)["input_ids"]
    # "41" sits at characters 4,5 -> LSD-first lanes [5, 4, -1, -1]
    assert ctx["a_pos"][0].tolist() == [5, 4, -1, -1], ctx["a_pos"][0]
    assert ctx["b_pos"][0].tolist() == [11, 10, -1, -1], ctx["b_pos"][0]
    assert ctx["a_dig"][0].tolist() == [1, 4, -100, -100]
    assert ctx["ctl_pos"][0] == len(pid) - 1 and ctx["p0"][0] == len(pid)
    # the block writes at the position BEFORE each answer digit
    for k in range(2):
        pos = int(ctx["w_pos"][0, k])
        tid = int(ids[0, pos + 1])
        assert tid == int(ctx["w_tok"][0, k])
        assert chr(tid) == "68"[1 - k]
    # the distractor in row 2 is tagged `none`, the operands 1 and 2
    assert ctx["span_labels"][1].tolist().count(1) == 1
    assert ctx["span_labels"][1].tolist().count(2) == 3
    print("  build_batch: LSD operand lanes, answer lanes one position early")


def test_block_is_bitwise_inert_at_gate_zero():
    m = tiny_model()
    tok = StubTok()
    ids, attn, ctx = build_batch(tok, problems_for_test(), dmax=4)
    with torch.no_grad():
        base = m.model(input_ids=ids, attention_mask=attn,
                       use_cache=False).last_hidden_state.clone()
    blk = CalcBlock(m.config.hidden_size, dmax=4, ops=OPS).float()
    blk.attach(m, 0, 1, 2)
    blk.ctx = ctx
    with torch.no_grad():
        withblk = m.model(input_ids=ids, attention_mask=attn,
                          use_cache=False).last_hidden_state
    assert torch.equal(base, withblk), "gate = 0 must be BITWISE the original model"
    assert blk.last["R"].shape == (2, 8, 10)
    assert blk.last["span_logits"].shape[-1] == 3

    # THE UNTRAINED ROUTER ABSTAINS, and that is the +2.0 `off` prior doing its job: with
    # it in place `mass` is exactly 0 and opening the gate still changes nothing. So the
    # prior has to be removed before the write site can be observed at all -- which is
    # itself the test that abstention is exact rather than merely small.
    with torch.no_grad():
        blk.gate.fill_(1.0)
        still_off = m.model(input_ids=ids, attention_mask=attn,
                            use_cache=False).last_hidden_state
        assert torch.equal(base, still_off), "the off prior must make the write exact zero"
        assert float(blk.last["mass"].max()) == 0.0
        blk.control.weight.zero_()                 # route every row to `add`, on purpose
        blk.control.bias.copy_(torch.tensor([10.0, 0.0, 0.0, -20.0]))
        opened = m.model(input_ids=ids, attention_mask=attn,
                         use_cache=False).last_hidden_state
        # (the probe is random here, so R holds the arithmetic of whatever digits it
        #  hallucinated -- exactness of the calculator itself is tested above, on
        #  one-hot inputs, where it is a claim about arithmetic and not about a probe)
        assert float(blk.last["mass"].min()) == 1.0
    first = int(ctx["w_pos"][ctx["w_pos"] >= 0].min())
    assert torch.equal(base[:, :first], opened[:, :first])
    assert not torch.equal(base, opened)
    blk.remove()
    with torch.no_grad():
        after = m.model(input_ids=ids, attention_mask=attn,
                        use_cache=False).last_hidden_state
    assert torch.equal(base, after), "remove() must put the host back exactly"
    print("  block: inert at gate 0, causal write site, hooks detach cleanly")


def test_greedy_decode_terminates():
    """Shape/termination only: the tiny model is RANDOM, so its digits mean nothing --
    this just checks the free-running decode loop in eval.py actually stops within its
    digit budget and hands back the shape run_greedy_eval promises, on both host and
    block passes and on a mix of arithmetic and off rows."""
    from exact_block.data import Problem
    from eval import run_greedy_eval

    m = tiny_model()
    tok = StubTok()
    blk = CalcBlock(m.config.hidden_size, dmax=4, ops=OPS).float()
    blk.attach(m, 0, 1, 2)
    args = argparse.Namespace(dmax=4)
    rows = problems_for_test() + [
        Problem(op="off", a=0, b=0, ans=0, prompt="shelf 12 held volume 34, filed under",
               completion="", roles=["d", "d"], cell="", tmpl=0)]
    ev = run_greedy_eval(m, blk, tok, rows, args, device="cpu", bs=2)
    assert ev["n_arith"] == 2 and ev["n_off"] == 1
    assert 0.0 <= ev["host"] <= 1.0 and 0.0 <= ev["block"] <= 1.0
    assert 0.0 <= ev["fire_on_off"] <= 1.0
    assert isinstance(ev["examples"], list) and len(ev["examples"]) <= 5
    print("  greedy decode: terminates within the digit budget on host and block passes")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"running {len(tests)} CPU tests (torch {torch.__version__})")
    for t in tests:
        print(f"- {t.__name__}")
        t()
    print("all CPU tests pass")


if __name__ == "__main__":
    main()
