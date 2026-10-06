"""reader_b.py -- READER B of the def-use reader: a small prefix-order tree decoder (GTS style, Xie & Sun 2019)
over the host's hidden state at the cue (H_space) and at each numeral's last digit token (H_run_last). numpy only,
manual gradients (checked against finite differences in tests/test_defuse_cpu.py).

PORTED, NOT REWRITTEN: a line-range copy of the project's pinned `defuse_reader_b.py` at its F2 version
(md5 ececa84a8f107191f573d50c94cc398f: log-space set-target loss, optional gradient clip, loud refusal on any
non-finite value). Patches (PROVENANCE.md): the import of reader A. The project's own selftest (cluster-bound) is
not copied; tests/test_defuse_cpu.py replaces it.

MODEL, LOSS, DECODING: see the class docstring below and the original header, kept here:
  inputs  q = H_space[l] of the row, h_k = H_run_last[k, l] of each digit run (standardised on the training rows)
  tokens  + - x / PCT CONST(c) (20 vocabulary values) and POINTER(k) (attention over the row's runs)
  loss    teacher-forced cross-entropy in prefix order; a pointer target is the SET of runs holding the value
  decode  beam search in prefix order, at most 6 binary steps; the best program that executes is executed exactly
"""
import sys
sys.dont_write_bytecode = True
import hashlib, importlib.util, math, os, tempfile
from fractions import Fraction
import numpy as np

from . import reader_a as A                                              # ported: was defuse_reader

N_OPS = 4                                       # add sub mul div
TOK_PCT = 4
N_CONST = len(A.VOCAB)
N_FIXED = 5 + N_CONST                           # ops, PCT, constants; pointers follow
OPS = A.BOPS


# ------------------------------------------------------------------ gold program -> prefix tokens
def prefix_tokens(t, row, R):
    """[(kind, value)] in prefix order: ('op', i) | ('pct', None) | ('const', c) | ('ptr', frozenset(runs)), or None
    when the program is outside B's grammar (negation, percent on a subtree, a pointer with no run)"""
    al = A.align_numerals(row); nums = A.numeral_values(row)
    out = []

    def runs_of(v):
        return frozenset(al[i] for i, x in enumerate(nums) if x is not None and x == Fraction(v) and al[i] is not None and al[i] < R)

    def w(n):
        if n[0] == "b":
            out.append(("op", OPS.index(n[1]))); return w(n[2]) and w(n[3])
        if n[0] == "u":
            if n[1] != "pct" or n[2][0] not in ("n", "c"):
                return False
            out.append(("pct", None)); return w(n[2])
        if n[0] == "c":
            out.append(("const", n[1])); return True
        s = runs_of(n[2])
        if not s:
            return False
        out.append(("ptr", s)); return True
    return out if w(t) else None


def tokens_to_tree(toks, P_run_value):
    """prefix tokens -> program tree (pointers become numeral leaves through the run -> (numeral, value) map)"""
    it = iter(toks)

    def build():
        k, v = next(it)
        if k == "op":
            L = build(); R_ = build()
            return ("b", OPS[v], L, R_)
        if k == "pct":
            return ("u", "pct", build())
        if k == "const":
            return ("c", v, A.VOCAB[v])
        ni, val = P_run_value[v]
        return ("n", ni, val)
    return build()


# ------------------------------------------------------------------ the model
class ReaderB:
    def __init__(self, d, dg=32, de=8, seed=0, l2=1e-4):
        r = np.random.default_rng(seed)
        s = lambda *sh: r.normal(size=sh) * (1.0 / math.sqrt(sh[-1]))   # noqa: E731
        self.p = dict(Wq=s(dg, d), Wh=s(dg, d), Wr=s(dg, dg), br=np.zeros(dg), Wl=s(dg, dg + de), bl=np.zeros(dg),
                      Wrt=s(dg, dg + de + dg), brt=np.zeros(dg), U=s(N_FIXED, dg), c=np.zeros(N_FIXED), V=s(dg, dg),
                      Eop=s(5, de), Ec=s(N_CONST, dg))
        self.d, self.dg, self.de, self.l2 = d, dg, de, l2
        self.mu = np.zeros(d); self.sd = np.ones(d)
        self.m = {k: np.zeros_like(v) for k, v in self.p.items()}; self.v = {k: np.zeros_like(v) for k, v in self.p.items()}
        self.t = 0

    def standardise(self, Q, H, mask):
        allx = np.concatenate([Q, H[mask]], 0).astype(np.float64)
        self.mu = allx.mean(0); sd = allx.std(0); live = sd > 0
        floor = 1e-3 * float(np.median(sd[live])) if live.any() else 1.0
        self.sd = np.where(live, np.maximum(sd, floor), 1.0)

    def _proj(self, q, h):
        p = self.p
        qn = (q - self.mu) / self.sd; hn = (h - self.mu) / self.sd
        return qn, hn, p["Wq"] @ qn, hn @ p["Wh"].T

    def _logits(self, g, ht, valid):
        p = self.p
        lt = p["U"] @ g + p["c"]
        lp = ht @ (p["V"] @ g)
        lp = np.where(valid, lp, -1e9)
        return np.concatenate([lt, lp])

    # ---------------- one row: loss and gradients (teacher forcing)
    def row_grad(self, q, h, valid, toks, G=None):
        p = self.p
        qn, hn, qt, ht = self._proj(q, h)
        slots = []                                               # dicts: kind, parent, x, g, probs, target ids
        stack = [("root", None, None, None)]
        loss = 0.0
        for ti, (kind, val) in enumerate(toks):
            ent = stack.pop()
            if ent[0] == "root":
                x = qt; a = p["Wr"] @ x + p["br"]; sk = dict(kind="root", parent=None, x=x)
            elif ent[0] == "left":
                par, oi = ent[1], ent[2]
                x = np.concatenate([slots[par]["g"], p["Eop"][oi]]); a = p["Wl"] @ x + p["bl"]
                sk = dict(kind="left", parent=par, x=x, oi=oi)
            else:                                               # right child: summary of the completed left subtree
                par, oi, start = ent[1], ent[2], ent[3]
                leaves = [toks[j] for j in range(start, ti) if toks[j][0] in ("ptr", "const")]
                tl, lv = self._tL(leaves, ht)
                x = np.concatenate([slots[par]["g"], p["Eop"][oi], tl]); a = p["Wrt"] @ x + p["brt"]
                sk = dict(kind="right", parent=par, x=x, oi=oi, leaves=lv)
            g = np.tanh(a)
            lg = self._logits(g, ht, valid)
            if kind == "op": tgt = [val]
            elif kind == "pct": tgt = [TOK_PCT]
            elif kind == "const": tgt = [5 + val]
            else: tgt = [N_FIXED + k for k in sorted(val)]
            # F2 FIX: the set-target loss in LOG space. The F1 code formed pt = sum p[tgt] and later divided by it; when
            # the target's logit sat > ~745 below the max, pt underflowed to 0 and 0/0 = NaN entered the gradient
            # (fit f1_20261002: every B parameter NaN, the same program at every layer).
            mx = lg.max(); lse = mx + math.log(np.exp(lg - mx).sum())
            lt = lg[tgt]; mt = lt.max(); lse_t = mt + math.log(np.exp(lt - mt).sum())
            loss -= (lse_t - lse)
            pr = np.exp(lg - lse)
            wt = np.zeros_like(pr); wt[tgt] = np.exp(lt - lse_t)              # the target set's own softmax
            sk.update(g=g, probs=pr, w=wt)
            slots.append(sk)
            me = len(slots) - 1
            if kind == "op":
                stack.append(("right", me, val, ti + 1)); stack.append(("left", me, val, None))
            elif kind == "pct":
                stack.append(("left", me, TOK_PCT, None))
        if G is None:
            return loss
        # ---------------- backward, reverse prefix order (children before parents)
        dg = [np.zeros(self.dg) for _ in slots]
        dht = np.zeros_like(ht); dqt = np.zeros(self.dg)
        for i in range(len(slots) - 1, -1, -1):
            s = slots[i]; g = s["g"]
            dl = s["probs"] - s["w"]                                  # d(-log sum_tgt p) / d logits, no division
            dlt, dlp = dl[:N_FIXED], dl[N_FIXED:]
            G["U"] += np.outer(dlt, g); G["c"] += dlt
            Vg = p["V"] @ g
            G["V"] += np.outer(dlp @ ht, g)
            dht += np.outer(dlp, Vg)
            dg[i] += p["U"].T @ dlt + p["V"].T @ (ht.T @ dlp)
            da = dg[i] * (1 - g * g)
            if s["kind"] == "root":
                G["Wr"] += np.outer(da, s["x"]); G["br"] += da; dqt += p["Wr"].T @ da
            elif s["kind"] == "left":
                G["Wl"] += np.outer(da, s["x"]); G["bl"] += da
                dx = p["Wl"].T @ da
                dg[s["parent"]] += dx[:self.dg]; G["Eop"][s["oi"]] += dx[self.dg:]
            else:
                G["Wrt"] += np.outer(da, s["x"]); G["brt"] += da
                dx = p["Wrt"].T @ da
                dg[s["parent"]] += dx[:self.dg]; G["Eop"][s["oi"]] += dx[self.dg:self.dg + self.de]
                dtl = dx[self.dg + self.de:]
                lv = s["leaves"]
                for kind, idx in lv:
                    if kind == "ptr":
                        dht[idx] += dtl / len(lv)
                    else:
                        G["Ec"][idx] += dtl / len(lv)
        G["Wq"] += np.outer(dqt, qn)
        G["Wh"] += dht.T @ hn
        return loss

    def _tL(self, leaves, ht):
        vecs, lv = [], []
        for kind, v in leaves:
            if kind == "ptr":
                k = min(v) if isinstance(v, frozenset) else int(v); vecs.append(ht[k]); lv.append(("ptr", k))
            else:
                vecs.append(self.p["Ec"][v]); lv.append(("const", v))
        if not vecs:
            return np.zeros(self.dg), []
        return np.mean(vecs, 0), lv

    def step(self, G, n, lr=3e-3, b1=0.9, b2=0.999, clip=None):
        """Adam; F2: with clip, the batch gradient (incl. L2) is rescaled to global norm <= clip (F1 had no clip and
        diverged on real rows: losses rose 35.7 -> 83.0 -> 60.3 nats/row, job 26050)"""
        self.t += 1
        gs = {k: G[k] / n + self.l2 * self.p[k] for k in self.p}
        scale = 1.0
        if clip is not None:
            nrm = math.sqrt(sum(float((g * g).sum()) for g in gs.values()))
            if nrm > clip:
                scale = clip / nrm
        for k in self.p:
            g = gs[k] * scale
            self.m[k] = b1 * self.m[k] + (1 - b1) * g; self.v[k] = b2 * self.v[k] + (1 - b2) * g * g
            mh = self.m[k] / (1 - b1 ** self.t); vh = self.v[k] / (1 - b2 ** self.t)
            self.p[k] -= lr * mh / (np.sqrt(vh) + 1e-8)

    def fit(self, data, epochs=30, batch=32, lr=3e-3, seed=0, stats=None, on_epoch=None, clip=None):
        """data: list (or indexable) of (q [d], h [R, d], valid [R] bool, toks). stats=(mu, sd) skips the in-memory
        standardisation (the fit driver computes it on a sample, so 125k rows never become one float64 array);
        on_epoch(epoch, model) is called after every epoch (settings chosen on folds 1-4 at checkpoints)."""
        if stats is not None:
            self.mu, self.sd = np.asarray(stats[0], float), np.asarray(stats[1], float)
        else:
            Q = np.stack([x[0] for x in data]); H = np.stack([x[1] for x in data]); M = np.stack([x[2] for x in data])
            self.standardise(Q, H, M)
        r = np.random.default_rng(seed)
        hist = []
        for ep in range(epochs):
            order = r.permutation(len(data)); tot = 0.0
            for b0 in range(0, len(order), batch):
                G = {k: np.zeros_like(v) for k, v in self.p.items()}
                idx = order[b0:b0 + batch]
                for i in idx:
                    q, h, valid, toks = data[i]
                    tot += self.row_grad(np.asarray(q, np.float64), np.asarray(h, np.float64), valid, toks, G)
                if not math.isfinite(tot) or any(not np.isfinite(v).all() for v in G.values()):
                    raise SystemExit("REFUSE (reader B): non-finite loss or gradient at epoch %d, batch at %d" % (ep + 1, b0))
                self.step(G, len(idx), lr, clip=clip)
                if any(not np.isfinite(v).all() for v in self.p.values()):
                    raise SystemExit("REFUSE (reader B): non-finite parameters after epoch %d, batch at %d" % (ep + 1, b0))
            hist.append(tot / len(data))
            if on_epoch is not None:
                on_epoch(ep + 1, self)
        return hist

    def state(self):
        return dict({"p_" + k: v for k, v in self.p.items()}, mu=self.mu, sd=self.sd,
                    dims=np.array([self.d, self.dg, self.de]))

    @classmethod
    def from_state(cls, z):
        d, dg, de = [int(x) for x in z["dims"]]
        m = cls(d, dg=dg, de=de)
        for k in m.p:
            m.p[k] = np.array(z["p_" + k], np.float64)
        m.mu, m.sd = np.array(z["mu"], float), np.array(z["sd"], float)
        return m

    # ---------------- decoding
    def decode(self, q, h, valid, beam=16, max_ops=A.MAX_STEPS, max_tokens=13):
        p = self.p
        qn, hn, qt, ht = self._proj(q, h)
        g0 = np.tanh(p["Wr"] @ qt + p["br"])
        beams = [(0.0, [], [("goal", g0)], 0)]                  # logp, tokens, stack, n_ops
        done = []
        for _ in range(max_tokens):
            nxt = []
            for lp, toks, stack, nops in beams:
                st = list(stack); ent = st.pop()
                if ent[0] == "goal":
                    g = ent[1]
                else:                                            # ("right", g_parent, oi, start)
                    leaves = [t_ for t_ in toks[ent[3]:] if t_[0] in ("ptr", "const")]
                    tl, _ = self._tL(leaves, ht)
                    g = np.tanh(p["Wrt"] @ np.concatenate([ent[1], p["Eop"][ent[2]], tl]) + p["brt"])
                after_pct = bool(toks) and toks[-1][0] == "pct"
                lg = self._logits(g, ht, valid)
                lg = lg - lg.max(); lpr = lg - math.log(np.exp(lg).sum())
                for ti in np.argsort(-lpr)[:beam]:
                    if lpr[ti] < -40:
                        break
                    s2 = list(st)
                    if ti < N_OPS:
                        if nops >= max_ops or after_pct:
                            continue
                        tok = ("op", int(ti))
                        s2.append(("right", g, int(ti), len(toks) + 1))
                        s2.append(("goal", np.tanh(p["Wl"] @ np.concatenate([g, p["Eop"][ti]]) + p["bl"])))
                        n2 = nops + 1
                    elif ti == TOK_PCT:
                        if after_pct:
                            continue
                        tok = ("pct", None)
                        s2.append(("goal", np.tanh(p["Wl"] @ np.concatenate([g, p["Eop"][TOK_PCT]]) + p["bl"])))
                        n2 = nops
                    elif ti < N_FIXED:
                        tok = ("const", int(ti - 5)); n2 = nops
                    else:
                        tok = ("ptr", int(ti - N_FIXED)); n2 = nops
                    t2 = toks + [tok]
                    if not s2:
                        done.append((lp + lpr[ti], t2))
                    else:
                        nxt.append((lp + lpr[ti], t2, s2, n2))
            beams = sorted(nxt, key=lambda x: -x[0])[:beam]
            if not beams:
                break
        return sorted(done, key=lambda x: -x[0])


def best_program(model, q, h, valid, run_value, beam=16):
    for lp, toks in model.decode(q, h, valid, beam=beam):
        if any(k == "ptr" and v not in run_value for k, v in toks):
            continue
        t = tokens_to_tree(toks, run_value)
        if A.execute(t) is not None:
            return t, lp
    return None, -math.inf


def row_inputs(Asm, i):
    """B's inputs from reader A's assembled matrices: q = H_space (Xs), h = H_run_last (H), valid = pointer-able runs"""
    row = Asm["rows"][i]; R = Asm["R"]
    al = A.align_numerals(row); nums = A.numeral_values(row)
    valid = np.zeros(R, bool); rv = {}
    for ni, r in enumerate(al):
        if r is not None and r < R and nums[ni] is not None:
            valid[r] = True
            rv.setdefault(r, (ni, nums[ni]))
    return Asm["Xs"][i].astype(np.float64), Asm["H"][i].astype(np.float64), valid, rv


# ------------------------------------------------------------------ selftest
def _gradcheck(rng):
    d, R = 6, 3
    m = ReaderB(d, dg=4, de=3, seed=1, l2=0.0)
    q = rng.normal(size=d); h = rng.normal(size=(R, d)); valid = np.array([True, True, False])
    toks = [("op", 1), ("op", 0), ("ptr", frozenset([0])), ("const", 2), ("pct", None), ("ptr", frozenset([1, 0]))]
    G = {k: np.zeros_like(v) for k, v in m.p.items()}
    m.row_grad(q, h, valid, toks, G)
    worst = 0.0
    for k in m.p:
        flat = m.p[k].reshape(-1)
        for j in rng.choice(flat.size, min(6, flat.size), replace=False):
            old = flat[j]; eps = 1e-6
            flat[j] = old + eps; lp_ = m.row_grad(q, h, valid, toks)
            flat[j] = old - eps; lm_ = m.row_grad(q, h, valid, toks)
            flat[j] = old
            num = (lp_ - lm_) / (2 * eps); an = G[k].reshape(-1)[j]
            worst = max(worst, abs(num - an) / max(1e-6, abs(num) + abs(an)))
    return worst
