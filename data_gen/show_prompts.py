#!/usr/bin/env python3
"""Look at the prompts of a bank: print rows, one template's variants, or counts, with filters.

    python data_gen/show_prompts.py                                   # 5 rows of bank v5
    python data_gen/show_prompts.py --lang ru --op sub --numerals 3 -n 10
    python data_gen/show_prompts.py --template W5-en-u05-05           # all 24 variants of one template
    python data_gen/show_prompts.py --rung L3_list --position between --random -n 5
    python data_gen/show_prompts.py --tag numdep --lang uk            # templates kept with number-dependent grammar
    python data_gen/show_prompts.py --count lang,dist_arm             # how many rows per language x arm
    python data_gen/show_prompts.py --bank banks/v4/signed_A_int.jsonl --hardness sem2 --lang ta
    python data_gen/show_prompts.py --novelty my_unit.json            # near copies of shipped v5 templates?

The bank is read line by line, so it works on the 290 MB v5 file without loading it. It
works on every bank in banks/ (v3_61, v4, v4wild, v5); filters on fields a bank does not
carry (d_rungs, tags, template_id: v5 only) simply match nothing there.

Each printed row is its text, then one line of labels: the operation, the two operands a
and b (for sub the minuend and the subtrahend; for div the dividend and the divisor), the
answer, the distractor values ds, and for v5 the arm, the distractor rungs, positions and
value tiers. Standard library only.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_BANK = os.path.join(REPO, "banks", "v5", "bank", "signed_A_int.jsonl")
DEFAULT_CLEAN = os.path.join(REPO, "banks", "v5", "clean", "r1-16")   # one <lang>.json per language

OP_SHORT = {"addition": "add", "subtraction": "sub", "product": "mul", "division": "div"}


def template_key(row: dict) -> str:
    """v5 rows name their template; older rows are identified by prefix:lang:bank:story."""
    return row.get("template_id") or ":".join(str(row.get("row_id", "")).split(":")[:4])


def op_of(row: dict) -> str:
    return row.get("op_short") or OP_SHORT.get(row.get("op"), row.get("op") or "?")


def as_list(v) -> list:
    return v if isinstance(v, list) else ([] if v is None else [v])


def matches(row: dict, a) -> bool:
    if a.lang and row.get("lang") not in a.lang:
        return False
    if a.op and op_of(row) not in a.op:
        return False
    if a.template and template_key(row) != a.template:
        return False
    if a.numerals and row.get("n_numerals_written") not in a.numerals:
        return False
    if a.arm and row.get("dist_arm") not in a.arm:
        return False
    if a.hardness and row.get("dist_hardness") not in a.hardness:
        return False
    if a.kind and row.get("kind") not in a.kind:
        return False
    if a.variant and row.get("variant") not in a.variant:
        return False
    if a.shape and row.get("shape") not in a.shape:
        return False
    for want, field in ((a.rung, "d_rungs"), (a.position, "d_positions"), (a.tier, "d_tiers")):
        if want and not set(want) & set(as_list(row.get(field))):
            return False
    if a.tag:
        tags = set(as_list(row.get("tags")))
        if a.tag == ["none"]:
            if tags:
                return False
        elif not set(a.tag) & tags:
            return False
    if a.grep and a.grep not in row.get("text", ""):
        return False
    return True


def iter_rows(path: str):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def label_line(row: dict, extra) -> str:
    parts = [f"{op_of(row)} a={row.get('a')} b={row.get('b')} ans={row.get('ans')} ds={row.get('ds')}",
             f"kind={row.get('kind')} variant={row.get('variant')} n={row.get('n_numerals_written')}"]
    if row.get("dist_arm") is not None:
        parts.append(f"arm={row.get('dist_arm')}")
    if row.get("d_rungs"):
        parts.append(f"rungs={row['d_rungs']} pos={row.get('d_positions')} tiers={row.get('d_tiers')}")
    elif row.get("dist_hardness"):
        parts.append(f"hardness={row['dist_hardness']} pos={row.get('distractor_pos')}")
    if row.get("tags"):
        parts.append(f"tags={row['tags']}")
    for f in extra:
        parts.append(f"{f}={row.get(f)!r}")
    return "   " + "  ".join(parts)


def print_row(row: dict, extra, out) -> None:
    print(f"[{row.get('lang')}] {template_key(row)}  {row.get('row_id')}", file=out)
    print("   " + row.get("text", ""), file=out)
    if row.get("frame_gloss"):
        print("   gloss: " + row["frame_gloss"], file=out)
    print(label_line(row, extra), file=out)
    print(file=out)


def novelty(path: str, clean: str, out) -> int:
    """Char-4-gram Jaccard of each template in a writer file against the shipped v5 templates
    of its language, with the same text and threshold as validate_v5.py's [novelty] check."""
    sys.path.insert(0, os.path.join(REPO, "banks", "v5"))
    import v5_common as C  # noqa: E402  (standard library; lives beside the v5 tools)
    unit = json.load(open(path, encoding="utf-8"))
    lang = unit.get("language_code")
    if os.path.isdir(clean):   # the shipped per-language files
        kept = json.load(open(os.path.join(clean, f"{lang}.json"), encoding="utf-8"))["kept"]
    else:                      # a single clean file, as check_v5.py --clean writes it
        kept = json.load(open(clean, encoding="utf-8"))["kept"]
    prior = [(k["template"]["id"], C.shingles(C.dup_text(k["template"]))) for k in kept if k["lang"] == lang]
    bad = 0
    for it in unit.get("items", []):
        sh = C.shingles(C.dup_text(it))
        best = max(((C.jaccard(sh, p), tid) for tid, p in prior), default=(0.0, "-"))
        flag = best[0] >= C.NEAR_DUP
        bad += flag
        print(f"  {'NEAR' if flag else 'ok  '} {it.get('id')}  max Jaccard {best[0]:.2f} with {best[1]}", file=out)
    print(f"novelty vs {len(prior)} shipped {lang} templates: {bad}/{len(unit.get('items', []))} "
          f"at or above {C.NEAR_DUP}", file=out)
    return 1 if bad else 0


def main(argv=None, out=sys.stdout) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bank", default=DEFAULT_BANK, help="a signed_A_int.jsonl (default: bank v5)")
    csv = lambda s: [x for x in s.split(",") if x]  # noqa: E731
    ap.add_argument("--lang", type=csv, help="language codes, comma-separated (ru,uk)")
    ap.add_argument("--op", type=csv, help="add,sub,mul,div")
    ap.add_argument("--template", help="one template: v5 id (W5-en-u05-05) or older prefix:lang:bank:story (sg:ta:A:3)")
    ap.add_argument("--numerals", type=lambda s: [int(x) for x in csv(s)], help="numerals written in the text: 2,3,4,5")
    ap.add_argument("--arm", type=csv, help="v5 arm: base,T,ex,sem,T+s,T+ex+sem")
    ap.add_argument("--rung", type=csv, help="v5 distractor rung: L0_kind,L1_owner_sent,L1_owner,L2_time,L3_list")
    ap.add_argument("--position", type=csv, help="v5 distractor position: before,between,after")
    ap.add_argument("--tier", type=csv, help="v5 distractor value tier: V0_len,V1_same_len,V2_near")
    ap.add_argument("--hardness", type=csv, help="v3/v4 distractor kind: easy,matched,sem1,sem2,multi2,multi3,wildT")
    ap.add_argument("--tag", type=csv, help="v5 template tags: numdep,demoted, or none (untagged only)")
    ap.add_argument("--kind", type=csv, help="pos,neg")
    ap.add_argument("--variant", type=csv, help="min_first,sub_first (which operand is written first)")
    ap.add_argument("--shape", type=csv, help="v5 shape: list,other_time,diff_owner")
    ap.add_argument("--grep", help="only rows whose text contains this string")
    ap.add_argument("-n", type=int, default=5, help="rows to print (0 = all); ignored with --template")
    ap.add_argument("--random", action="store_true", help="a seeded random sample instead of the first n")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fields", type=csv, default=[], help="extra row fields to print")
    ap.add_argument("--count", type=csv, help="count matching rows by these fields instead of printing them")
    ap.add_argument("--novelty", metavar="WRITER_FILE", help="compare a writer unit with the shipped v5 templates")
    ap.add_argument("--clean", default=DEFAULT_CLEAN,
                    help="--novelty compares with: the per-language folder (default) or one clean file")
    a = ap.parse_args(argv)

    if a.novelty:
        return novelty(a.novelty, a.clean, out)
    if not os.path.exists(a.bank):
        print(f"no bank at {a.bank}: run python banks/make_v5.py (or make_banks.py for v3_61/v4/v4wild)", file=out)
        return 2

    rows = (r for r in iter_rows(a.bank) if matches(r, a))
    if a.count:
        c = collections.Counter(tuple(str(r.get(f)) for f in a.count) for r in rows)
        for key, n in sorted(c.items()):
            print(f"{n:8d}  " + "  ".join(key), file=out)
        print(f"{sum(c.values()):8d}  total", file=out)
        return 0
    if a.template:
        got = list(rows)
        got.sort(key=lambda r: (str(r.get("dist_arm")), str(r.get("variant")), str(r.get("qorder")), str(r.get("row_id"))))
    elif a.random:
        # reservoir sample: one pass, memory for n rows only
        rng, got, seen = random.Random(a.seed), [], 0
        for r in rows:
            seen += 1
            if len(got) < a.n:
                got.append(r)
            else:
                j = rng.randrange(seen)
                if j < a.n:
                    got[j] = r
    else:
        got = []
        for r in rows:
            got.append(r)
            if a.n and len(got) >= a.n:
                break
    for r in got:
        print_row(r, a.fields, out)
    print(f"{len(got)} row(s) shown", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
