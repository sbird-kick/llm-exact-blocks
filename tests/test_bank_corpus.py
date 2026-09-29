#!/usr/bin/env python3
"""CPU tests for data_gen/bank_to_corpus.py. Standard library only, except the last test,
which needs torch and is skipped (and says so) when torch is not installed.

    python tests/test_bank_corpus.py          (or)      python -m pytest -q tests/test_bank_corpus.py

The rows below are written for this test in the bank's row schema; they are not bank rows.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data_gen"))

import bank_to_corpus as B  # noqa: E402

PROBLEM_FIELDS = ["op", "a", "b", "ans", "prompt", "completion", "roles", "cell", "tmpl"]


def row(text, a, b, ans, lang="en", op="subtraction", story=1, fill="int"):
    return dict(row_id=f"t:{lang}:{story}:{a}:{b}", lang=lang, story_id=story, op=op,
                fill=fill, text=text, a=a, b=b, ans=ans)


ROWS = [
    # English, minuend written second, a distractor first
    row("Locker 58 is by the door. At noon the tank held 31 litres; by evening it held 47 litres. "
        "What was the change in the tank from noon to evening? The answer is", 47, 31, 16),
    # the negative half of the same minimal pair: left out
    row("Locker 58 is by the door. At noon the tank held 47 litres; by evening it held 31 litres. "
        "What was the change in the tank from noon to evening? The answer is", 31, 47, -16),
    # Japanese: no spaces between sentences, ASCII digits inside CJK text
    row("朝の気温は12度で、夕方の気温は29度でした。朝から夕方までの変化はいくらですか。答えは",
        29, 12, 17, lang="ja", story=2),
    # Arabic, right to left, a distractor after the pair
    row("كان في المخزن 350 صندوقا ثم خرج منه 120 صندوقا. رقم المخزن 7. كم صندوقا بقي؟ الجواب هو",
        350, 120, 230, lang="ar", story=3),
    # Thai, addition, three numerals
    row("ร้านขายส้ม 14 กิโลกรัม มะม่วง 9 กิโลกรัม และกล้วย 23 กิโลกรัม ขายส้มและกล้วยรวมกี่กิโลกรัม คำตอบคือ",
        14, 23, 37, lang="th", op="addition", story=4),
    # product
    row("Each of the 6 crates on the shelf holds 25 jars, and 4 other crates stayed in the van. "
        "How many jars are on the shelf? The answer is", 6, 25, 150, op="product", story=5),
]


def test_conversion_fields_and_roles():
    out = [B.convert(r) for r in ROWS]
    ok = [p for p, why in out if p is not None]
    whys = [why for p, why in out if p is None]
    assert whys == ["negative answer (no sign channel)"], whys
    assert len(ok) == 5
    for p in ok:
        assert list(p) == PROBLEM_FIELDS, list(p)
        assert p["completion"] == f" {p['ans']}\n"
        assert p["roles"].count("a") == 1 and p["roles"].count("b") == 1
    en, ja, ar, th, mul = ok
    assert en["op"] == "sub" and en["roles"] == ["d", "b", "a"] and en["cell"] == "2x2"
    assert ja["roles"] == ["b", "a"] and ja["prompt"].endswith("答えは")
    assert ar["roles"] == ["a", "b", "d"] and ar["cell"] == "3x3"
    assert th["op"] == "add" and th["roles"] == ["a", "d", "b"]
    assert mul["op"] == "mul" and mul["roles"] == ["a", "b", "d"] and mul["cell"] == "1x2"
    print("  convert: Problem fields in order, roles in written order, negatives left out")


def test_contract_refusals():
    cases = {
        "decimal row": row("It held 7.5 kg and then 2.5 kg. The answer is", 7.5, 2.5, 5.0, fill="dec"),
        "non-ASCII digit in the text": row("দোকানে 35 টি আম, ১২ টি বিক্রি। The answer is", 35, 12, 23),
        "an operand is not exactly one digit run": row("Box 35 held 35 pens and 12 pencils. The answer is",
                                                       35, 12, 23),
        "the answer is written in the prompt": row("Room 23: 35 pens, 12 lent. The answer is", 35, 12, 23),
    }
    for want, r in cases.items():
        p, why = B.convert(r)
        assert p is None and why == want, (want, why)
    print(f"  convert: {len(cases)} contract breaches refused with their reason")


def test_product_row_with_repeated_operand_is_refused():
    r = row("Each of the 6 crates holds 25 jars. How many jars do the 6 crates hold? The answer is",
            6, 25, 150, op="product")
    p, why = B.convert(r)
    assert p is None and why == "an operand is not exactly one digit run", why
    print("  convert: a repeated operand numeral is refused, never guessed")


def test_main_writes_three_splits_and_honours_test_langs():
    with tempfile.TemporaryDirectory() as d:
        bank = os.path.join(d, "bank.jsonl")
        with open(bank, "w", encoding="utf-8") as fh:
            for r in ROWS:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        out = B.main(["--bank", bank, "--out", os.path.join(d, "c"), "--test-langs", "ja"])
        assert sum(len(v) for v in out.values()) == 5
        assert [p["prompt"][:4] for p in out["test"] if "答え" in p["prompt"]]
        for split in ("train", "val", "test"):
            path = os.path.join(d, "c", f"{split}.jsonl")
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    assert list(json.loads(line)) == PROBLEM_FIELDS
        # --langs keeps only the listed languages (plus the held-out ones)
        out2 = B.main(["--bank", bank, "--out", os.path.join(d, "c2"), "--langs", "ar"])
        assert sum(len(v) for v in out2.values()) == 1
    print("  main: train/val/test written in the Problem schema, --langs and --test-langs work")


def test_split_is_story_level_across_languages():
    a = dict(lang="en", story_id=9, op="subtraction", a=40, b=17)
    b = dict(lang="ta", story_id=9, op="subtraction", a=71, b=3)
    assert B.split_of(a, "story", set()) == B.split_of(b, "story", set())
    assert B.split_of(b, "story", {"ta"}) == "test"
    print("  split: one story, one split, in every language")


def test_converted_rows_pass_build_batch():
    try:
        import torch  # noqa: F401
    except ImportError:
        print("  build_batch: SKIPPED (torch is not installed; run this file where it is)")
        return
    from exact_block.block import build_batch
    from exact_block.data import Problem
    from test_cpu import StubTok
    probs = [Problem(**p) for p, _ in (B.convert(r) for r in ROWS) if p is not None]
    ids, attn, ctx = build_batch(StubTok(), probs, dmax=8, ops=("add", "sub", "mul"))
    assert ids.shape[0] == len(probs)
    print(f"  build_batch: {len(probs)} converted rows in 3 scripts locate and lay out")


def main():
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"running {len(tests)} bank-corpus tests")
    for t in tests:
        print(f"- {t.__name__}")
        t()
    print(f"all {len(tests)} bank-corpus tests pass")


if __name__ == "__main__":
    main()
