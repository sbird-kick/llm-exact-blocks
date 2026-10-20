"""selfcue_to_defuse.py -- turn the project's generated problem rows (rows file + gold file) into def-use rows.

The project's own generated rows (v1 ... v5, v8 bbx, v21 wildbig, v24 large-number copies) are kept as two files per
set: a rows file (`row_id`, `text` = the question, `lang`, `tid`, `src`, ...) and a gold file (`prog` with the gold
equation, `qnums` the numerals as written, `gold`, `steps`, ...). The def-use package (`defuse/`) reads one row with a
prompt that ends at the cue, an `annotation`, `numerals_written`, `prov` and `gold_frac`. This script joins the two files by
`row_id` and writes that row. It changes neither the question nor the answer:

  * text            = question + " The answer is"  (the cue the dumper expects; `answer_cue` is kept as its own field)
  * annotation      = {"kind": "ape210k", "equation": <gold equation, infix "x=...">}  (the parser's infix format,
                      the same choice `defuse/bank_rows.py` makes for the v6ms bank)
  * numerals_written= the gold file's `qnums` when they appear in the question in that order, else the digit groups
  * prov.run_values = the maximal runs of decimal characters (str.isdecimal, like the dumper's locator) of the question
  * gold_frac       = the gold answer as an exact fraction "p/q"
  * fold            = 1 + md5(family) % 4  (folds 1-4, same meaning as in the wild rows: you hold one out yourself)

Only rows whose split in the given manifest is "train" are read (the row id is matched on the raw line before any
JSON is parsed). Rows with no gold equation or no numeric gold (the abstain rows) are skipped and counted.

    python data_gen/selfcue_to_defuse.py --rows R/rows.jsonl --gold R/GOLD.jsonl --manifest M/selfcue_v24.jsonl \
        --set selfcue_v24 --out out.jsonl [--status] [--subset-key think_source]

Output rows are sorted as in the rows file. `--status` adds `pool.gold_status` by running the package's own gold parser.
"""
import argparse
import hashlib
import json
import re
import sys
from fractions import Fraction

CUE = "The answer is"
RID = re.compile(r'"row_id": ?"((?:[^"\\]|\\.)*)"')
KEEP_ROW_FIELDS = ("lang", "tid", "src", "derived_from_row_id", "size")
KEEP_GOLD_FIELDS = ("steps", "stratum", "width", "source_bank", "src_row", "orig_row_id", "band", "set", "bb_op")


def fold_of(family):
    return 1 + int(hashlib.md5(family.encode("utf-8")).hexdigest(), 16) % 4


def digit_runs(s):
    """maximal runs of decimal characters (the dumper's rule: str.isdecimal, so native digits count, a superscript does not)"""
    runs, cur = [], []
    for ch in s:
        if ch.isdecimal():
            cur.append(ch)
        elif cur:
            runs.append("".join(cur)); cur = []
    if cur:
        runs.append("".join(cur))
    return runs


def written_numerals(question, qnums):
    """qnums if every one appears in the question, in order; else None"""
    pos = 0
    for q in qnums:
        i = question.find(str(q), pos)
        if i < 0:
            return None
        pos = i + len(str(q))
    return [str(q) for q in qnums]


BB_OPS = {"plus": "+", "minus": "-", "times": "*", "divided by": "/"}
BB = re.compile(r"^What is (\d+) (plus|minus|times|divided by) (\d+)\?$")


def bb_equation(question):
    """the BIG-bench-style arithmetic rows (`What is 5 plus 8?`) carry no program; the equation is the sentence itself"""
    m = BB.match(question)
    return "x=%s%s%s" % (m.group(1), BB_OPS[m.group(2)], m.group(3)) if m else None


def numeric(x):
    try:
        Fraction(str(x).replace(",", ""))
        return True
    except (ValueError, ZeroDivisionError):
        return False


def frac_str(gold):
    f = Fraction(str(gold).replace(",", ""))
    return "%d/%d" % (f.numerator, f.denominator)


def convert(row, gold, man, set_name, subset_key=None):
    """one def-use row from a rows line, its gold line and its manifest entry; (row, note) with note in
    ok | numerals_regrouped"""
    question = row["text"].rstrip()
    if question.endswith(CUE):
        question = question[: -len(CUE)].rstrip()
    equation = (gold.get("prog") or {}).get("equation") or gold.get("eq") or bb_equation(question)
    runs = digit_runs(question)
    nw = written_numerals(question, gold.get("qnums") or [])
    note = "ok"
    if nw is None:
        nw, note = list(runs), "numerals_regrouped"
    out = {
        "row_id": row["row_id"],
        "fold": fold_of(man["family"]),
        "text": question + " " + CUE,
        "question": question,
        "answer_cue": CUE,
        "annotation": {"kind": "ape210k", "equation": equation},
        "numerals_written": nw,
        "prov": {"locator": "decimal-character runs of the question (str.isdecimal); the dumper re-checks n_runs",
                 "gold_run_idx": [], "n_runs": len(runs), "run_values": runs},
        "gold_frac": frac_str(gold["gold"]),
        "gold_str": str(gold["gold"]),
        "status": "scored",
        "source_set": set_name,
        "source_split": "train",
        "family": man["family"],
    }
    for k in KEEP_ROW_FIELDS:
        if row.get(k) is not None:
            out[k] = row[k]
    for k in KEEP_GOLD_FIELDS:
        if gold.get(k) is not None and k not in out:
            out[k] = gold[k]
    if subset_key:
        out[subset_key] = bool(gold.get(subset_key))
    return out, note


def load_manifest(path):
    m = {}
    for line in open(path, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            m[r["row_id"]] = r
    return m


def train_lines(path, man):
    """(row_id, raw line) for the lines whose manifest split is train; other lines are never parsed"""
    for line in open(path, encoding="utf-8"):
        m = RID.search(line)
        if m and (man.get(json.loads('"%s"' % m.group(1))) or {}).get("split") == "train":
            yield json.loads('"%s"' % m.group(1)), line


def row_text(line):
    return json.loads(line)["text"].rstrip()


def build(rows_path, gold_path, manifest_path, set_name, subset_key=None, with_status=False, skip_stratum=()):
    man = load_manifest(manifest_path)
    gold = {rid: json.loads(l) for rid, l in train_lines(gold_path, man)}
    out, skipped, notes = [], {}, {}
    inv = None
    if with_status:
        sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
        from defuse import reader_a as A
    for rid, line in train_lines(rows_path, man):
        g = gold.get(rid)
        if g is None:
            skipped["no_gold"] = skipped.get("no_gold", 0) + 1
            continue
        if skip_stratum and g.get("stratum") in skip_stratum:
            skipped["stratum_" + g["stratum"]] = skipped.get("stratum_" + g["stratum"], 0) + 1
            continue
        if not ((g.get("prog") or {}).get("equation") or g.get("eq") or bb_equation(row_text(line))) or not numeric(g.get("gold")):
            k = "no_numeric_gold_" + str(g.get("kind"))
            skipped[k] = skipped.get(k, 0) + 1
            continue
        row, note = convert(json.loads(line), g, man[rid], set_name, subset_key)
        notes[note] = notes.get(note, 0) + 1
        if with_status:
            row["pool"] = {"gold_status": A.gold_tree(row)[1], "n_runs": row["prov"]["n_runs"]}
        out.append(row)
    return out, skipped, notes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--set", required=True, dest="set_name")
    ap.add_argument("--out", required=True)
    ap.add_argument("--subset-key", default=None, help="a gold-file flag to copy into the row (e.g. think_source)")
    ap.add_argument("--skip-stratum", nargs="*", default=[], help="gold-file strata to leave out (e.g. wild: duplicates of data/more/wild rows)")
    ap.add_argument("--status", action="store_true", help="add pool.gold_status from the package's own parser")
    a = ap.parse_args()
    out, skipped, notes = build(a.rows, a.gold, a.manifest, a.set_name, a.subset_key, a.status, a.skip_stratum)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    print("wrote %d rows; skipped %s; numerals %s" % (len(out), skipped, notes))


if __name__ == "__main__":
    main()
