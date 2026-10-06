"""bank_rows.py -- turn a bank row (data/banks/...) into a def-use row. NEW CODE (not a port).

The wild rows the project fitted on carry `numerals_written`, `prov.run_values` and `gold_frac`, and an equation in
a source format `inventory.parse_row` knows. Bank rows carry the same information under other names: `text` (the
prompt ending at the cue), `ans`, and for the multi-step bank v6ms an infix equation (`annotation.kind` "v6ms infix").
This adapter fills the def-use fields WITHOUT changing the row's text or answer:

  * numerals_written = prov.run_values = the plain digit groups of the text, in order (the v6ms builder's own
    locator is the same regex, and the dumper re-checks the count against the tokenizer);
  * gold_frac = the bank's answer as an exact fraction (`ans_frac` when present, else `ans`);
  * an infix equation "x=..." is parsed as the Ape210K-style infix format it is;
  * fold = the bank's own fold column you name, shifted so that ONE of its values becomes the held-out fold 5.

    from defuse.bank_rows import to_defuse_row
    row = to_defuse_row(bank_row, fold_key=("v6", "tmpl_fold"), heldout_value=5)

Which column to fold on is a design choice: template folds test new templates in seen languages; the v6ms language
folds (`v6.lang_fold`) test unseen languages. Choose before you fit, and keep the held-out value fixed.
"""
import copy
import re
from fractions import Fraction

DIGITS = re.compile(r"[0-9]+")


def _get(r, key):
    if isinstance(key, (tuple, list)):
        for k in key:
            r = (r or {}).get(k)
        return r
    return r.get(key)


def to_defuse_row(r, fold_key=None, heldout_value=None, values=(1, 2, 3, 4, 5)):
    """values: the fold column's five values (v6ms tmpl_fold / lang_fold: 1-5; subrole / divrole2 fold: 0-4)"""
    x = copy.deepcopy(r)
    text = x["text"]
    cue = x.get("answer_cue") or ""
    body = text[: len(text) - len(cue)] if cue and text.endswith(cue) else text
    groups = DIGITS.findall(body)
    x["numerals_written"] = list(groups)
    prov = dict(x.get("prov") or {})
    prov["run_values"] = list(groups)
    prov.setdefault("n_runs", len(groups))
    prov.setdefault("gold_run_idx", [])
    x["prov"] = prov
    if "gold_frac" not in x:
        x["gold_frac"] = str(Fraction(str(x["ans_frac"])) if x.get("ans_frac") is not None else Fraction(str(x["ans"])))
    ann = dict(x.get("annotation") or {})
    if (ann.get("kind") or "").split(" ")[-1] == "infix":
        ann["kind"] = "ape210k"                  # the parser's infix "x=..." format; the equation text is unchanged
    x["annotation"] = ann
    x.setdefault("status", "scored")
    if fold_key is not None:
        if heldout_value not in values:
            raise SystemExit("REFUSE (bank_rows): name the held-out value of %s (one of %s)" % (fold_key, values))
        v = int(_get(x, fold_key))
        others = [w for w in values if w != heldout_value]
        x["fold"] = 5 if v == heldout_value else others.index(v) + 1
    return x
