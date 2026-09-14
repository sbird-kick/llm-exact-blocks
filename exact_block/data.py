"""THE CORPUS. Templated English prose, distractor numbers, and `off` rows.

A row is a prompt that stops exactly where the answer begins, plus the completion that
answers it:

    prompt      "Each of the 4821 trays holds 63 seedlings, so the nursery holds"
    completion  " 303723\n"

Three things about this corpus are doing real work, and the block is much easier than it
looks without any of them:

  * DISTRACTORS. Half the templates render a third number that is not an operand. Without
    them "the last two numbers" is a perfect locator and the span tagger learns nothing.
  * REVERSED RENDER ORDER. Several subtraction and multiplication templates put {b} before
    {a} in the sentence ("From 9310 subtract 47", "216 of the 740 seats"), so the roles
    cannot be read off position either.
  * `off` ROWS. Prose that contains numbers, ends in an answer-shaped slot, and asks for
    no arithmetic at all. These are the only reason the router's `off` class means
    anything, and they are the negative half of every route number in the report.

NO TEMPLATE CONTAINS A LITERAL DIGIT. A stray "7" in the prose would be a third number
run, the locator's arity check would drop the row, and an entire template could vanish
from training in silence.

SPLITS ARE PROBLEM-DISJOINT, not row-disjoint: the split is a hash of (op, a, b), so the
same operand pair can never appear in two files under any template.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import dataclass, asdict

from .calc import OPS, exact_answer

SLOTS = ("{a}", "{b}", "{d1}", "{d2}")

TEMPLATES = {
    "add": [
        "The depot received {a} bolts on Monday and {b} bolts on Tuesday, so the running total is",
        "A survey counted {a} households in the eastern ward and {b} in the western ward; taken together that is",
        "Adding {a} to {b} gives",
        "Of the {d1} forms filed that season, {a} were approved in the first round and {b} in the second, for a combined",
        "Two batches left the plant, one of {a} units and one of {b} units, while {d1} units stayed behind; the two shipped batches come to",
        "The northern branch banked {b} kroner and the southern branch banked {a} kroner, which sums to",
    ],
    "sub": [
        "The vault held {a} coins before {b} were withdrawn, leaving",
        "Subtract {b} from {a} to get",
        "From {a} subtract {b}, which leaves",
        "{b} of the {a} seats had already been sold, so the number still free is",
        "After {b} litres evaporated from a tank of {a} litres, what remains is",
        "The archive listed {d1} crates in all; of the {a} that were catalogued, {b} have since been returned, leaving",
    ],
    "mul": [
        "Each of the {a} trays holds {b} seedlings, so the nursery holds",
        "Multiply {a} by {b} to obtain",
        "The rate is {b} grams per sample and there are {a} samples, giving a mass of",
        "A grid of {a} rows by {b} columns contains",
        "Ignoring the {d1} spoiled cases, the plant packs {a} boxes of {b} jars each, which is",
        "The product of {a} and {b} equals",
    ],
    # NEGATIVES. Numbers present, an answer-shaped slot at the end, no arithmetic asked.
    # The router must reach `off` on every one of these, and the write must stay silent.
    "off": [
        "The report numbered {d1} and the memo numbered {d2} were both filed by the clerk whose surname was",
        "Between kilometre {d1} and kilometre {d2} the road stayed closed, and the contractor responsible was",
        "Shelf {d1} of the reading room held the bound volumes, while shelf {d2} was reserved for the atlas of",
        "The inspector signed form {d1} in the morning and form {d2} that evening, in the town of",
        "Of the {d1} delegates and the {d2} observers, the only one to speak twice was the representative from",
        "Ticket {d1} was issued at the gate and ticket {d2} at the counter, both printed on paper supplied by",
    ],
}


@dataclass
class Problem:
    op: str                 # "add" | "sub" | "mul" | "off"
    a: int
    b: int
    ans: int
    prompt: str
    completion: str
    roles: list             # "a" / "b" / "d", one per rendered number, in text order
    cell: str               # e.g. "8x4", "" for an off row
    tmpl: int


def roles_of(template: str) -> list:
    """Which number each rendered slot is, in the order the template writes them."""
    hits = []
    for slot in SLOTS:
        start = 0
        while True:
            i = template.find(slot, start)
            if i < 0:
                break
            hits.append((i, slot))
            start = i + 1
    hits.sort()
    return [{"{a}": "a", "{b}": "b"}.get(s, "d") for _, s in hits]


def split_of(op: str, a: int, b: int) -> str:
    """Problem-disjoint split: a stable hash of the OPERANDS, never of the row."""
    h = int(hashlib.md5(f"{op}:{a}:{b}".encode()).hexdigest()[:8], 16) % 100
    return "train" if h < 80 else ("val" if h < 90 else "test")


def sample_width(d: int, rng: random.Random) -> int:
    """A uniformly random integer with EXACTLY d decimal digits."""
    return rng.randrange(10 ** (d - 1), 10 ** d) if d > 1 else rng.randrange(1, 10)


def make_problem(op: str, cell: str, rng: random.Random, split: str,
                 tries: int = 400) -> Problem | None:
    da, db = (int(x) for x in cell.split("x"))
    for _ in range(tries):
        a, b = sample_width(da, rng), sample_width(db, rng)
        if op == "sub" and a < b:
            continue                       # no sign channel in the answer lanes
        if split_of(op, a, b) != split:
            continue
        ans = exact_answer(a, b, op)
        t = rng.randrange(len(TEMPLATES[op]))
        template = TEMPLATES[op][t]
        roles = roles_of(template)
        fills = {"a": a, "b": b}
        used = {a, b, ans}
        for i in (1, 2):
            if "{d%d}" % i not in template:
                continue
            for _ in range(50):
                d = sample_width(rng.randint(1, 6), rng)
                if d not in used:
                    break
            used.add(d)
            fills["d%d" % i] = d
        prompt = template.format(**fills)
        return Problem(op=op, a=a, b=b, ans=ans, prompt=prompt,
                       completion=f" {ans}\n", roles=roles, cell=cell, tmpl=t)
    return None


def make_off(rng: random.Random) -> Problem:
    t = rng.randrange(len(TEMPLATES["off"]))
    template = TEMPLATES["off"][t]
    fills = {"d1": sample_width(rng.randint(1, 8), rng),
             "d2": sample_width(rng.randint(1, 8), rng)}
    return Problem(op="off", a=0, b=0, ans=0, prompt=template.format(**fills),
                   completion="", roles=roles_of(template), cell="", tmpl=t)


def generate(split: str, cells, ops, per_cell: int, n_off: int, seed: int) -> list:
    rng = random.Random(hashlib.md5(f"{split}:{seed}".encode()).hexdigest()[:8])
    out = []
    for op in ops:
        for cell in cells:
            got = 0
            while got < per_cell:
                p = make_problem(op, cell, rng, split)
                assert p is not None, f"could not sample {op} {cell} for {split}"
                out.append(p)
                got += 1
    out.extend(make_off(rng) for _ in range(n_off))
    rng.shuffle(out)
    return out


def write_jsonl(path: str, problems) -> None:
    with open(path, "w") as f:
        for p in problems:
            f.write(json.dumps(asdict(p)) + "\n")


def read_jsonl(path: str) -> list:
    with open(path) as f:
        return [Problem(**json.loads(line)) for line in f if line.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description="generate the templated arithmetic corpus")
    ap.add_argument("--out", default="data", help="output directory")
    ap.add_argument("--ops", default=",".join(OPS))
    ap.add_argument("--train-cells", default="4x4,6x6,8x8,8x4")
    ap.add_argument("--eval-cells", default="4x4,6x6,8x8,8x4,5x5,6x3",
                    help="the two extra cells are HELD OUT widths: never trained")
    ap.add_argument("--train-per-cell", type=int, default=3000)
    ap.add_argument("--eval-per-cell", type=int, default=200)
    ap.add_argument("--off-frac", type=float, default=0.25,
                    help="off rows as a fraction of the arithmetic rows")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    import os
    os.makedirs(a.out, exist_ok=True)
    ops = tuple(a.ops.split(","))
    tr_cells = tuple(a.train_cells.split(","))
    ev_cells = tuple(a.eval_cells.split(","))
    plan = [
        ("train", tr_cells, a.train_per_cell),
        ("val", ev_cells, max(1, a.eval_per_cell // 4)),
        ("test", ev_cells, a.eval_per_cell),
    ]
    for split, cells, per_cell in plan:
        n_arith = per_cell * len(cells) * len(ops)
        rows = generate(split, cells, ops, per_cell,
                        int(round(n_arith * a.off_frac)), a.seed)
        path = os.path.join(a.out, f"{split}.jsonl")
        write_jsonl(path, rows)
        n_off = sum(1 for p in rows if p.op == "off")
        print(f"{path}: {len(rows)} rows  ({len(rows) - n_off} arithmetic, {n_off} off, "
              f"cells {','.join(cells)})")


if __name__ == "__main__":
    main()
