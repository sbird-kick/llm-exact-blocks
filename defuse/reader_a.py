"""reader_a.py -- READER A of the def-use reader: per-numeral heads over the host's hidden states, fitted by ridge,
plus the gold-program machinery (parse, execute exactly, per-numeral targets) and the DU-AG firing rule.

PORTED, NOT REWRITTEN. Every function below is copied line for line from the project's pinned `defuse_reader.py`
(md5 d2eb8b33672d3cb03c7f16c5dfede819); the line ranges and every textual patch are listed in defuse/PROVENANCE.md.
The patches only (a) swap the project's cluster path guard for `defuse/guard.py` (same function names, fold-5 /
fold-6 refusal kept), and (b) load the gold-equation parser from `defuse/inventory.py` instead of a cluster path.

The decoder block (`decode`, `_depth_score`, `a_identifiable`, `oracle_P`, `search_programs`, `answer_targets`,
`host_program_line`, `head_accuracy_by_position`) is the pinned file's lines 732-1063, copied unchanged (PROVENANCE.md);
tests/test_reader_a_decode.py checks it against outputs recorded from the pinned file on synthetic fixtures.

Program trees:  ('n', k, value) pointer to written numeral k | ('c', ci, value) constant VOCAB[ci] |
                ('u', 'pct'|'neg', child) | ('b', op, left, right) with op in add / sub / mul / div.
"""
import sys
sys.dont_write_bytecode = True
import argparse, collections, hashlib, importlib.util, itertools, json, math, os, re, tempfile, time, zlib
from fractions import Fraction
import numpy as np

from . import guard as G                                                 # ported: was eval_guard_defuse

LAYERS = [20, 24, 28]
LAMS = [1.0, 10.0, 100.0, 1000.0, 10000.0, 100000.0]                   # the frozen readers' grid
TEMPS = [0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0]
BOPS = ("add", "sub", "mul", "div")
PARENT_CLASSES = ("add", "sub", "mul", "div", "pct")
ROOT_CLASSES = ("add", "sub", "mul", "div", "pct", "leaf")
DEPTH_CLASSES = 5                                                       # 0 (a 0-step program), 1, 2, 3, >= 4
STEP_CLASSES = 7                                                        # 0 .. 5, 6+
MAX_STEPS = 6
MAX_USED = 6
# the pool's top-20 constant values (POOL_clean.json daa1142a, const_top20, in its order); 157/50 is the pi class
VOCAB20 = ["2", "1", "157/50", "4", "3", "100", "10", "5", "6", "12", "8", "7", "60", "20", "30", "9", "80", "1000",
           "100000", "15"]
VOCAB = [Fraction(v) for v in VOCAB20]
PI_INDEX = VOCAB20.index("157/50")
# ported: the project's PINS (cluster paths of other pinned modules) and HOST_LABEL (which machine dumped
# which tree) are not needed by any function in this package and are left out.
_MODS = {}


def md5f(p):
    return G.md5f(p)


def load_pinned(name, signed=None):
    """ported: the only pinned module reader A needs at fit time is the gold-equation parser, shipped as
    defuse/inventory.py (a line-range copy of the project's defuse_inventory.py a0a2b821). The other PINS entries
    belong to cluster-only scripts that are not part of this package."""
    if name in _MODS:
        return _MODS[name]
    if name != "defuse_inventory":
        raise SystemExit("REFUSE: %s is not shipped in this package (cluster-only)" % name)
    from . import inventory as m
    _MODS[name] = m
    return m


def nt(a, b):
    return "%d/%d" % (a, b)


# ================================================================== programs
# ('n', k, value)  pointer leaf to numeral k (written order)      ('c', ci, value)  constant leaf, vocab index ci
# ('u', 'pct'|'neg', child)                                        ('b', op, left, right)
def execute(t):
    k = t[0]
    if k in ("n", "c"):
        return Fraction(t[2])
    if k == "u":
        v = execute(t[2])
        if v is None:
            return None
        return v / 100 if t[1] == "pct" else -v
    a, b = execute(t[2]), execute(t[3])
    if a is None or b is None:
        return None
    op = t[1]
    if op == "add": return a + b
    if op == "sub": return a - b
    if op == "mul": return a * b
    if b == 0:
        return None
    return a / b


def canon(t):
    """canonical string up to commutativity of + and x; leaves by VALUE (any run holding the value counts)"""
    k = t[0]
    if k in ("n", "c"):
        return str(Fraction(t[2]))
    if k == "u":
        return "%s(%s)" % (t[1], canon(t[2]))
    a, b = canon(t[2]), canon(t[3])
    if t[1] in ("add", "mul") and b < a:
        a, b = b, a
    return "(%s %s %s)" % (a, {"add": "+", "sub": "-", "mul": "*", "div": "/"}[t[1]], b)


def n_steps(t):
    if t[0] in ("n", "c"):
        return 0
    if t[0] == "u":
        return n_steps(t[2])
    return 1 + n_steps(t[2]) + n_steps(t[3])


def leaves_of(t):
    if t[0] in ("n", "c"):
        return [t]
    if t[0] == "u":
        return leaves_of(t[2])
    return leaves_of(t[2]) + leaves_of(t[3])


# ================================================================== numerals -> digit runs
def align_numerals(row):
    """per written numeral, the index of its LAST digit run (a decimal / comma numeral spans several runs), or None"""
    runs = [str(x) for x in ((row.get("prov") or {}).get("run_values") or [])]
    nums = [str(x) for x in (row.get("numerals_written") or [])]
    out, pos = [None] * len(nums), 0
    for i, s in enumerate(nums):
        groups = re.findall(r"\d+", s)
        if not groups:
            continue
        L = len(groups)
        for p in range(pos, len(runs) - L + 1):
            if runs[p:p + L] == groups:
                out[i] = p + L - 1; pos = p + L; break
    return out


def numeral_values(row):
    out = []
    for x in row.get("numerals_written") or []:
        try:
            s = str(x).strip().replace(",", "")
            out.append(Fraction(s[1:] if s.startswith("+") else s))
        except (ValueError, ZeroDivisionError):
            out.append(None)
    return out


# ================================================================== gold program -> tree
class NotRepresentable(Exception):
    pass


def _resolve_inventory(row, parsed, inv):
    """defuse_inventory.analyse's steps 1-2 (statement chaining; MathQA n_k), keeping the numeral index of n_k"""
    fmt, prog = parsed["fmt"], parsed["prog"]
    nums = numeral_values(row)
    if fmt in ("asdiv", "gsm8k"):
        stated = parsed.get("stated") or []
        new = []
        for k, node in enumerate(prog):
            def sub(n, k=k):
                if n[0] == "leaf":
                    for j in range(k - 1, -1, -1):
                        if stated[j] is not None and stated[j] == n[1]:
                            return ("ref", j)
                    return n
                if n[0] == "op":
                    return ("op", n[1], [sub(c) for c in n[2]])
                return n
            new.append(sub(node))
        prog = new
    if fmt == "mathqa":
        new = []
        for node in prog:
            ch = []
            for c in node[2]:
                if c[0] == "nidx":
                    if c[1] >= len(nums) or nums[c[1]] is None:
                        raise NotRepresentable("mathqa_n_out_of_range")
                    ch.append(("leaf", nums[c[1]], "n%d" % c[1], c[1]))
                else:
                    ch.append(c)
            new.append(("op", node[1], ch))
        prog = new
    return prog


def _to_tree(n, prog, nums, depth=0):
    if depth > 64:
        raise NotRepresentable("too_deep")
    k = n[0]
    if k == "ref":
        return _to_tree(prog[n[1]], prog, nums, depth + 1)
    if k == "leaf":
        v, tag = n[1], str(n[2])
        if len(n) > 3 and n[3] is not None:                               # MathQA n_k: numeral k by index
            return ("n", int(n[3]), nums[int(n[3])])
        if tag == "const_pi":
            return ("c", PI_INDEX, v)
        hits = [i for i, x in enumerate(nums) if x is not None and x == v]
        if hits:
            return ("n", hits[0], v)
        if v in VOCAB:
            return ("c", VOCAB.index(v), v)
        raise NotRepresentable("const_outside_vocab")
    if k == "op":
        name, ch = n[1], n[2]
        if name in BOPS and len(ch) == 2:
            return ("b", name, _to_tree(ch[0], prog, nums, depth + 1), _to_tree(ch[1], prog, nums, depth + 1))
        if name in ("pct", "neg") and len(ch) == 1:
            return ("u", name, _to_tree(ch[0], prog, nums, depth + 1))
        raise NotRepresentable("op_outside_grammar:%s" % name)
    raise NotRepresentable("node:%s" % k)


def gold_tree(row, inv=None):
    """(tree or None, status). status: exec_exact | exec_approx | exec_mismatch | no_equation | unsupported:* |
    not_representable:*"""
    inv = inv or load_pinned("defuse_inventory")
    try:
        parsed = inv.parse_row(row)
    except inv.Unsupported as e:
        return None, ("no_equation" if str(e) == "no_equation" else "unsupported:" + str(e).split(":")[0])
    except (ValueError, ZeroDivisionError, RecursionError, TypeError, OverflowError):
        return None, "unsupported:parse_error"
    nums = numeral_values(row)
    try:
        prog = _resolve_inventory(row, parsed, inv)
        t = _to_tree(prog[-1], prog, nums)
    except NotRepresentable as e:
        return None, "not_representable:" + str(e)
    except (ValueError, ZeroDivisionError, RecursionError, TypeError, OverflowError):
        return None, "unsupported:parse_error"
    v = execute(t)
    gold = Fraction(row["gold_frac"])
    if v is None:
        return t, "exec_mismatch"
    if v == gold:
        return t, "exec_exact"
    if abs(v - gold) <= Fraction(5, 1000) * max(1, abs(gold)):
        return t, "exec_approx"
    return t, "exec_mismatch"


# ================================================================== targets
def vocab_fallback(t, row, R):
    """F1 fix 4a: walking the leaves left to right (the order targets_from_tree assigns runs), a pointer leaf whose
    value has no free run left becomes a CONSTANT leaf when the value is in the 20-value vocabulary (e.g. the 1 of
    (1 - 1/3) where '1' is also written once). Reuse of a value outside the vocabulary is left as is (not decodable
    by A; reader B can point at a run twice)."""
    al = align_numerals(row); nums = numeral_values(row)
    free = collections.Counter()
    for i, x in enumerate(nums):
        if x is not None and al[i] is not None and al[i] < R:
            free[x] += 1

    def w(n):
        if n[0] == "b":
            return ("b", n[1], w(n[2]), w(n[3]))
        if n[0] == "u":
            return ("u", n[1], w(n[2]))
        if n[0] == "n":
            v = Fraction(n[2])
            if free[v] > 0:
                free[v] -= 1; return n
            if v in VOCAB:
                return ("c", VOCAB.index(v), v)
        return n
    return w(t)


def targets_from_tree(t, row, R, fallback=True):
    """per-run targets (-1 = masked) + row targets + sibling pairs. A pointer leaf goes to the last run of its numeral;
    a value written twice goes to the first not-yet-used run holding it (the executed value is the same). With
    fallback (F1 fix 4a), a reused vocabulary value becomes a constant leaf first."""
    if fallback:
        t = vocab_fallback(t, row, R)
    al = align_numerals(row)
    nums = numeral_values(row)
    n_runs = int((row.get("prov") or {}).get("n_runs") or 0)
    leafable = sorted({r for r in al if r is not None and r < R})
    T = dict(used=np.full(R, -1, np.int8), parent=np.full(R, -1, np.int8), side=np.full(R, -1, np.int8),
             depth=np.full(R, -1, np.int8), cpartner=np.full(R, -1, np.int8), ambig=np.zeros(R, bool))
    for r in leafable:
        T["used"][r] = 0
    info = dict(decodable=True, why=None)
    taken = set()
    sib_runs = set()

    def run_for(leaf):
        k = leaf[1]
        cands = [al[i] for i, x in enumerate(nums) if x is not None and x == Fraction(leaf[2]) and al[i] is not None and al[i] < R]
        first = al[k] if k < len(al) else None
        if first is not None and first < R and first not in taken:
            return first, len(set(cands)) > 1, None
        for c in cands:
            if c not in taken:
                return c, True, None
        return None, False, ("numeral_reused" if (first is not None and first in taken) else "pointer_without_run")

    def walk(n, depth, parent_op, side, sibling):
        """returns the run of n if n is a pointer leaf (possibly percent-wrapped), else None. side = the numeral's side
        under its NEAREST - or / ancestor (None if it has none): where the parent itself is - or /, this is the
        prereg's SIDE; it also orders a - or / whose two children are both subtrees. No object ids are used: an
        inlined reused subtree (MathQA #k) is the same tuple object twice."""
        if n[0] == "u":
            if n[1] == "pct" and n[2][0] in ("n", "c"):
                return walk(n[2], depth, "pct", side, sibling)
            if n[1] == "neg" or n[2][0] not in ("n", "c"):
                info["decodable"] = False; info["why"] = info["why"] or "unary_not_on_a_leaf_or_neg"
            walk(n[2], depth, parent_op, side, sibling)
            return None
        if n[0] == "b":
            L, Rr = n[2], n[3]
            nc = n[1] in ("sub", "div")
            rl = walk(L, depth + 1, n[1], 0 if nc else side, Rr)
            rr = walk(Rr, depth + 1, n[1], 1 if nc else side, L)
            if rl is not None and rr is not None:
                sib_runs.add((min(rl, rr), max(rl, rr)))
            return None
        if n[0] == "c":
            return None
        r, amb, why = run_for(n)
        if r is None:
            info["decodable"] = False; info["why"] = info["why"] or why
            return None
        taken.add(r)
        T["used"][r] = 1; T["ambig"][r] = amb
        T["parent"][r] = PARENT_CLASSES.index(parent_op) if parent_op else -1
        T["side"][r] = side if side is not None else -1
        T["depth"][r] = min(depth, DEPTH_CLASSES - 1)
        sc = _leaf_core(sibling) if sibling is not None else None
        T["cpartner"][r] = (1 + sc[1]) if (sc is not None and sc[0] == "c") else 0
        return r

    walk(t, 0, None, None, None)
    st = n_steps(t)
    if st > MAX_STEPS:
        info["decodable"] = False; info["why"] = info["why"] or "over_6_steps"
    used_runs = [r for r in range(R) if T["used"][r] == 1]
    if len(used_runs) > MAX_USED:
        info["decodable"] = False; info["why"] = info["why"] or "over_6_numerals"
    sib = {}
    for a, b in itertools.combinations(used_runs, 2):
        sib[(a, b)] = int((a, b) in sib_runs)
    cc = np.zeros(len(VOCAB), np.int8)
    for lf in leaves_of(t):
        if lf[0] == "c":
            cc[lf[1]] = min(2, cc[lf[1]] + 1)
    root = t
    while root[0] == "u" and root[1] == "neg":
        root = root[2]
    rootc = "leaf" if root[0] in ("n", "c") else (root[1] if root[0] == "b" else "pct")
    return dict(per_run=T, pairs=sib, steps=min(st, STEP_CLASSES - 1), root=ROOT_CLASSES.index(rootc), consts=cc,
                n_runs=n_runs, leafable=leafable, decodable=info["decodable"], why=info["why"], n_steps=st)


def _leaf_core(n):
    while n is not None and n[0] == "u" and n[1] == "pct":
        n = n[2]
    return n if n is not None and n[0] in ("n", "c") else None


# ================================================================== dumps and features
def load_dump(path):
    """a dump through the guard: .npz fixture (selftest) or the pinned dumper's .pt (torch, mmap)"""
    G.check_path(path)
    if path.endswith(".npz"):
        Z = np.load(path, allow_pickle=False)
        return dict(meta=json.loads(str(Z["meta_json"])), layers=[int(x) for x in Z["layers"]],
                    space_layers=[int(x) for x in Z["space_layers"]], H_run_last=Z["H_run_last"], A_space=Z["A_space"],
                    H_space=Z["H_space"], run_mask=Z["run_mask"])
    import torch
    try:
        return torch.load(path, map_location="cpu", mmap=True, weights_only=False)
    except TypeError:
        return torch.load(path, map_location="cpu")


def _np(t):
    if isinstance(t, np.ndarray):
        return t.astype(np.float32)
    return t.float().numpy()


def load_rows(path):
    G.check_path(path)
    out = []
    for line in open(path, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            G.check_row_id(r["row_id"], r)
            out.append(r)
    return out


def join_dump_rows(st, rows, idx=None):
    """the dump meta must equal the row file row for row (wild_read's rule); returns the row list in dump order"""
    meta = st["meta"]
    if len(meta) != len(rows):
        raise SystemExit("REFUSE: dump rows %d != row file rows %d" % (len(meta), len(rows)))
    idx = range(len(meta)) if idx is None else idx
    out = []
    for j in idx:
        m, r = meta[j], rows[j]
        if m["row_id"] != r["row_id"]:
            raise SystemExit("REFUSE: dump row %d is %s, row file has %s" % (j, m["row_id"], r["row_id"]))
        G.check_row_id(m["row_id"], r)
        rv = [str(x) for x in ((r.get("prov") or {}).get("run_values") or [])]
        mv = [str(x).strip() for x in (m.get("run_values") or [])]
        if rv[:len(mv)] != mv or int(m.get("n_runs", len(mv))) != len(mv):
            raise SystemExit("REFUSE: %s run values %s != row prov %s" % (m["row_id"], mv, rv))
        out.append(r)
    return out


def layer_index(st, L, space=False):
    ls = list(st["space_layers"] if space else st["layers"])
    if L not in ls:
        raise SystemExit("REFUSE: layer %d not in the dump's %s %s" % (L, "space_layers" if space else "layers", ls))
    return ls.index(L)


def _take(arr, J):
    """rows J of a numpy array or a (mmap'd) torch tensor; a contiguous J is a slice (reads only those pages)"""
    J = np.asarray(J, dtype=np.int64)
    if len(J) and np.all(np.diff(J) == 1):
        return arr[int(J[0]):int(J[-1]) + 1]
    if isinstance(arr, np.ndarray):
        return arr[J]
    import torch
    return arr[torch.as_tensor(J)]


def run_features(st, J, L):
    """[n, R, D]: H_run_last[k, L] + H_space[L] + A_space[k] flattened"""
    li, si = layer_index(st, L), layer_index(st, L, True)
    HL = _np(_take(st["H_run_last"], J)[:, :, li])
    HS = _np(_take(st["H_space"], J)[:, si])
    A = _np(_take(st["A_space"], J))
    n, R, d = HL.shape
    return np.concatenate([HL, np.repeat(HS[:, None, :], R, 1), A.reshape(n, R, -1)], axis=2)


def space_features(st, J, L):
    return _np(_take(st["H_space"], J)[:, layer_index(st, L, True)])


def run_states(st, J, L):
    return _np(_take(st["H_run_last"], J)[:, :, layer_index(st, L)])


def pair_features(h, pairs):
    """[h_k * h_j, h_k + h_j] for each (row, k, j): symmetric in k, j"""
    a = np.stack([h[i, k] for i, k, _ in pairs]); b = np.stack([h[i, j] for i, _, j in pairs])
    return np.concatenate([a * b, a + b], axis=1)


# ---------------------------------------------------------------- A-text (text-only twin)
TEXT_DIM = 4096


def _masked_text(row):
    q = (row.get("question") or row.get("text") or "").lower()
    return q


def text_run_features(row, R, dim=TEXT_DIM, win=12):
    """[R, dim+4]: hashed char 1-3-grams of the numbers-masked text in +-win chars of each run, + position features"""
    q = _masked_text(row)
    spans = [(m.start(), m.end()) for m in re.finditer(r"\d+", q)]
    masked = re.sub(r"\d", "#", q)
    n_runs = int((row.get("prov") or {}).get("n_runs") or 0)
    X = np.zeros((R, dim + 4), np.float32)
    for k in range(min(R, n_runs, len(spans))):
        s, e = spans[k]
        ctx = masked[max(0, s - win):s] + "|" + masked[e:e + win]
        for n in (1, 2, 3):
            for i in range(len(ctx) - n + 1):
                X[k, zlib.crc32(("%d:" % n + ctx[i:i + n]).encode("utf-8")) % dim] += 1.0
        X[k, dim] = k; X[k, dim + 1] = k / max(1, n_runs - 1); X[k, dim + 2] = float(k == 0); X[k, dim + 3] = float(k == n_runs - 1)
    return X


def text_row_features(row, dim=TEXT_DIM):
    masked = re.sub(r"\d+", "#", _masked_text(row))
    X = np.zeros(dim, np.float32)
    for n in (1, 2, 3):
        for i in range(len(masked) - n + 1):
            X[zlib.crc32(("%d:" % n + masked[i:i + n]).encode("utf-8")) % dim] += 1.0
    return X


def position_class(k, n_runs):
    if n_runs <= 1:
        return "only"
    return "first" if k == 0 else ("last" if k == n_runs - 1 else "middle")


# ================================================================== heads
class Ridge:
    """one-hot ridge with intercept (centred), standardised features (sd floor 1e-3 x median), primal or dual solve"""

    def __init__(self, X):
        X = np.asarray(X, np.float64)
        self.mu = X.mean(0); sd = X.std(0); live = sd > 0
        floor = 1e-3 * float(np.median(sd[live])) if live.any() else 1.0
        self.sd = np.where(live, np.maximum(sd, floor), 1.0)
        Z = (X - self.mu) / self.sd
        self.n, self.d = Z.shape
        self.dual = self.n < self.d
        if self.dual:
            e, U = np.linalg.eigh(Z @ Z.T); self.Z = Z
        else:
            e, U = np.linalg.eigh(Z.T @ Z); self.Zt = Z.T
        self.e = np.maximum(e, 0.0); self.U = U

    def solve(self, Y, lam):
        Y = np.asarray(Y, np.float64); ym = Y.mean(0); Yc = Y - ym
        if self.dual:
            alpha = self.U @ ((self.U.T @ Yc) / (self.e + lam)[:, None])
            W = self.Z.T @ alpha
        else:
            W = self.U @ ((self.U.T @ (self.Zt @ Yc)) / (self.e + lam)[:, None])
        return W, ym

    def scores(self, X, W, ym):
        return ((np.asarray(X, np.float64) - self.mu) / self.sd) @ W + ym


def _onehot(y, C):
    Y = np.zeros((len(y), C)); Y[np.arange(len(y)), y] = 1.0
    return Y


def _logsoftmax(S):
    S = S - S.max(1, keepdims=True)
    return S - np.log(np.exp(S).sum(1, keepdims=True))


class Head:
    """a ridge head over C classes; lambda by grouped CV on `groups` (ties -> larger lambda); temperature on the same
    CV predictions (max log-likelihood); final fit on every training row"""

    def __init__(self, name, C):
        self.name, self.C = name, C

    def fit(self, X, y, groups, lams=LAMS, weights=None):
        y = np.asarray(y, int); groups = np.asarray(groups)
        Y = _onehot(y, self.C)
        if weights is not None:                                          # ties split / per-source weights (D12)
            Y = Y * np.asarray(weights, float)[:, None]
        gs = sorted(set(groups.tolist()))
        cvS = {lam: np.zeros((len(y), self.C)) for lam in lams}
        if len(gs) >= 2:
            for g in gs:
                tr, te = groups != g, groups == g
                if tr.sum() < 2 or te.sum() == 0:
                    continue
                F = Ridge(X[tr])
                for lam in lams:
                    W, ym = F.solve(Y[tr], lam); cvS[lam][te] = F.scores(X[te], W, ym)
            acc = {lam: float((cvS[lam].argmax(1) == y).mean()) for lam in lams}
            self.lam = max(lams, key=lambda l: (round(acc[l], 9), l))
            S = cvS[self.lam]
            self.T = max(TEMPS, key=lambda T: float(_logsoftmax(S / T)[np.arange(len(y)), y].sum()))
            self.cv_acc = acc
        else:
            self.lam, self.T, self.cv_acc = lams[len(lams) // 2], 1.0, {}
        self.F = Ridge(X)
        self.W, self.ym = self.F.solve(Y, self.lam)
        return self

    def logp(self, X):
        return _logsoftmax(self.F.scores(X, self.W, self.ym) / self.T)


# ================================================================== reader A: assemble, fit, predict
def assemble(rows, st, J, L, R, text=False):
    """per-run, pair and row matrices + targets for the rows (dump indices J); rows without a usable gold tree get
    no targets but still get features. text=True gives the A-text twin's features instead of the dumped states."""
    if text:
        Xr = np.stack([text_run_features(r, R) for r in rows]); Xs = np.stack([text_row_features(r) for r in rows])
        H = Xr
    else:
        Xr = run_features(st, J, L); Xs = space_features(st, J, L); H = run_states(st, J, L)
    tg = []
    for r in rows:
        t, status = gold_tree(r)
        tg.append((t, status, targets_from_tree(t, r, R) if t is not None and status == "exec_exact" else None))
    return dict(Xr=Xr, Xs=Xs, H=H, tg=tg, rows=rows, R=R, text=text)


def head_samples(A, idx):
    """the training samples of every head over rows idx"""
    S = collections.defaultdict(lambda: ([], [], []))                    # head -> (row-run keys, y, row index)
    for i in idx:
        tg = A["tg"][i][2]
        if tg is None:
            continue
        T = tg["per_run"]
        for k in tg["leafable"]:
            S["used"][0].append((i, k)); S["used"][1].append(int(T["used"][k])); S["used"][2].append(i)
            if T["used"][k] == 1:
                for h in ("parent", "depth", "cpartner"):
                    if T[h][k] >= 0:
                        S[h][0].append((i, k)); S[h][1].append(int(T[h][k])); S[h][2].append(i)
                if T["side"][k] >= 0:
                    S["side"][0].append((i, k)); S["side"][1].append(int(T["side"][k])); S["side"][2].append(i)
        for (a, b), s in tg["pairs"].items():
            S["sib"][0].append((i, a, b)); S["sib"][1].append(s); S["sib"][2].append(i)
        for h in ("steps", "root"):
            S[h][0].append(i); S[h][1].append(int(tg[h])); S[h][2].append(i)
        for c in range(len(VOCAB)):
            S["const%d" % c][0].append(i); S["const%d" % c][1].append(int(tg["consts"][c])); S["const%d" % c][2].append(i)
    return S


HEAD_C = dict(used=2, parent=len(PARENT_CLASSES), side=2, depth=DEPTH_CLASSES, cpartner=1 + len(VOCAB), sib=2,
              steps=STEP_CLASSES, root=len(ROOT_CLASSES))


def _X_for(A, head, keys):
    if head == "sib":
        return pair_features(A["H"], keys)
    if head in ("steps", "root") or head.startswith("const"):
        return A["Xs"][np.asarray(keys)]
    return np.stack([A["Xr"][i, k] for i, k in keys])


def fit_reader(A, idx, fold_of_row, lams=LAMS, side_override=None):
    """fit every head on rows idx; lambda by CV over the training rows' folds. side_override: a fitted SIDE head
    (BW) replacing A's own."""
    S = head_samples(A, idx)
    heads = {}
    for h, (keys, y, rws) in S.items():
        C = HEAD_C.get(h, 3)
        y = np.asarray(y)
        if len(y) == 0:
            continue
        if len(set(y.tolist())) < 2:                                    # a constant target: a degenerate head
            heads[h] = ("const", int(y[0]), C); continue
        heads[h] = Head(h, C).fit(_X_for(A, h, keys), y, [fold_of_row[i] for i in rws], lams)
    if side_override is not None:
        heads["side"] = side_override
    return heads


def _hlogp(head, X):
    if isinstance(head, tuple):                                          # ("const", class, C)
        lp = np.full((len(X), head[2]), -30.0); lp[:, head[1]] = 0.0
        return lp
    return head.logp(X)


def predict_row(heads, A, i):
    """every head's log-probabilities for row i (the decoder's input)"""
    tg = A["tg"][i][2]
    row = A["rows"][i]
    al = align_numerals(row)
    leafable = sorted({r for r in al if r is not None and r < A["R"]})
    P = dict(leafable=leafable, run={})
    if leafable:
        Xk = A["Xr"][i, leafable]
        lp = {h: _hlogp(heads[h], Xk) for h in ("used", "parent", "side", "depth", "cpartner") if h in heads}
        for j, k in enumerate(leafable):
            P["run"][k] = {h: lp[h][j] for h in lp}
    P["sib"] = {}
    if "sib" in heads and len(leafable) >= 2:
        prs = [(i, a, b) for a, b in itertools.combinations(leafable, 2)]
        lp = _hlogp(heads["sib"], pair_features(A["H"], prs))
        for (_, a, b), v in zip(prs, lp):
            P["sib"][(a, b)] = v
    xs = A["Xs"][i:i + 1]
    P["steps"] = _hlogp(heads["steps"], xs)[0] if "steps" in heads else np.zeros(STEP_CLASSES)
    P["root"] = _hlogp(heads["root"], xs)[0] if "root" in heads else np.zeros(len(ROOT_CLASSES))
    P["consts"] = [int(np.argmax(_hlogp(heads["const%d" % c], xs)[0])) if ("const%d" % c) in heads else 0
                   for c in range(len(VOCAB))]
    P["run_value"] = {}
    nums = numeral_values(row)
    for ni, r in enumerate(al):
        if r is not None and r < A["R"] and r not in P["run_value"] and nums[ni] is not None:
            P["run_value"][r] = (ni, nums[ni])
    del tg
    return P


# ================================================================== decoder
BEAM = 64


def decode(P, beam=BEAM, used_thr=0.5):
    """bottom-up beam search; returns (tree or None, score, info). Leaves: numerals with P(USED) > used_thr (top 6
    by P(USED)) + the row head's constant multiset; total leaves <= 7 (constants dropped first, vocab order)."""
    run = P["run"]
    cand = [(math.exp(run[k]["used"][1]), k) for k in run if "used" in run[k] and k in P["run_value"]]
    num_leaves = [k for p, k in sorted(cand, key=lambda x: (-x[0], x[1])) if p > used_thr][:MAX_USED]
    consts = [c for c in range(len(VOCAB)) for _ in range(P["consts"][c])]
    consts = consts[:max(0, MAX_STEPS + 1 - len(num_leaves))]
    if not num_leaves and not consts:
        return None, -math.inf, dict(why="no_leaves", n_leaves=0)
    items, base = [], 0.0
    for k in num_leaves:
        ni, v = P["run_value"][k]
        lf = ("n", ni, v)
        pr = run[k].get("parent")
        if pr is not None and int(np.argmax(pr)) == PARENT_CLASSES.index("pct"):
            items.append((("u", "pct", lf), frozenset([k]), frozenset([k]))); base += pr[PARENT_CLASSES.index("pct")]
        else:
            items.append((lf, frozenset([k]), frozenset([k])))
        base += run[k]["used"][1]
    for k in run:
        if k not in num_leaves and "used" in run[k]:
            base += run[k]["used"][0]
    for c in consts:
        items.append((("c", c, VOCAB[c]), frozenset(), frozenset()))
    for (a, b), lp in P["sib"].items():
        if a in num_leaves and b in num_leaves:
            base += lp[0]
    nL = len(items)
    base += P["steps"][min(nL - 1, STEP_CLASSES - 1)]

    def run_of(t):
        return next(iter(t[1])) if (t[0][0] in ("n",) or (t[0][0] == "u" and t[0][2][0] == "n")) and len(t[1]) == 1 else None

    def local(left, right, op):
        s = 0.0
        for me, other, side in ((left, right, 0), (right, left, 1)):
            k = run_of(me)
            if k is None:
                continue
            is_pct = me[0][0] == "u"
            if not is_pct and run[k].get("parent") is not None:
                s += run[k]["parent"][PARENT_CLASSES.index(op)]
            if run[k].get("cpartner") is not None:
                oc = _leaf_core(other[0])
                s += run[k]["cpartner"][(1 + oc[1]) if (oc is not None and oc[0] == "c") else 0]
        if op in ("sub", "div"):                                           # SIDE: every run exposed on each side
            for me, side in ((left, 0), (right, 1)):
                for k in me[2]:
                    if run[k].get("side") is not None:
                        s += run[k]["side"][side]
        a, b = run_of(left), run_of(right)
        if a is not None and b is not None:
            key = (min(a, b), max(a, b))
            if key in P["sib"]:
                s += P["sib"][key][1] - P["sib"][key][0]
        return s

    if nL == 1:
        t = items[0][0]
        return t, base + P["root"][ROOT_CLASSES.index("pct" if t[0] == "u" else "leaf")] + _depth_score(t, run, P), \
            dict(n_leaves=1, states=1)
    states = [(0.0, tuple(items))]
    n_states = 0
    for _ in range(nL - 1):
        nxt = {}
        for sc, its in states:
            for i, j in itertools.combinations(range(len(its)), 2):
                rest = tuple(x for m, x in enumerate(its) if m not in (i, j))
                for op in BOPS:
                    orders = [(its[i], its[j])] if op in ("add", "mul") else [(its[i], its[j]), (its[j], its[i])]
                    for L_, R_ in orders:
                        if L_[0][0] == "c" and R_[0][0] == "c":
                            continue                                       # no constant-only step
                        node = (("b", op, L_[0], R_[0]), L_[1] | R_[1],
                                frozenset() if op in ("sub", "div") else (L_[2] | R_[2]))
                        new = tuple(sorted(rest + (node,), key=lambda x: canon(x[0])))
                        key = tuple(canon(x[0]) for x in new)
                        s2 = sc + local(L_, R_, op)
                        n_states += 1
                        if key not in nxt or nxt[key][0] < s2:
                            nxt[key] = (s2, new)
        states = sorted(nxt.values(), key=lambda x: -x[0])[:beam]
    best, best_s = None, -math.inf
    for sc, its in states:
        t = its[0][0]
        if execute(t) is None:
            continue
        s = base + sc + P["root"][ROOT_CLASSES.index(t[1])] + _depth_score(t, run, P)
        if s > best_s:
            best, best_s = t, s
    return best, best_s, dict(n_leaves=nL, states=n_states)


def _depth_score(t, run, P):
    s = 0.0

    def w(n, d):
        nonlocal s
        if n[0] == "b":
            w(n[2], d + 1); w(n[3], d + 1); return
        if n[0] == "u":
            w(n[2], d); return
        if n[0] == "n":
            for k, (ni, v) in P["run_value"].items():
                if ni == n[1] and k in run and run[k].get("depth") is not None:
                    s += run[k]["depth"][min(d, DEPTH_CLASSES - 1)]; break
    w(t, 0)
    return s


def a_identifiable(t):
    """True iff reader A's head set can pin this program: every non-root step has a numeral leaf as a direct child
    (its PARENT-OP names the step's operator) and every - or / step has a numeral exposed on one side (its SIDE orders
    the step). A step joining two subtrees, or a subtree and a constant, has no per-numeral signal for its operator:
    the prereg's own reason for reader B (s4.2)."""
    def core_num(n):
        c = _leaf_core(n)
        return c is not None and c[0] == "n"

    def exposed(n):
        if n[0] == "u":
            return exposed(n[2])
        if n[0] == "n":
            return True
        if n[0] == "c":
            return False
        return n[1] in ("add", "mul") and (exposed(n[2]) or exposed(n[3]))

    def ok(n, root):
        if n[0] == "u":
            return ok(n[2], root)
        if n[0] != "b":
            return True
        if not root and not (core_num(n[2]) or core_num(n[3])):
            return False
        if n[1] in ("sub", "div") and not (exposed(n[2]) or exposed(n[3])):
            return False
        return ok(n[2], False) and ok(n[3], False)
    return ok(t, True)


def oracle_P(tg, row, R, sharp=30.0):
    """head outputs that put all mass on the gold targets (decoder selftest)"""
    T = tg["per_run"]
    P = dict(leafable=tg["leafable"], run={}, sib={}, run_value={})
    for k in tg["leafable"]:
        d = {}
        for h, C in (("used", 2), ("parent", len(PARENT_CLASSES)), ("side", 2), ("depth", DEPTH_CLASSES),
                     ("cpartner", 1 + len(VOCAB))):
            v = np.full(C, -sharp)
            if T[h][k] >= 0:
                v[T[h][k]] = 0.0
            else:
                v[:] = -math.log(C)
            d[h] = v
        P["run"][k] = d
    for key, s in tg["pairs"].items():
        v = np.full(2, -sharp); v[s] = 0.0; P["sib"][key] = v
    P["steps"] = np.full(STEP_CLASSES, -sharp); P["steps"][tg["steps"]] = 0.0
    P["root"] = np.full(len(ROOT_CLASSES), -sharp); P["root"][tg["root"]] = 0.0
    P["consts"] = [int(x) for x in tg["consts"]]
    al = align_numerals(row); nums = numeral_values(row)
    for ni, r in enumerate(al):
        if r is not None and r < R and r not in P["run_value"] and nums[ni] is not None:
            P["run_value"][r] = (ni, nums[ni])
    return P


# ================================================================== A-answer search (D6) and the host program
def search_programs(row, target, R, max_steps=3, max_consts=2, tie_cap=64, eps=1e-9):
    """the shortest programs (<= max_steps) over the row's pointer-able numerals and the vocabulary that execute EXACTLY
    to target. Each numeral used at most once, at most max_consts constant leaves, no constant-only step. Float search,
    exact verification. Returns (steps or None, [trees], n_candidates_checked)."""
    target = Fraction(target)
    al = align_numerals(row); nums = numeral_values(row)
    seen, L = set(), []
    for ni, (r, v) in enumerate(zip(al, nums)):
        if r is not None and r < R and v is not None and v not in seen:
            seen.add(v); L.append((("n", ni, v), frozenset([ni]), 0))
    for ci, v in enumerate(VOCAB):
        L.append((("c", ci, v), frozenset(), 1))
    tf = float(target)
    hits = {}

    def add_hit(t):
        if len(hits) < tie_cap and execute(t) == target:
            hits.setdefault(canon(t), t)
    for t, _, _ in L:
        if t[0] == "n" and t[2] == target:
            add_hit(t)
    if hits:
        return 0, list(hits.values()), len(L)

    def comb(a, b):
        out = []
        if a[2] + b[2] > max_consts or (a[0][0] == "c" and b[0][0] == "c") or (a[1] & b[1]):
            return out
        for op in BOPS:
            pairs = [(a, b)] if op in ("add", "mul") else [(a, b), (b, a)]
            for x, y in pairs:
                out.append((("b", op, x[0], y[0]), x[1] | y[1], x[2] + y[2]))
        return out

    def fval(t):
        try:
            v = execute(t)
        except (ZeroDivisionError, OverflowError):
            return None
        return None if v is None else float(v)
    E1 = []
    for a, b in itertools.combinations(L, 2):
        for e in comb(a, b):
            v = fval(e[0])
            if v is not None:
                E1.append((e, v))
    checked = len(E1)
    for e, v in E1:
        if abs(v - tf) <= eps * max(1.0, abs(tf)):
            add_hit(e[0])
    if hits or max_steps < 2:
        return (1, list(hits.values()), checked) if hits else (None, [], checked)
    E2 = []
    for e, _ in E1:
        for lf in L:
            for c in comb(e, lf):
                v = fval(c[0])
                if v is not None:
                    E2.append((c, v))
    checked += len(E2)
    for e, v in E2:
        if abs(v - tf) <= eps * max(1.0, abs(tf)):
            add_hit(e[0])
    if hits or max_steps < 3:
        return (2, list(hits.values()), checked) if hits else (None, [], checked)
    # 3 steps by inverse lookup: target = E2 (op) leaf, leaf (op) E2, or E1 (op) E1'
    def key(v):
        return round(v, 6) if abs(v) < 1e12 else None
    idx2 = collections.defaultdict(list)
    for e, v in E2:
        k = key(v)
        if k is not None:
            idx2[k].append(e)
    idx1 = collections.defaultdict(list)
    for e, v in E1:
        k = key(v)
        if k is not None:
            idx1[k].append(e)

    def need(op, known, known_left):
        """the other operand's value so that (known op x) or (x op known) = target"""
        try:
            if op == "add": return tf - known
            if op == "mul": return tf / known if known != 0 else None
            if op == "sub": return known - tf if known_left else tf + known
            if op == "div": return known / tf if known_left else tf * known
        except ZeroDivisionError:
            return None
    for big, index in ((L, idx2), ([e for e, _ in E1], idx1)):
        for x in big:
            xv = fval(x[0])
            if xv is None:
                continue
            for op in BOPS:
                for known_left in (True, False):
                    if op in ("add", "mul") and not known_left:
                        continue
                    nv = need(op, xv, known_left)
                    if nv is None or key(nv) is None:
                        continue
                    for y in index.get(key(nv), []):
                        if len(hits) >= tie_cap:
                            break
                        if (x[1] & y[1]) or x[2] + y[2] > max_consts:
                            continue
                        t = ("b", op, x[0], y[0]) if known_left else ("b", op, y[0], x[0])
                        checked += 1
                        if n_steps(t) == 3:
                            add_hit(t)
    return (3, list(hits.values()), checked) if hits else (None, [], checked)


def answer_targets(row, R, **kw):
    """A-answer (D6): targets from the searched programs, ties split (weight 1/n per tied program)"""
    steps, progs, _ = search_programs(row, Fraction(row["gold_frac"]), R, **kw)
    if steps is None:
        return None
    w = 1.0 / len(progs)
    return [(targets_from_tree(t, row, R), w) for t in progs]


def host_program_line(items):
    """ADDENDUM_DEFUSE_A1 item 2. items: (reader_tree or None, host_programs list, gold_tree or None) per host-wrong
    row. Where the host program is UNIQUE: the reader's program matches host / gold / neither. n/total."""
    c = collections.Counter()
    for rt, hp, gt in items:
        c["host_wrong_rows"] += 1
        if not hp:
            c["no_host_program"] += 1; continue
        if len(hp) > 1:
            c["host_program_ambiguous"] += 1; continue
        c["unique"] += 1
        if rt is None:
            c["reader_no_program"] += 1; continue
        r, h = canon(rt), canon(hp[0])
        g = canon(gt) if gt is not None else None
        c["reader_is_host"] += r == h
        c["reader_is_gold"] += (g is not None and r == g)
        c["reader_is_neither"] += (r != h and (g is None or r != g))
    u = c["unique"]
    return dict(host_wrong_rows=c["host_wrong_rows"], host_program_unique=nt(u, c["host_wrong_rows"]),
                host_program_ambiguous=nt(c["host_program_ambiguous"], c["host_wrong_rows"]),
                no_host_program=nt(c["no_host_program"], c["host_wrong_rows"]),
                reader_no_program=nt(c["reader_no_program"], u), reader_matches_host=nt(c["reader_is_host"], u),
                reader_matches_gold=nt(c["reader_is_gold"], u), reader_matches_neither=nt(c["reader_is_neither"], u))


# ================================================================== per-head accuracy, by text position
def head_accuracy_by_position(A, heads, idx):
    """held-out per-head accuracy, n/total, split by the numeral's text position (first / middle / last / only)"""
    S = head_samples(A, idx)
    out = {}
    for h, (keys, y, _) in S.items():
        if h not in heads or h == "sib" or h in ("steps", "root") or h.startswith("const"):
            continue
        pred = np.argmax(_hlogp(heads[h], _X_for(A, h, keys)), 1)
        c = collections.defaultdict(lambda: [0, 0])
        for (i, k), yy, p in zip(keys, y, pred):
            pc = position_class(k, A["tg"][i][2]["n_runs"])
            c[pc][0] += int(p == yy); c[pc][1] += 1; c["all"][0] += int(p == yy); c["all"][1] += 1
        out[h] = {k: nt(*v) for k, v in sorted(c.items())}
    return out


def frac_or_none(x):
    if x is None or isinstance(x, bool):
        return None
    try:
        return Fraction(str(x).strip().replace(",", ""))
    except (ValueError, ZeroDivisionError):
        return None


def host_class(host1, host1_none, v, prompt_vals):
    """agree / none / echo / other, exact and sign-aware"""
    h = frac_or_none(host1)
    if host1_none or h is None:
        return "none"
    if v is not None and h == v:
        return "agree"
    if any(p is not None and h == p for p in prompt_vals):
        return "echo"
    return "other"


def du_ag(progs, host1, host1_none, prompt_vals, layers=LAYERS):
    """fire iff the three layers decode the same program (canonical) AND the host class is echo or other; an abstain
    answers HOST1; never fire on a host-silent row"""
    cs = [canon(progs[L]) if progs.get(L) is not None else None for L in layers]
    v = execute(progs[layers[1]]) if progs.get(layers[1]) is not None else None
    if any(c is None for c in cs):
        return dict(fire=False, reason="no program at some layer", answer=host1, host_class=None, v=None)
    if len(set(cs)) != 1:
        return dict(fire=False, reason="layers disagree", answer=host1, host_class=None, v=v)
    if v is None:
        return dict(fire=False, reason="program does not execute", answer=host1, host_class=None, v=None)
    hc = host_class(host1, host1_none, v, prompt_vals)
    if hc in ("echo", "other"):
        return dict(fire=True, reason="layers agree; host %s" % hc, answer=str(v), host_class=hc, v=v, program=cs[0])
    return dict(fire=False, reason="host %s" % hc, answer=host1, host_class=hc, v=v, program=cs[0])
