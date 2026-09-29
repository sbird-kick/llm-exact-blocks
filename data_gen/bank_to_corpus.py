#!/usr/bin/env python3
"""Turn signed-bank rows (any language) into the corpus format train.py and eval.py read.

    python data_gen/bank_to_corpus.py --bank banks/out/v3_61/signed_A_int.jsonl \\
        --langs ru,uk,pl --out data_slavic
    python train.py --data data_slavic ...            # unchanged
    python eval.py  --data data_slavic ...            # unchanged

Standard library only. Writes <out>/{train,val,test}.jsonl with exactly the fields of
exact_block.data.Problem (op, a, b, ans, prompt, completion, roles, cell, tmpl), so the
training and evaluation scripts need no new flag and the English corpus is untouched.

WHAT CHANGES ON THE WAY
  prompt      the bank row's `text` (it already ends with the language's "The answer is")
  completion  " <answer>\\n", as in the English corpus
  op          subtraction -> sub, addition -> add, product -> mul
  a, b        the bank's a / b: minuend and subtrahend for sub, the two operands otherwise
  roles       "a" / "b" / "d" for every numeral in the text, in written order
  cell        "<digits of a>x<digits of b>", the English corpus's width cell
  tmpl        the bank's story_id

WHAT IS LEFT OUT, AND WHY (every drop is counted and printed)
  * NEGATIVE ANSWERS. Half of a signed bank's subtraction rows have the smaller number as
    the minuend, so the answer is negative. The block has no sign channel: its calculator
    refuses a negative result, and build_batch cannot even lay out the digits of "-17".
    Those rows stay in the bank for the pair and role readers, but not in this corpus.
  * DECIMAL ROWS (signed_*_dec.jsonl). The locator reads "7.5" as two numerals.
  * any row that breaks the corpus contract: an operand that is not exactly one digit run,
    the answer written in the prompt, a digit that is not ASCII, an answer too wide for
    the answer lanes.

SPLITS
  --split-by story (default): a hash of the story number alone, so story N is in the same
    split in every language. The generator gives story N the same numerals in every
    language, so this keeps both the templates and (almost always) the numerals of a
    test story out of training.
  --split-by lang-story: a hash of (language, story). More even split sizes; the same
    numerals can then appear in train (one language) and test (another).
  --split-by pair: a hash of (op, a, b), the English corpus's rule.
  --test-langs xx,yy: those languages go to test only, whatever --split-by says (a
    held-out-language evaluation).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from exact_block.numerals_ml import non_ascii_digits  # noqa: E402

RUNS = re.compile(r"[0-9]+")
OP_MAP = {"subtraction": "sub", "addition": "add", "product": "mul"}
FIELDS = ("op", "a", "b", "ans", "prompt", "completion", "roles", "cell", "tmpl")


def bucket(key: str) -> str:
    h = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:8], 16) % 100
    return "train" if h < 80 else ("val" if h < 90 else "test")


def split_of(row: dict, how: str, test_langs: set) -> str:
    if row["lang"] in test_langs:
        return "test"
    if how == "story":
        return bucket(f"story:{row['story_id']}")
    if how == "lang-story":
        return bucket(f"{row['lang']}:{row['story_id']}")
    return bucket(f"{OP_MAP[row['op']]}:{row['a']}:{row['b']}")


def convert(row: dict, dmax: int = 16):
    """-> (problem dict, None) or (None, the reason the row is left out)."""
    if row.get("fill", "int") != "int":
        return None, "decimal row"
    op = OP_MAP.get(row.get("op", "subtraction"))
    if op is None:
        return None, f"operation {row.get('op')!r} has no body in the block"
    a, b, ans = row["a"], row["b"], row["ans"]
    if not all(isinstance(v, int) for v in (a, b, ans)):
        return None, "non-integer operand or answer"
    if ans < 0:
        return None, "negative answer (no sign channel)"
    text = row["text"]
    if non_ascii_digits(text):
        return None, "non-ASCII digit in the text"
    vals = [int(v) for v in RUNS.findall(text)]
    if vals.count(a) != 1 or vals.count(b) != 1:
        return None, "an operand is not exactly one digit run"
    if a == b:
        return None, "equal operands (roles undefined)"
    if ans in vals:
        return None, "the answer is written in the prompt"
    if max(len(str(a)), len(str(b))) > dmax or len(str(ans)) > 2 * dmax:
        return None, "wider than the block's lanes"
    roles = ["a" if v == a else ("b" if v == b else "d") for v in vals]
    prob = dict(op=op, a=a, b=b, ans=ans, prompt=text, completion=f" {ans}\n",
                roles=roles, cell=f"{len(str(a))}x{len(str(b))}", tmpl=int(row["story_id"]))
    return {k: prob[k] for k in FIELDS}, None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bank", nargs="+", required=True, help="one or more signed_*_int.jsonl files")
    ap.add_argument("--out", required=True, help="output directory (train/val/test.jsonl)")
    ap.add_argument("--langs", default="", help="comma-separated language codes (default: all)")
    ap.add_argument("--test-langs", default="", help="languages held out entirely into test")
    ap.add_argument("--split-by", choices=("story", "lang-story", "pair"), default="story")
    ap.add_argument("--ops", default="sub,add,mul", help="block bodies to keep")
    ap.add_argument("--dmax", type=int, default=16)
    a = ap.parse_args(argv)

    keep_langs = set(filter(None, a.langs.split(",")))
    test_langs = set(filter(None, a.test_langs.split(",")))
    keep_ops = set(a.ops.split(","))
    out = {"train": [], "val": [], "test": []}
    dropped = collections.Counter()
    per_lang = collections.Counter()
    seen = 0
    for path in a.bank:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                if keep_langs and row["lang"] not in keep_langs and row["lang"] not in test_langs:
                    continue
                seen += 1
                prob, why = convert(row, a.dmax)
                if prob is None:
                    dropped[why] += 1
                    continue
                if prob["op"] not in keep_ops:
                    dropped[f"op {prob['op']} not in --ops"] += 1
                    continue
                out[split_of(row, a.split_by, test_langs)].append(prob)
                per_lang[row["lang"]] += 1

    kept = sum(len(v) for v in out.values())
    if not kept:
        raise SystemExit(f"no row survived out of {seen}: {dict(dropped)}")
    os.makedirs(a.out, exist_ok=True)
    for split, rows in out.items():
        with open(os.path.join(a.out, f"{split}.jsonl"), "w", encoding="utf-8") as fh:
            for p in rows:
                fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"read {seen} rows, kept {kept}/{seen}, dropped {seen - kept}/{seen}")
    for why, n in dropped.most_common():
        print(f"   dropped {n}/{seen}: {why}")
    for split, rows in out.items():
        cells = collections.Counter(p["cell"] for p in rows)
        ops = collections.Counter(p["op"] for p in rows)
        print(f"{split}: {len(rows)} rows, ops {dict(ops)}, {len(cells)} cells")
    print(f"languages {len(per_lang)}: {dict(sorted(per_lang.items()))}")
    return out


if __name__ == "__main__":
    main()
