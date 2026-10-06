"""inventory.py -- the gold-equation parser of the def-use labels: per source format (ASDiv formulas, MAWPS linear
equations, MathQA programs, Ape210K / Math23K infix, GSM8K calculator annotations, Dolphin1878 single equations)
-> an expression DAG, exact Fraction evaluation, leaf classes and the numbers-masked template key used for fold
grouping. Standard library only.

PORTED, NOT REWRITTEN: lines 24-507 of the project's pinned `defuse_inventory.py` (md5
a0a2b821ac27e04b242f6b041e300d53), minus its cluster path guard (lines 27-34); the inventory / aggregate drivers
after line 507 read cluster files and are not copied. Row fields it reads: annotation.equation, annotation.kind,
numerals_written, prov.run_values, gold_frac, question / text, lang.
"""
import argparse, ast, collections, glob, hashlib, json, math, os, re, sys
from fractions import Fraction


# --------------------------------------------------------------------------------------------- numbers / words
EN_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
            "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
            "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
            "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
            "thousand": 1000, "million": 1000000, "dozen": 12, "dozens": 12, "twice": 2, "double": 2,
            "doubled": 2, "triple": 3, "tripled": 3, "thrice": 3, "half": Fraction(1, 2), "halves": Fraction(1, 2),
            "quarter": Fraction(1, 4), "quarters": Fraction(1, 4), "third": Fraction(1, 3), "pair": 2,
            "pairs": 2, "once": 1, "single": 1, "score": 20, "week": 7, "weeks": 7, "hour": 60, "hours": 60,
            "minute": 60, "minutes": 60, "day": 24, "days": 24, "year": 12, "years": 12, "percent": 100,
            "cents": 100, "cent": 100, "dollar": 100, "dollars": 100}
# Words above that are UNITS (week, hour, ...) are tagged 'unit_word' not 'number_word' in the leaf class.
UNIT_WORDS = {"week", "weeks", "hour", "hours", "minute", "minutes", "day", "days", "year", "years", "percent",
              "cents", "cent", "dollar", "dollars"}
CJK = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
       "十": 10, "百": 100, "千": 1000, "万": 10000, "半": Fraction(1, 2), "双": 2, "倍": 2}


def frac(s):
    s = str(s).strip().replace(",", "")
    if s.startswith("+"):
        s = s[1:]
    return Fraction(s)


def numeral_values(r):
    out = []
    for x in r.get("numerals_written") or []:
        try:
            out.append(frac(x))
        except (ValueError, ZeroDivisionError):
            out.append(None)
    return out


def run_values(r):
    out = []
    for x in (r.get("prov") or {}).get("run_values") or []:
        try:
            out.append(Fraction(int(x)))
        except ValueError:
            out.append(None)
    return out


# --------------------------------------------------------------------------------------------- expression DAG
# node: ("leaf", Fraction, tag)   tag = literal text or "n3" / "const_100"
#       ("op", name, [child, ...])
#       ("ref", k)                 -> statement / step k's result (an intermediate)
BIN = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.Div: "div", ast.Pow: "pow", ast.Mod: "mod",
       ast.FloorDiv: "floordiv"}


class Unsupported(Exception):
    pass


def from_ast(n, refs=None):
    if isinstance(n, ast.Expression):
        return from_ast(n.body, refs)
    if isinstance(n, ast.BinOp) and type(n.op) in BIN:
        return ("op", BIN[type(n.op)], [from_ast(n.left, refs), from_ast(n.right, refs)])
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
        c = from_ast(n.operand, refs)
        if c[0] == "leaf":
            return ("leaf", -c[1], "-" + c[2])
        return ("op", "neg", [c])
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.UAdd):
        return from_ast(n.operand, refs)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
        raise Unsupported("float_const")          # literals are pre-wrapped as L("...") strings
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
        nm = n.func.id
        if nm == "L" and len(n.args) == 1 and isinstance(n.args[0], ast.Constant):
            t = n.args[0].value
            return ("leaf", frac(t), t)
        if nm == "pct" and len(n.args) == 1:
            return ("op", "pct", [from_ast(n.args[0], refs)])
        if nm == "R" and len(n.args) == 1 and isinstance(n.args[0], ast.Constant):
            return ("ref", int(n.args[0].value))
        raise Unsupported("call:" + nm)
    if isinstance(n, ast.Name):
        raise Unsupported("name:" + n.id)
    raise Unsupported("node:" + type(n).__name__)


NUM_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?|\.\d+)(?![\w])")


def wrap_literals(s):
    return NUM_RE.sub(lambda m: 'L("%s")' % m.group(1), s)


def norm_infix(s):
    s = s.replace("×", "*").replace("÷", "/").replace("（", "(").replace("）", ")").replace("[", "(")
    s = s.replace("]", ")").replace("{", "(").replace("}", ")").replace("^", "**").replace("：", ":")
    s = re.sub(r"(?<=\d),(?=\d{3})", "", s)                     # 1,000 -> 1000
    s = re.sub(r"(\d)\s*[xX]\s*(\d)", r"\1*\2", s)              # 3 x 4 -> 3*4
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"pct(\1)", s)           # 5% -> pct(5)
    return s


def parse_infix(expr, refs=None):
    s = norm_infix(expr)
    flags = set()
    if ":" in s:
        flags.add("ratio_colon"); s = s.replace(":", "/")
    if re.search(r"\d\(", s):
        flags.add("mixed_number"); s = re.sub(r"(\d)\(", r"\1+(", s)
    s = wrap_literals(s)
    if refs:
        for k, name in refs:
            s = s.replace(name, 'R("%d")' % k)
    if "%" in s:
        raise Unsupported("bare_percent")
    try:
        t = ast.parse(s.strip(), mode="eval")
    except SyntaxError:
        raise Unsupported("syntax")
    return from_ast(t), flags


def ev(n, steps):
    """exact evaluation; returns (value, exact_flag)"""
    k = n[0]
    if k == "leaf":
        return n[1], True
    if k == "ref":
        return steps[n[1]]
    name, ch = n[1], n[2]
    vals = [ev(c, steps) for c in ch]
    ex = all(e for _, e in vals)
    v = [x for x, _ in vals]
    try:
        if name == "add": return v[0] + v[1], ex
        if name == "sub": return v[0] - v[1], ex
        if name == "mul": return v[0] * v[1], ex
        if name == "div": return Fraction(v[0]) / v[1], ex
        if name == "neg": return -v[0], ex
        if name == "pct": return Fraction(v[0]) / 100, ex
        if name == "pow":
            if Fraction(v[1]).denominator == 1 and abs(v[1]) <= 64:
                return Fraction(v[0]) ** int(v[1]), ex
            return Fraction(float(v[0]) ** float(v[1])), False
        if name in ("mod", "reminder"): return Fraction(v[0]) % v[1], ex
        if name == "floordiv": return Fraction(math.floor(Fraction(v[0]) / v[1])), ex
        if name == "floor": return Fraction(math.floor(v[0])), ex
        if name == "inverse": return 1 / Fraction(v[0]), ex
        if name == "sqrt":
            r = math.isqrt(int(v[0])) if Fraction(v[0]).denominator == 1 and v[0] >= 0 else None
            if r is not None and r * r == v[0]: return Fraction(r), ex
            return Fraction(math.sqrt(float(v[0]))), False
        if name == "factorial":
            if not 0 <= v[0] <= 200: raise Unsupported("exec_error")
            return Fraction(math.factorial(int(v[0]))), ex
        if name == "lcm": return Fraction(math.lcm(int(v[0]), int(v[1]))), ex
        if name == "gcd": return Fraction(math.gcd(int(v[0]), int(v[1]))), ex
        if name == "choose": return Fraction(math.comb(int(v[0]), int(v[1]))), ex
        if name == "permutation": return Fraction(math.perm(int(v[0]), int(v[1]))), ex
        if name == "max": return max(v[0], v[1]), ex
        if name == "min": return min(v[0], v[1]), ex
        if name == "rectangle_area": return v[0] * v[1], ex
        if name == "square_area": return v[0] * v[0], ex
        if name == "speed": return Fraction(v[0]) / v[1], ex
        if name == "rectangle_perimeter": return 2 * (v[0] + v[1]), ex
        if name == "square_perimeter": return 4 * v[0], ex
        if name == "volume_cube": return v[0] ** 3, ex
        if name == "surface_cube": return 6 * v[0] ** 2, ex
        if name == "triangle_area": return Fraction(v[0]) * v[1] / 2, ex
        if name == "volume_rectangular_prism": return v[0] * v[1] * v[2], ex
        if name == "circle_area": return Fraction(3.1416) * v[0] ** 2, False
        if name == "circumface": return 2 * Fraction(3.1416) * v[0], False
        if name == "triangle_perimeter": return v[0] + v[1] + v[2], ex
        if name == "rhombus_area": return Fraction(v[0]) * v[1] / 2, ex
    except (ZeroDivisionError, ValueError, OverflowError, TypeError):
        raise Unsupported("exec_error")
    raise Unsupported("op:" + name)


BASIC = {"add", "sub", "mul", "div"}
MATHQA_OPMAP = {"add": "add", "subtract": "sub", "multiply": "mul", "divide": "div"}


def const_value(name):
    if name == "const_pi":
        return Fraction("3.1416"), "const_pi"
    body = name[len("const_"):]
    if body.startswith("m_"):
        return -frac(body[2:].replace("_", ".")), name
    return frac(body.replace("_", ".")), name


def parse_mathqa(eq):
    steps = [s for s in eq.strip().strip("|").split("|") if s.strip()]
    prog = []
    for s in steps:
        m = re.fullmatch(r"\s*([a-z_0-9]+)\((.*)\)\s*", s)
        if not m:
            raise Unsupported("mathqa_syntax")
        op, args = m.group(1), [a.strip() for a in m.group(2).split(",") if a.strip()]
        ch = []
        for a in args:
            if re.fullmatch(r"n\d+", a): ch.append(("nidx", int(a[1:])))
            elif re.fullmatch(r"#\d+", a): ch.append(("ref", int(a[1:])))
            elif a.startswith("const_"):
                v, t = const_value(a); ch.append(("leaf", v, t))
            else:
                raise Unsupported("mathqa_arg")
        prog.append(("op", MATHQA_OPMAP.get(op, op), ch))
    return prog


# --------------------------------------------------------------------------------------------- per-format parse
def solve_linear(eq):
    """single-unknown linear equation 'lhs = rhs' -> explicit expression tree for the unknown, by inversion."""
    if eq.count("=") != 1:
        raise Unsupported("not_one_equals")
    lhs, rhs = eq.split("=")
    names = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", norm_infix(eq))) - {"pct"}
    if len(names) != 1:
        raise Unsupported("system" if len(names) > 1 else "no_unknown")
    var = names.pop()
    def side(s):
        s2 = wrap_literals(norm_infix(s))
        s2 = re.sub(r"\b%s\b" % re.escape(var), "V", s2)
        return ast.parse(s2.strip(), mode="eval").body
    try:
        L, R = side(lhs), side(rhs)
    except SyntaxError:
        raise Unsupported("syntax")
    def has(n):
        return any(isinstance(x, ast.Name) and x.id == "V" for x in ast.walk(n))
    if has(L) and has(R):
        raise Unsupported("unknown_both_sides")
    if not has(L):
        L, R = R, L
    explicit = isinstance(L, ast.Name)
    target = from_ast(R)
    node = L
    while not isinstance(node, ast.Name):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            target = ("op", "neg", [target]); node = node.operand; continue
        if not (isinstance(node, ast.BinOp) and type(node.op) in BIN):
            raise Unsupported("nonlinear")
        op = BIN[type(node.op)]
        if has(node.left):
            other = from_ast(node.right)
            inv = {"add": ("sub", False), "sub": ("add", False), "mul": ("div", False), "div": ("mul", False)}
            if op not in inv: raise Unsupported("nonlinear")
            target = ("op", inv[op][0], [target, other]); node = node.left
        else:
            other = from_ast(node.left)
            if op == "add": target = ("op", "sub", [target, other])
            elif op == "mul": target = ("op", "div", [target, other])
            elif op == "sub": target = ("op", "sub", [other, target])
            elif op == "div": target = ("op", "div", [other, target])
            else: raise Unsupported("nonlinear")
            node = node.right
    return target, explicit


UNIT_PAREN = re.compile(r"\(\s*[A-Za-z][A-Za-z/ ]*\)")


def parse_row(r):
    """returns dict(fmt, prog=[stmt nodes], final=index, flags) or raises Unsupported. prog: list of nodes;
    each statement's result may be referenced by later ones through ('ref', k)."""
    a = r.get("annotation") or {}
    eq = a.get("equation")
    kind = (a.get("kind") or "").split(" ")[0]
    if not eq:
        raise Unsupported("no_equation")
    flags = set()
    if kind == "mathqa":
        return dict(fmt="mathqa", prog=parse_mathqa(eq), flags=flags)
    if kind in ("ape210k", "math23k", "paramawps"):
        e = eq.strip()
        e = re.sub(r"^\s*[xX]\s*=", "", e)
        if "=" in e:
            raise Unsupported("implicit_equation")
        node, fl = parse_infix(e)
        return dict(fmt=kind, prog=[node], flags=fl)
    if kind == "mawps":
        if ";" in eq:
            raise Unsupported("system")
        node, explicit = solve_linear(eq)
        if not explicit: flags.add("implicit_inverted")
        return dict(fmt="mawps", prog=[node], flags=flags)
    if kind == "dolphin1878":
        parts = [p.strip() for p in eq.split(";")]
        eqs = [p[4:].strip() for p in parts if p.startswith("equ:")]
        if len(eqs) != 1:
            raise Unsupported("system")
        node, explicit = solve_linear(eqs[0])
        if not explicit: flags.add("implicit_inverted")
        return dict(fmt="dolphin1878", prog=[node], flags=flags)
    if kind in ("asdiv", "gsm8k"):
        if kind == "asdiv":
            e = UNIT_PAREN.sub("", eq)
            if re.search(r"\d\s*r\s*\d", e):
                raise Unsupported("remainder")
            stmts = [s for s in e.split(";") if s.strip()]
        else:
            stmts = [s for s in eq.split("|") if s.strip()]
        prog, results = [], []
        for s in stmts:
            if "=" in s:
                lhs, rhs = s.rsplit("=", 1)
            else:
                lhs, rhs = s, None
            lhs = re.sub(r"[$€£]", "", lhs)
            node, fl = parse_infix(lhs)
            flags |= fl
            prog.append(node)
            rv = None
            if rhs is not None:
                m = re.search(r"-?\d[\d,]*(?:\.\d+)?|-?\.\d+", rhs)
                if m:
                    try: rv = frac(m.group(0))
                    except ValueError: rv = None
            results.append(rv)
        return dict(fmt=kind, prog=prog, stated=results, flags=flags)
    raise Unsupported("kind:" + kind)


# --------------------------------------------------------------------------------------------- leaf mapping
def leaf_class(v, r, nums, runs, qlow, lang):
    if v is None:
        return "const", None
    hits = [i for i, x in enumerate(nums) if x is not None and x == v]
    if hits:
        rhits = [i for i, x in enumerate(runs) if x is not None and x == v]
        if rhits:
            return ("numeral_in_runs" if len(hits) == 1 else "numeral_in_runs_ambig"), hits
        return "numeral_not_a_run", hits                 # decimal / comma numeral: state at its last run
    if lang == "en" or (lang or "").startswith("en"):
        for w, val in EN_WORDS.items():
            if Fraction(val) == v and re.search(r"\b%s\b" % w, qlow):
                return ("unit_word" if w in UNIT_WORDS else "number_word"), None
    q = r.get("question") or ""
    for ch, val in CJK.items():
        if Fraction(val) == v and ch in q:
            return "cjk_numeral", None
    return "const", None


def walk(n):
    yield n
    if n[0] == "op":
        for c in n[2]:
            yield from walk(c)


def analyse(r, parsed):
    """link statements, map leaves, execute; returns a compact dict."""
    fmt, prog = parsed["fmt"], parsed["prog"]
    nums, runs = numeral_values(r), run_values(r)
    qlow = (r.get("question") or "").lower()
    lang = r.get("lang") or ""
    # 1. resolve statement chaining for asdiv / gsm8k: a literal equal to an earlier stated result -> ref
    amb_inter = 0
    if fmt in ("asdiv", "gsm8k"):
        stated = parsed.get("stated") or []
        new = []
        for k, node in enumerate(prog):
            def sub(n):
                nonlocal amb_inter
                if n[0] == "leaf":
                    for j in range(k - 1, -1, -1):
                        if stated[j] is not None and stated[j] == n[1]:
                            if any(x == n[1] for x in nums if x is not None):
                                amb_inter += 1
                            return ("ref", j)
                    return n
                if n[0] == "op":
                    return ("op", n[1], [sub(c) for c in n[2]])
                return n
            new.append(sub(node))
        prog = new
    # 2. mathqa n_k -> numerals by index
    leaves_bad = 0
    if fmt == "mathqa":
        new = []
        for node in prog:
            ch = []
            for c in node[2]:
                if c[0] == "nidx":
                    if c[1] >= len(nums) or nums[c[1]] is None:
                        leaves_bad += 1; ch.append(("leaf", None, "n%d" % c[1]))
                    else:
                        ch.append(("leaf", nums[c[1]], "n%d" % c[1]))
                else:
                    ch.append(c)
            new.append(("op", node[1], ch))
        prog = new
    # 3. execute (the last statement is the answer)
    steps = []
    exact = True
    for node in prog:
        if any(x[0] == "leaf" and x[1] is None for x in walk(node)):
            raise Unsupported("mathqa_n_out_of_range")
        v, ex = ev(node, steps)
        steps.append((v, ex)); exact = exact and ex
    val, _ = steps[-1]
    gold = Fraction(r["gold_frac"])
    try:
        if val == gold and exact:
            status = "exec_exact"
        elif abs(val - gold) <= Fraction(5, 1000) * max(1, abs(gold)):
            status = "exec_approx"
        else:
            status = "exec_mismatch"
    except (OverflowError, TypeError):
        status = "exec_mismatch"
    # 4. DAG statistics. Count every op node over all statements reachable from the final one.
    used = collections.Counter()
    def reach(k, seen):
        if k in seen: return
        seen.add(k)
        for n in walk(prog[k]):
            if n[0] == "ref":
                used[n[1]] += 1; reach(n[1], seen)
    reach(len(prog) - 1, set())
    live = {len(prog) - 1} | set(used)
    ops = collections.Counter(); n_bin = n_unary = 0; defuse = 0; leaves = []
    nc = dict(n=0, both_num=0, left_first=0, left_larger=0)
    for k in live:
        for n in walk(prog[k]):
            if n[0] != "op":
                if n[0] == "leaf": leaves.append(n)
                continue
            ops[n[1]] += 1
            if len(n[2]) >= 2: n_bin += 1
            else: n_unary += 1
            if any(c[0] in ("op", "ref") for c in n[2]):
                defuse += 1
            if n[1] in ("sub", "div") and len(n[2]) == 2:
                nc["n"] += 1
                L, R = n[2]
                if L[0] == "leaf" and R[0] == "leaf" and L[1] is not None and R[1] is not None:
                    li = [i for i, x in enumerate(nums) if x == L[1]]
                    ri = [i for i, x in enumerate(nums) if x == R[1]]
                    if li and ri:
                        nc["both_num"] += 1
                        if min(li) < min(ri): nc["left_first"] += 1
                        if L[1] > R[1]: nc["left_larger"] += 1
    # chained-statement steps also count the reference edges as def-use
    reuse = sum(1 for k, c in used.items() if c >= 2)
    lc = collections.Counter(); consts = []
    for lf in leaves:
        c, _ = leaf_class(lf[1], r, nums, runs, qlow, lang) if not str(lf[2]).startswith("const_") else ("const", None)
        if str(lf[2]).startswith("n") and fmt == "mathqa":
            c = "numeral_in_runs" if r.get("runs_equal_numerals") else "numeral_not_a_run"
        lc[c] += 1
        if c == "const":
            consts.append(str(lf[1]) if not str(lf[2]).startswith("const_") else str(lf[1]))
    grammar = "basic4" if set(ops) <= BASIC | {"pct", "neg"} else "extended"
    return dict(status=status, grammar=grammar, ops=dict(ops), n_bin=n_bin, n_unary=n_unary, defuse=defuse,
                reuse=reuse, n_stmt=len(prog), n_leaves=len(leaves), leaf=dict(lc), consts=consts,
                amb_inter=amb_inter, nc=nc, flags=sorted(parsed.get("flags") or []))


# --------------------------------------------------------------------------------------------- template key
def tkey(r):
    q = (r.get("question") or r.get("text") or "").lower()
    q = re.sub(r"\d+(?:[.,]\d+)*", "#", q)
    for w in EN_WORDS:
        if w not in UNIT_WORDS:
            q = re.sub(r"\b%s\b" % w, "#", q)
    q = re.sub(r"\s+", "", q)
    return hashlib.md5(q.encode("utf-8")).hexdigest()[:16]

