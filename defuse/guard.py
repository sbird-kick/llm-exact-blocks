"""guard.py -- the fold discipline, in the shape the ported readers expect (md5f / check_path / check_row_id).

The project's own guard is a cluster-specific audit hook with an allow-list of paths. This replacement keeps the
part that matters for anyone fitting on def-use data: **fold 5 is the held-out fold and fold 6 is the official
test split of the source datasets; neither is ever fitted, calibrated or selected on.** Two checks enforce it:

  * a row (or a dump's meta row) whose `fold` field is 5 or 6 is refused;
  * a row id on a blocklist is refused.
    The blocklist is empty by default; `set_blocklist(path)` loads one id per line (`defuse.data` does this for
    you when the data folder ships `HELDOUT_IDS.txt`).
Both checks are lifted only inside `with scoring_pass():`, the single scoring pass with frozen settings.

`check_path` refuses file names that belong to evaluation sets (the GSM8K test family, MGSM, AfriMGSM, SVAMP,
the held-out `fresh` set, fold 5 / official test files). It is a tripwire for honest mistakes, not a sandbox.

NEW CODE (not a port): this module was written for the students' package; see PROVENANCE.md.
"""
import hashlib
import os
import re

HELDOUT_FOLDS = (5, 6)
EVAL_NAME = re.compile(r"(gsm8k_?test|gsm8ktest|mgsm|afrimgsm|gsm-?plus|gsm-?hard|svamp|singleeq|(^|[/_])e2[_.]|"
                       r"(^|/)fresh(/|$)|fold_?5|fold_?6|official_?test|heldout)", re.I)
S = dict(blocklist=frozenset(), blocklist_path=None, scoring=False)


class Refused(PermissionError):
    pass


def md5f(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def set_blocklist(path):
    """load held-out row ids (one per line); an absent path clears the list"""
    if path is None or not os.path.exists(path):
        S.update(blocklist=frozenset(), blocklist_path=None)
        return 0
    ids = frozenset(l.strip() for l in open(path, encoding="utf-8") if l.strip())
    S.update(blocklist=ids, blocklist_path=os.path.abspath(path))
    return len(ids)


def check_path(path):
    name = os.fspath(path)
    if EVAL_NAME.search(name.replace("\\", "/")):
        raise Refused("REFUSE (defuse guard): %s looks like an evaluation / held-out file; fits never read those" % name)
    return path


class scoring_pass:
    """`with guard.scoring_pass():` -- the ONE pass that decodes / scores held-out rows with frozen settings. Inside
    it check_row_id lets fold-5 / fold-6 / blocklisted rows through; the fit functions (fit_b.make_rows_by_fold,
    gate.fit_gate) refuse those folds on their own regardless."""

    def __enter__(self):
        S["scoring"] = True
        return self

    def __exit__(self, *exc):
        S["scoring"] = False
        return False


def check_row_id(rid, row=None):
    if S["scoring"]:
        return True
    if rid in S["blocklist"]:
        raise Refused("REFUSE (defuse guard): row %s is on the held-out blocklist %s" % (rid, S["blocklist_path"]))
    if row is not None and row.get("fold") in HELDOUT_FOLDS:
        raise Refused("REFUSE (defuse guard): row %s is fold %s (held out: never fitted on)" % (rid, row.get("fold")))
    return True
