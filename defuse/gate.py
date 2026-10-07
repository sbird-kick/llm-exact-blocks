"""gate.py -- the abstention gate and the R1 ledger of the def-use reader.

THE RULE (R1, the project's abstention criterion): never turn a host-right or a host-silent row into a wrong answer.
Concretely, on a set of rows:
  * HR = rows the host (the frozen LLM itself) answers right;
  * a FIRE is a row where the system replaces the host's answer by the executed program's value;
  * BROKEN = host right, fired, system wrong;   FIXED = host wrong, fired, system right;
  * R1 SUCCESS iff broken <= floor(1% of HR); FAILURE iff broken > 5% of HR; NEITHER in between.
  * The DU-AG base rule (reader_a.du_ag) never fires on a host-silent row (the host wrote no number) by construction.
Every quantity is reported as n/total (`ledger`, `fmt`).

THE GATE (the project's "M1" combiner; the same recipe gates reader B): on the base rule's fires, a small logistic
model scores "fixed" against "broken" from 13 features (the decoder's beam score per leaf at the middle layer, its
minimum over the three layers, two host-outcome state probes on H_slot / H_space, one-hots of the program's steps
and the prompt's numeral count, three interactions: `feats`). The model is CROSS-FITTED over folds 1-4 (fit on three
folds' fires, score the fourth), the cut is calibrated on those out-of-fold scores so that broken <= floor(tau x HR)
on folds 1-4 (`calibrate`), and the final model is fitted on all folds 1-4 fires. Fold 5 is scored ONCE with the
frozen cut. tau = 1.00% at 8B, 0.75% at 32B / 1.7B / 0.6B in the project (a pre-registered choice per size).

PORTED, NOT REWRITTEN: every function except `fit_gate` / `apply_gate` is a line-range copy of the project's pinned
analysis files (br_common.py, task4_rules2.py, task3_rules.py, readerB bgate_rules.py, firing_probe.py; md5s and
ranges in PROVENANCE.md). `fit_gate` re-assembles, in one function, the exact steps of bgate_rules.fit (cross-fit,
calibrate, final fit) so that it runs on a list of rows instead of the project's files.

A-side features `_spl` / `_minspl` come from reader A's decoder beam score per leaf (`margins`; reader_a.decode returns
the score and the leaf count). The B-side features (`prep_b`) come from reader B's own beam log-prob; the B gate is
the one wired into run.py.
"""
import collections, hashlib, json, math
import numpy as np

def nt(a, b):
    return "%d/%d" % (a, b)



def outcome(x):
    """for a fired row: fixed / broken / both wrong"""
    if x["host1_right"]:
        return "broken" if not x["right"] else "same"
    return "fixed" if x["right"] else "both wrong"


def ledger(rows, fire_fn=lambda x: True):
    HR = sum(bool(x["host1_right"]) for x in rows)
    fires = [x for x in rows if x["fire"] and fire_fn(x)]
    fr = sum(bool(x["right"]) for x in fires)
    broken = sum(bool(x["host1_right"]) and not x["right"] for x in fires)
    fixed = sum((not x["host1_right"]) and bool(x["right"]) for x in fires)
    r1 = "SUCCESS" if broken <= math.floor(0.01 * HR) else ("FAILURE" if broken > 0.05 * HR else "NEITHER")
    return dict(rows=len(rows), HR=HR, host_wrong=len(rows) - HR, fires=len(fires), fired_right=fr, broken=broken,
                fixed=fixed, net=fixed - broken, r1=r1, bar=math.floor(0.01 * HR))


def fmt(d):
    return "fires %s | broken %s | fixed %s | net %+d | R1 %s (bar %d)" % (
        nt(d["fires"], d["rows"]), nt(d["broken"], d["HR"]), nt(d["fixed"], d["host_wrong"]), d["net"], d["r1"], d["bar"])


def auroc(s, y):
    """P(score positive > score negative), ties 1/2"""
    pairs = sorted(zip(s, y))
    npos = sum(1 for _, v in pairs if v); nneg = len(pairs) - npos
    if not npos or not nneg:
        return None
    r = 0.0; i = 0; rank_sum = 0.0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1
        rank_sum += avg * sum(1 for k in range(i, j + 1) if pairs[k][1])
        i = j + 1
    return (rank_sum - npos * (npos + 1) / 2.0) / (npos * nneg)



TAUS = (("a", 0.005), ("b", 0.0075), ("c", 0.01))
LAM = 1.0


def prep_a(x):
    x["_steps"] = x["reader_steps"]; x["_num"] = x["n_numerals"]
    x["_spl"] = x["margins"]["24"]["score_per_leaf"] if x.get("margins") and x["margins"].get("24") else None


# ---------------------------------------------------------------- thresholds (folds 1-4 only)
def prep_m1(x):
    prep_a(x)
    m = x.get("margins") or {}
    v = [m[L]["score_per_leaf"] for L in ("20", "24", "28") if m.get(L)]
    x["_minspl"] = min(v) if v else None


def feats(x):
    st, nu, spl, mspl, sl, sp = x["_steps"], x["_num"], x["_spl"], x["_minspl"], x["_slot"], x["_space"]
    return [spl, mspl, sl, sp, float(st == 1), float(st == 2), float(st >= 3), float(nu == 2), float(nu == 3), float(nu >= 4),
            spl * float(st == 1), spl * float(st >= 3), sp * float(st == 1)]


def fit_logit(X, y):
    mu = X.mean(0); sd = X.std(0); sd[sd < 1e-9] = 1.0
    Z = np.hstack([np.ones((len(X), 1)), (X - mu) / sd])
    w = np.zeros(Z.shape[1]); R = LAM * np.eye(Z.shape[1]); R[0, 0] = 0
    for _ in range(50):
        p = 1 / (1 + np.exp(-Z @ w))
        g = Z.T @ (p - y) + R @ w
        H = (Z * (p * (1 - p))[:, None]).T @ Z + R
        step = np.linalg.solve(H, g); w -= step
        if np.max(np.abs(step)) < 1e-10:
            break
    return dict(mu=mu.tolist(), sd=sd.tolist(), w=w.tolist())


def score_logit(m, X):
    Z = (np.asarray(X) - np.asarray(m["mu"])) / np.asarray(m["sd"])
    return Z @ np.asarray(m["w"][1:]) + m["w"][0]


def calibrate(vals, outc, budget):
    """cut on a 1-D score (fire iff v >= cut): most fixed with broken <= budget; returns (cut, broken, fixed)"""
    o = np.argsort(-np.asarray(vals), kind="mergesort")
    v = np.asarray(vals)[o]; b = np.cumsum([outc[i] == "broken" for i in o]); f = np.cumsum([outc[i] == "fixed" for i in o])
    best = (math.inf, 0, 0)
    for j in range(len(v)):
        if j + 1 < len(v) and v[j + 1] == v[j]:
            continue                                                       # a cut includes every tie
        if b[j] <= budget and f[j] > best[2]:
            best = (float(v[j]), int(b[j]), int(f[j]))
    return best



def prep_b(x, pr):
    """the M1 fields of task4_rules2.feats, from B's decode"""
    x["_steps"] = x["steps24"] if x["steps24"] is not None else 0
    x["_num"] = x["n_numerals"]
    s = {L: x["lp"][L] / x["nleaves"][L] for L in ("20", "24", "28") if x["lp"][L] is not None and x["nleaves"][L]}
    x["_spl"] = s.get("24"); x["_minspl"] = min(s.values()) if s else None
    if pr is not None:
        p = pr[x["row_id"]]; x["_slot"], x["_space"] = p["slot"], p["space"]
    else:
        x["_slot"] = x["_space"] = 0.0


def feats_b(x, probes):
    f = feats(x)
    if probes:
        return f
    # no-probe variant: drop slot (2), space (3), space x st1 (12)
    return [v for i, v in enumerate(f) if i not in (2, 3, 12)]



def cross_scores(F, lab, use, groups, K):
    """K-way cross-fit scores (fit on the other parts' labelled rows, score the part)"""
    s = np.empty(len(F))
    for k in range(K):
        tr = use & (groups != k)
        m = fit_logit(F[tr], lab[tr])
        s[groups == k] = score_logit(m, F[groups == k])
    return s



# ---- the host-outcome state probe (firing_probe.py): ridge on H_slot / H_space, label host WRONG
ALPHAS = [1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0]
QS = (0.5, 0.75, 0.9)
CH = 2048


def auroc_mw(s, y):
    """P(score of a positive > score of a negative), ties 1/2 (Mann-Whitney with average ranks)"""
    s = np.asarray(s, np.float64); y = np.asarray(y, bool)
    npos, nneg = int(y.sum()), int((~y).sum())
    if npos == 0 or nneg == 0:
        return None
    o = np.argsort(s, kind="mergesort"); r = np.empty(len(s)); ss = s[o]
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and ss[j + 1] == ss[i]:
            j += 1
        r[o[i:j + 1]] = (i + j) / 2.0 + 1
        i = j + 1
    return float((r[y].sum() - npos * (npos + 1) / 2.0) / (npos * nneg))



def fit_arm(X, y, fold):
    n, dm = X.shape
    tr = np.isin(fold, [1, 2, 3, 4])
    idx_tr = np.where(tr)[0]
    # standardisation on folds 1-4
    s1 = np.zeros(dm); s2 = np.zeros(dm)
    for c0 in range(0, len(idx_tr), CH):
        Z = X[idx_tr[c0:c0 + CH]].astype(np.float64)
        s1 += Z.sum(0); s2 += (Z * Z).sum(0)
    mu = s1 / len(idx_tr); sd = np.sqrt(np.maximum(s2 / len(idx_tr) - mu * mu, 0))
    sd = np.maximum(sd, 1e-3 * np.median(sd[sd > 0]))

    def z(rows):
        return (X[rows].astype(np.float64) - mu) / sd
    S = {}
    for k in (1, 2, 3, 4):
        ik = np.where(fold == k)[0]
        nk = len(ik); s = np.zeros(dm); Gm = np.zeros((dm, dm)); t = np.zeros(dm); sy = 0.0
        for c0 in range(0, nk, CH):
            r = ik[c0:c0 + CH]; Z = z(r); yy = y[r].astype(np.float64)
            s += Z.sum(0); Gm += Z.T @ Z; t += Z.T @ yy; sy += yy.sum()
        S[k] = (nk, s, Gm, t, sy)

    def solve(keep):
        nn = sum(S[k][0] for k in keep); s = sum(S[k][1] for k in keep); Gm = sum(S[k][2] for k in keep)
        t = sum(S[k][3] for k in keep); sy = sum(S[k][4] for k in keep)
        m = s / nn; ybar = sy / nn
        Gc = Gm - nn * np.outer(m, m); tc = t - m * sy
        e, V = np.linalg.eigh(Gc)
        e = np.maximum(e, 0); Vt = V.T @ tc; me = float(e.mean())
        return {a: (V @ (Vt / (e + a * me)), m, ybar) for a in ALPHAS}

    def score(rows, W):
        w, m, yb = W
        out = np.empty(len(rows))
        for c0 in range(0, len(rows), CH):
            r = rows[c0:c0 + CH]
            out[c0:c0 + len(r)] = (z(r) - m) @ w + yb
        return out
    cv = collections.defaultdict(list); oof = {a: np.empty(n) for a in ALPHAS}
    for k in (1, 2, 3, 4):
        Wk = solve([j for j in (1, 2, 3, 4) if j != k])
        ik = np.where(fold == k)[0]
        for a in ALPHAS:
            sk = score(ik, Wk[a]); oof[a][ik] = sk
            cv[a].append(auroc_mw(sk, y[ik]))
        del Wk
    mean_cv = {a: float(np.mean(cv[a])) for a in ALPHAS}
    best = max(ALPHAS, key=lambda a: (round(mean_cv[a], 6), a))
    W = solve([1, 2, 3, 4])[best]
    rest = np.where(~tr)[0]
    sc = np.full(n, np.nan)
    sc[rest] = score(rest, W)
    sc[idx_tr] = oof[best][idx_tr]
    thr = {str(q): float(np.quantile(oof[best][idx_tr], q)) for q in QS}
    return dict(alpha=best, cv_auroc={str(a): v for a, v in mean_cv.items()}, cv_per_fold=[float(x) for x in cv[best]],
                thresholds_oof_folds1_4=thr, oof_auroc_folds1_4=auroc_mw(oof[best][idx_tr], y[idx_tr])), sc




# ---- NEW (not a line copy): bgate_rules.fit's per-size body, as one function over a list of rows
def _prep(x, side, probes):
    if side == "b":
        prep_b(x, probes)
    else:
        if probes is not None:
            p = probes[x["row_id"]]; x["_slot"], x["_space"] = p["slot"], p["space"]
        else:
            x["_slot"] = x["_space"] = 0.0
        prep_m1(x)


def _feats(x, side, probes):
    return feats_b(x, probes is not None) if side == "b" else feats(x)


def fit_gate(rows, tau, side="b", probes=None):
    """Fit the gate on OUT-OF-FOLD decodes of folds 1-4 ONLY (each row decoded by a reader that did not see its fold).

    rows   dicts with fold (1-4), fire (the ungated DU-AG decision), right (the executed program equals the gold),
           host1_right (the host's own answer equals the gold), and the decoder fields: for side "b" lp / nleaves /
           steps24 (reader B's beam log-prob, leaf count and steps per layer label "20" / "24" / "28") and n_numerals;
           for side "a" margins / reader_steps / n_numerals (from reader A's decoder).
    tau    the R1 budget fraction used to set the cut on folds 1-4 (the project: 0.01 at 8B, 0.0075 otherwise).
    probes optional {row_id: {"slot": s, "space": s}} host-outcome probe scores (fit_arm); None drops those three
           features (bgate_rules' "no-probe" variant).
    Steps exactly as bgate_rules.fit: cross-fit over the four folds -> OOF scores -> cut = calibrate(OOF, outcomes,
    floor(tau x HR)) -> final model on all folds-1-4 fires."""
    bad = sorted({x["fold"] for x in rows} - {1, 2, 3, 4})
    if bad:
        raise SystemExit("REFUSE (fit_gate): folds %s in the gate's fit rows; only folds 1-4 are ever fitted on" % bad)
    HR = sum(bool(x["host1_right"]) for x in rows)
    fires = [x for x in rows if x["fire"]]
    for x in fires:
        _prep(x, side, probes)
    F = np.array([_feats(x, side, probes) for x in fires], float); oc = [outcome(x) for x in fires]
    lab = np.array([1.0 if o == "fixed" else 0.0 for o in oc]); use = np.array([o in ("fixed", "broken") for o in oc])
    fo = np.array([x["fold"] - 1 for x in fires])
    thin = [k + 1 for k in range(4) if int((use & (fo != k)).sum()) < 2 or len(set(lab[use & (fo != k)].tolist())) < 2]
    if thin:
        raise SystemExit("REFUSE (fit_gate): too few fixed / broken fires to cross-fit (%d labelled fires of %d fires; the "
                         "training part for held-out fold(s) %s lacks one of the two outcomes). A gate needs the full "
                         "folds-1-4 run, not a smoke subset." % (int(use.sum()), len(fires), thin))
    oof = cross_scores(F, lab, use, fo, 4)
    cut, b, f = calibrate(oof.tolist(), oc, math.floor(tau * HR))
    model = fit_logit(F[use], lab[use])
    au = auroc(oof[use].tolist(), lab[use].astype(bool).tolist())
    return dict(side=side, tau=tau, probes=probes is not None, cut=cut, model=model, oof_rows=len(rows), oof_HR=HR,
                oof_fires=len(fires), oof_broken=b, oof_fixed=f, budget=math.floor(tau * HR), oof_auroc=au,
                oof_ungated=dict(broken=oc.count("broken"), fixed=oc.count("fixed")))


def apply_gate(rows, gate, probes=None):
    """the frozen gate on new rows: fire iff the base rule fires AND the final model's score >= the frozen cut.
    Returns the set of row ids that fire; score with `ledger(rows, lambda x: x["row_id"] in ids)`."""
    if gate["probes"] != (probes is not None):
        raise SystemExit("REFUSE (apply_gate): the gate was fitted %s probe scores; pass the same" % ("with" if gate["probes"] else "without"))
    ids = set()
    for x in rows:
        if not x["fire"]:
            continue
        _prep(x, gate["side"], probes)
        if float(score_logit(gate["model"], [_feats(x, gate["side"], probes)])[0]) >= gate["cut"]:
            ids.add(x["row_id"])
    return ids
