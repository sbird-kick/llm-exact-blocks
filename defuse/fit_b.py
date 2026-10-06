"""fit_b.py -- fit reader B (the tree decoder) on folds 1-4 and decode rows into DU-AG records.

    rows_by_fold = make_rows_by_fold(asm_24, folds_of_rows)    # B's training tuples from an assembled layer
    res, model = run_fitb(rows_by_fold, out_dir, L=24)          # grid on folds 1-3, select on fold 4, refit on 1-4
    rec = decode_record(models, asms, i, row, host)             # one row -> the record the gate and ledger read

PORTED: `b_stats`, `b_exact`, `run_fitb` and the grids `B_GRID` / `F2_GRID` are line-range copies of the project's
pinned fit driver `defuse_fit.py` at its F2 version (md5 80e86a7537404ae1420c25b58b652997); `run_fitb`'s three data
calls are patched from the project's cluster cache to the `rows_by_fold` callable (PROVENANCE.md).
NEW: `b_data`, `make_rows_by_fold`, `decode_record` re-assemble, over in-memory rows, the same predicates as the
project's `b_rows` (defuse_fit.py) and the record fields of `bgate.py` (readerB, md5 81a72db4).
The grid the project used (F2_GRID): l2 in {1e-4, 1e-3}, lr in {3e-3, 1e-3}, epochs in {10, 20, 30}, dg 64, de 8,
gradient clip 1.0, decode beam 8, fold-4 selection on at most 3000 rows; R = 5 runs per row.
"""
import json, os
from fractions import Fraction
import numpy as np
from . import reader_a as A
from . import reader_b as B

LAYERS = A.LAYERS


def P(*a):
    print(*a, flush=True)


B_GRID = dict(l2=(1e-4, 1e-3), epochs=(10, 20, 30), dg=64, de=8, beam=8, val_cap=3000)
# F2: the B refit grid. lr is now chosen on fold 4 too (F1 ran at the fit() default 3e-3, not the 4e-3 F1 s2 states);
# global-norm gradient clipping 1.0 is always on (F1's B diverged on real rows before it went NaN: job 26050)
F2_GRID = dict(B_GRID, lr=(3e-3, 1e-3), clip=1.0)


def b_stats(data, n=5000, seed=0):
    r = np.random.default_rng(seed)
    sel = r.choice(len(data), min(n, len(data)), replace=False)
    Q = np.stack([data[k][0] for k in sel]).astype(np.float64)
    Hm = np.concatenate([data[k][1][data[k][2]] for k in sel]).astype(np.float64)
    allx = np.concatenate([Q, Hm]); mu = allx.mean(0); sd = allx.std(0); live = sd > 0
    floor = 1e-3 * float(np.median(sd[live])) if live.any() else 1.0
    return mu, np.where(live, np.maximum(sd, floor), 1.0)


def b_exact(m, data):
    ok = 0
    for q, h, valid, toks, r in data:
        al = A.align_numerals(r); nums = A.numeral_values(r); rv = {}
        for ni, rk in enumerate(al):
            if rk is not None and rk < 5 and nums[ni] is not None:
                rv.setdefault(rk, (ni, nums[ni]))
        bt, _ = B.best_program(m, np.asarray(q, float), np.asarray(h, float), valid, rv, beam=B_GRID["beam"])
        t, _ = A.gold_tree(r)
        ok += bt is not None and A.canon(bt) == A.canon(t)
    return ok


def run_fitb(rows_by_fold, out, L, grid=F2_GRID):
    tr = rows_by_fold((1, 2, 3))
    va = _cap(rows_by_fold((4,)), grid["val_cap"])
    d = tr[0][0].shape[0]
    stats = b_stats(tr)
    sel = {}
    lrs = grid.get("lr", (3e-3,)); clip = grid.get("clip")
    for l2 in grid["l2"]:
        for lr in lrs:
            m = B.ReaderB(d, dg=grid["dg"], de=grid["de"], seed=0, l2=l2)

            def cb(ep, mm, l2=l2, lr=lr):
                if ep in grid["epochs"]:
                    sel[(l2, lr, ep)] = b_exact(mm, va)
                    P("  B L%d l2 %g lr %g clip %s epoch %d: fold-4 exact %d/%d" % (L, l2, lr, clip, ep, sel[(l2, lr, ep)], len(va)))
            m.fit([x[:4] for x in tr], epochs=max(grid["epochs"]), stats=stats, on_epoch=cb, lr=lr, clip=clip)
    vals = list(sel.values())
    if len(set(vals)) == 1 and len(vals) > 1:
        raise SystemExit("REFUSE (fitb): every setting gives the same fold-4 exact match %d/%d: a flat grid (the f1 B signature)"
                         % (vals[0], len(va)))
    l2, lr, ep = max(sel, key=lambda k: (sel[k], k[0], -k[2]))
    n_va = len(va)
    del tr, va                                                          # <= 16G: never hold folds 1-3 and 1-4 at once
    full = rows_by_fold((1, 2, 3, 4))
    m = B.ReaderB(d, dg=grid["dg"], de=grid["de"], seed=0, l2=l2)
    m.fit([x[:4] for x in full], epochs=ep, stats=b_stats(full), lr=lr, clip=clip)
    np.savez(os.path.join(out, "READERB_L%d.npz" % L), **m.state())
    res = dict(layer=L, chosen=dict(l2=l2, lr=lr, clip=clip, epochs=ep), fold4_exact={"%g/%g/%d" % k: A.nt(v, n_va) for k, v in sel.items()},
               train_rows=len(full))
    json.dump(res, open(os.path.join(out, "READERB_L%d.json" % L), "w"), indent=1)
    P("  B L%d chosen l2 %g lr %g clip %s epochs %d" % (L, l2, lr, clip, ep))
    return res, m


# ---- NEW wrappers over in-memory rows (same predicates as defuse_fit.b_rows and fields as readerB bgate.py)
def _cap(data, cap, rng=None):
    """defuse_fit.b_rows' cap: a seeded subset, kept in order"""
    if cap is not None and len(data) > cap:
        sel = sorted((rng or np.random.default_rng(0)).choice(len(data), cap, replace=False).tolist())
        data = [data[k] for k in sel]
    return data


def b_data(asm, idx):
    """B's training tuples (q, h, valid, prefix tokens, row) for the rows idx of one assembled layer (A.assemble);
    rows whose gold program does not execute to the gold (exactly or within MathQA's rounding) or falls outside B's
    grammar are skipped, as in the project."""
    out = []
    for i in idx:
        r = asm["rows"][i]
        t, s = A.gold_tree(r)
        if t is None or s not in ("exec_exact", "exec_approx"):
            continue
        tk = B.prefix_tokens(t, r, 5)
        if tk is None:
            continue
        al = A.align_numerals(r); nums = A.numeral_values(r)
        valid = np.zeros(5, bool)
        for ni, rk in enumerate(al):
            if rk is not None and rk < 5 and nums[ni] is not None:
                valid[rk] = True
        out.append((asm["Xs"][i].astype(np.float16), asm["H"][i].astype(np.float16), valid, tk, r))
    return out


def make_rows_by_fold(asm, folds_of_rows):
    """a rows_by_fold(folds) callable for run_fitb. folds_of_rows[i] is row i's fold; fold 5 / 6 rows are refused"""
    fo = list(folds_of_rows)
    if any(f in (5, 6) for f in fo):
        raise SystemExit("REFUSE (fit_b): fold 5 / 6 rows passed to a fit; hold them out before assembling")

    def rows_by_fold(folds):
        return b_data(asm, [i for i, f in enumerate(fo) if f in folds])
    return rows_by_fold


def decode_record(models, asms, i, row, host, fold=None):
    """one row -> the DU-AG record (readerB bgate.py's fields). models / asms: {layer: ReaderB / assembled layer};
    host: dict(host1=<the host's own first number or None>, host1_none=<bool>, host1_right=<bool>)."""
    t, gs, tg = asms[24]["tg"][i]
    bprog, lp = {}, {}
    for L in LAYERS:
        q, h, valid, rv = B.row_inputs(asms[L], i)
        bprog[L], lp[L] = B.best_program(models[L], q, h, valid, rv, beam=B_GRID["beam"])
    du = A.du_ag(bprog, host["host1"], host["host1_none"], A.numeral_values(row))
    gold_v = Fraction(row["gold_frac"])
    right = (Fraction(du["answer"]) == gold_v) if du["fire"] else bool(host["host1_right"])
    canon = {str(L): (A.canon(bprog[L]) if bprog[L] is not None else None) for L in LAYERS}
    nleaves = {str(L): (len(A.leaves_of(bprog[L])) if bprog[L] is not None else None) for L in LAYERS}
    return dict(row_id=row["row_id"], fold=fold, n_numerals=len(row.get("numerals_written") or []),
                host1=host["host1"], host1_none=bool(host["host1_none"]), host1_right=bool(host["host1_right"]),
                gold_value=str(gold_v), decodable=tg["decodable"] if tg else False,
                gold_steps=tg["n_steps"] if tg else (A.n_steps(t) if t is not None else None),
                canon=canon, lp={str(L): (None if bprog[L] is None else round(float(lp[L]), 6)) for L in LAYERS},
                nleaves=nleaves, steps24=(A.n_steps(bprog[24]) if bprog[24] is not None else None),
                value24=(str(A.execute(bprog[24])) if bprog[24] is not None else None), fire=bool(du["fire"]),
                right=bool(right))
