"""run.py -- the def-use pipeline on your own host, step by step (CPU after the dump). NEW CODE (a thin driver over
the ported functions; it adds no modelling of its own).

    # 0. GPU, once per host: dump the rows (layers = your host's real layers; see dump.py)
    python -m defuse.dump --host meta-llama/Llama-3.2-1B --tag l1b --out dumps --banks wild=rows.jsonl \\
        --layers 9,11,13 --max-runs 5 --greedy 12 --locator grouped
    # 1. reader B on folds 1-4 (grid on folds 1-3, selection on fold 4, refit on 1-4), one model per layer label
    python -m defuse.run fit-b    --rows rows.jsonl --dump dumps/l1b_wild_operandstate.pt --relabel 9:20,11:24,13:28 --out fitB
    # 2. leave-one-fold-out refits with the chosen setting, then out-of-fold decodes of folds 1-4 (the gate's data)
    python -m defuse.run lofo-b   --rows rows.jsonl --dump ... --relabel ... --fit fitB --out lofo
    # 3. the gate on the out-of-fold decodes (folds 1-4 only), tau = your R1 budget fraction
    python -m defuse.run fit-gate --records lofo/OOF.jsonl --tau 0.0075 --out gate.json
    # 4. ONCE: decode the held-out fold with the frozen models, then score it
    python -m defuse.run decode-b --rows heldout_rows.jsonl --dump ... --relabel ... --fit fitB --heldout --out fold5.jsonl
    python -m defuse.evaluate --records fold5.jsonl --gate gate.json --label "Llama-3.2-1B, <gpu>"

Host fields. The host's own answer comes from the dump (--greedy N): host1 = the first number in its greedy text
(a decimal or a plain integer, commas removed), host1_none = it wrote no number, host1_right = host1 == gold_frac.
This is NEW and simpler than the project's wild scorer; report it as such.
"""
import argparse
import json
import os
import re
from fractions import Fraction

import numpy as np

from . import data as D
from . import fit_b as FB
from . import gate as GT
from . import guard as G
from . import reader_a as A
from . import reader_b as B

NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def host_fields(meta, row):
    """NEW: host1 / host1_none / host1_right from the dump's greedy text (see the module docstring)"""
    raw = meta.get("greedy_raw")
    if raw is None:
        raise SystemExit("REFUSE: the dump has no greedy text; dump with --greedy 12 to get host-outcome labels")
    m = NUM.search(raw)
    if not m:
        return dict(host1=None, host1_none=True, host1_right=False)
    try:
        v = Fraction(m.group(0).replace(",", ""))
    except (ValueError, ZeroDivisionError):
        return dict(host1=None, host1_none=True, host1_right=False)
    return dict(host1=str(v), host1_none=False, host1_right=(v == Fraction(row["gold_frac"])))


def _relabel(s):
    return {int(a): int(b) for a, b in (x.split(":") for x in s.split(","))} if s else None


def _load(a, scoring=False):
    rows = D.load_rows(a.rows, fit=not scoring)
    st = D.load_dump(a.dump)
    if a.relabel:
        D.relabel_layers(st, _relabel(a.relabel))
    rows = D.rows_in_dump_order(st, rows, scoring=scoring)
    J = list(range(len(rows)))
    asms = {L: A.assemble(rows, st, J, L, 5) for L in A.LAYERS}
    return rows, st, asms


def cmd_fit_b(a):
    rows, st, asms = _load(a)
    os.makedirs(a.out, exist_ok=True)
    folds = [r["fold"] for r in rows]
    for L in A.LAYERS:
        res, _ = FB.run_fitb(FB.make_rows_by_fold(asms[L], folds), a.out, L)
        print(json.dumps(res))


def _fixed_setting_fit(data, d, ch):
    """the chosen setting refitted on other data: run_fitb's final-refit lines with the setting fixed"""
    m = B.ReaderB(d, dg=FB.F2_GRID["dg"], de=FB.F2_GRID["de"], seed=0, l2=ch["l2"])
    m.fit([x[:4] for x in data], epochs=ch["epochs"], stats=FB.b_stats(data), lr=ch["lr"], clip=ch["clip"])
    return m


def cmd_lofo_b(a):
    rows, st, asms = _load(a)
    os.makedirs(a.out, exist_ok=True)
    folds = [r["fold"] for r in rows]
    recs = []
    for k in (1, 2, 3, 4):
        models = {}
        for L in A.LAYERS:
            ch = json.load(open(os.path.join(a.fit, "READERB_L%d.json" % L)))["chosen"]
            data = FB.make_rows_by_fold(asms[L], folds)(tuple(f for f in (1, 2, 3, 4) if f != k))
            models[L] = _fixed_setting_fit(data, asms[L]["Xs"].shape[1], ch)
        for i, r in enumerate(rows):
            if r["fold"] == k:
                recs.append(FB.decode_record(models, asms, i, r, host_fields(st["meta"][i], r), fold=k))
    with open(os.path.join(a.out, "OOF.jsonl"), "w", encoding="utf-8") as f:
        for x in recs:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print("OOF records: %d (folds 1-4)" % len(recs))


def cmd_decode_b(a):
    if not a.heldout:
        raise SystemExit("REFUSE: decode-b is the held-out scoring pass; pass --heldout to confirm (once, frozen models)")
    with G.scoring_pass():
        rows, st, asms = _load(a, scoring=True)
        models = {L: B.ReaderB.from_state(np.load(os.path.join(a.fit, "READERB_L%d.npz" % L))) for L in A.LAYERS}
        with open(a.out, "w", encoding="utf-8") as f:
            for i, r in enumerate(rows):
                rec = FB.decode_record(models, asms, i, r, host_fields(st["meta"][i], r), fold=r.get("fold"))
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("decoded %d rows -> %s" % (len(rows), a.out))


def cmd_fit_gate(a):
    recs = [json.loads(l) for l in open(a.records, encoding="utf-8") if l.strip()]
    probes = None
    if a.probes:
        probes = {x["row_id"]: x for x in (json.loads(l) for l in open(a.probes, encoding="utf-8") if l.strip())}
    g = GT.fit_gate(recs, a.tau, side="b", probes=probes)
    json.dump(g, open(a.out, "w"), indent=1, sort_keys=True)
    print("gate: cut %.4f, folds-1-4 OOF broken %s (budget %d), fixed %d; md5 %s" % (
        g["cut"], GT.nt(g["oof_broken"], g["oof_HR"]), g["budget"], g["oof_fixed"], G.md5f(a.out)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fit-b", "lofo-b", "decode-b"):
        p = sp.add_parser(name)
        p.add_argument("--rows", required=True); p.add_argument("--dump", required=True)
        p.add_argument("--relabel", default="", help="real:label pairs, e.g. 16:20,19:24,22:28")
        p.add_argument("--out", required=True)
        if name != "fit-b":
            p.add_argument("--fit", required=True, help="the fit-b output folder")
        if name == "decode-b":
            p.add_argument("--heldout", action="store_true")
    p = sp.add_parser("fit-gate")
    p.add_argument("--records", required=True); p.add_argument("--tau", type=float, required=True)
    p.add_argument("--probes", default=None); p.add_argument("--out", required=True)
    a = ap.parse_args()
    {"fit-b": cmd_fit_b, "lofo-b": cmd_lofo_b, "decode-b": cmd_decode_b, "fit-gate": cmd_fit_gate}[a.cmd](a)


if __name__ == "__main__":
    main()
