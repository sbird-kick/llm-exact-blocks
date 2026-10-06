"""data.py -- loading def-use rows and dumps with the fold discipline built in. NEW CODE (not a port).

Folds. Every def-use row carries `fold` in 1..6. Folds 1-4 are for fitting (heads, decoder, gate thresholds, every
setting). Fold 5 is the held-out fold: it is scored ONCE with frozen settings and never fitted, calibrated or
selected on. Fold 6 is the source datasets' own official test splits (and rows linked to them): never fitted on
either. `load_rows(..., fit=True)` refuses any fold-5 / fold-6 row (and any id on a held-out blocklist) and stops;
`load_rows(..., fit=False)` is for the one scoring pass.

Rows from the project's pools are grouped into folds by connected components over a numbers-masked template key
and near-duplicate links (`inventory.tkey`), so no paraphrase straddles two folds. If you build your own rows, group
them the same way before you assign folds (see MIGRATION.md).
"""
import json
import os

from . import guard as G
from . import reader_a as A

FIT_FOLDS = (1, 2, 3, 4)


def load_rows(path, fit=True, blocklist=None, folds=None):
    """rows of a .jsonl file. fit=True: refuse fold 5 / 6 and blocklisted ids (raises guard.Refused).
    folds: keep only these folds (after the check)."""
    G.check_path(path) if fit else None
    if blocklist is not None:
        G.set_blocklist(blocklist)
    else:
        G.set_blocklist(os.path.join(os.path.dirname(os.path.abspath(path)), "HELDOUT_IDS.txt"))
    out = []
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        if fit:
            G.check_row_id(r["row_id"], r)
            if r.get("fold") is not None and r["fold"] not in FIT_FOLDS:
                raise G.Refused("REFUSE (defuse data): row %s has fold %s; fit rows are folds 1-4" % (r["row_id"], r["fold"]))
        if folds is None or r.get("fold") in folds:
            out.append(r)
    return out


def load_dump(path):
    """a dump written by defuse.dump (.pt, torch) or a .npz fixture"""
    return A.load_dump(path)


def relabel_layers(st, real_to_label):
    """The readers address layers by LABEL (20 / 24 / 28: the project's labels; at 1.7B / 0.6B the real layers were
    16 / 19 / 22 and at 32B 42 / 48 / 56). Dump at your host's real layers, then relabel, e.g.
    relabel_layers(st, {16: 20, 19: 24, 22: 28}). Returns st with `layers` / `space_layers` rewritten and the real
    ones kept in `real_layers` / `real_space_layers`."""
    st["real_layers"] = list(st["layers"]); st["real_space_layers"] = list(st["space_layers"])
    st["layers"] = [real_to_label[int(x)] for x in st["layers"]]
    st["space_layers"] = [real_to_label[int(x)] for x in st["space_layers"]]
    return st


def rows_in_dump_order(st, rows, scoring=False):
    """the rows that the dumper KEPT (it skips rows whose run count differs from prov.n_runs), in dump order, with
    the project's row-for-row check (A.join_dump_rows)"""
    by = {r["row_id"]: r for r in rows}
    meta = st["meta"]
    missing = [m["row_id"] for m in meta if m["row_id"] not in by]
    if missing:
        raise SystemExit("REFUSE: %d dump rows are not in the row file (first %s)" % (len(missing), missing[0]))
    kept = [by[m["row_id"]] for m in meta]
    if scoring:
        with G.scoring_pass():
            return A.join_dump_rows(st, kept)
    return A.join_dump_rows(st, kept)
