#!/usr/bin/env python3
"""gen_v5.py -- fill the CLEANED v5 templates into bank rows in v4's row format, audit them, record md5s (stdlib only).

    python3 gen_v5.py --clean clean/clean_v5.json --out-dir bank          # the bank of record (verified templates)
    python3 gen_v5.py --preview --out-dir preview                         # accepted writer units, unverified, for a look
    python3 gen_v5.py --selftest

OUTPUT (v4 layout, so the finaliser / dumper / readers find what they expect): <out>/signed_A_int.jsonl (every row),
empty signed_B_int / signed_A_dec / signed_B_dec, pairs.json (template -> arm -> operands), AUDIT_v5.txt, and
SHIP_V5.raw.md5. Every row carries every key a v4 row carries (checked in the selftest against v4/signed_A_int.jsonl
and v4wild/signed_A_int.jsonl) plus the v5 difficulty metadata below. `a` is the minuend / dividend / first operand,
`b` the subtrahend / divisor / second operand, so the finaliser's gold_run_idx [index(a), index(b)] is the role label.

ROWS PER TEMPLATE (24, 12 in each written order; k = the template's ordinal within its language, used only to
rotate categories, tiers and which order the single-order arms take):
  base      2 numerals   base facts alone                          2 orders x 2 twins                      4 rows
  T         3            facts with the inline {T}                 2 orders x 2 twins x 2 value tiers      8 rows
  ex        3            base + the role-free sentence             1 order ((k+1)%2) x 2 twins             2 rows
  sem       3            base + the same-kind other-owner sentence the other order x 2 twins             2 rows
  T+ex|sem  4            facts with {T} + one sentence (ex if k even, sem if odd)  2 orders x 2 twins      4 rows
  T+ex+sem  5            facts with {T} + both sentences           2 orders x 2 twins                      4 rows
Every row is one half of a MINIMAL PAIR (same pair_key, word-identical after swapping the operands back):
  sub, signed    value swap: pos M = big, S = small | neg M = small, S = big (answer negative)   kind pos / neg
  sub, unsigned  redraw: identical operands (M larger), the DISTRACTOR values redrawn             kind pos / pos
  add, mul       value swap of the two operand slots                                              kind pos / pos
  div            divisor swap: same dividend N = f1*f2, divisor f1 (answer f2) | f2 (answer f1)   kind pos / pos
so the size rule ("the minuend is the larger") is wrong on every neg row, and for div it is right by construction
(an exact quotient of distinct whole numbers is smaller than its dividend): div breaks WRITTEN ORDER, not size.

DIFFICULTY METADATA (per row, aligned with `ds` in written order):
  d_rungs      the similarity ladder: L0_kind (role-free, different kind) < L1_owner_sent (same kind, other owner,
               own sentence) < L1_owner (same kind, other owner, inline) < L2_time (same owner, another time)
               < L3_list (same-kind list, the question picks two)
  d_positions  before / between / after the two operands, from the filled text
  d_tiers      V0_len (a digit length no operand has) / V1_same_len (an operand's length, not near) /
               V2_near (an operand's length and within max(2, x/10) of it); d_tiers_intended records the plan
  n_numerals_written 2..5, variant (min_first = {M} written first), qorder
  attr_pairs / attr_collision   host_attr_v5.row_record: every candidate pair's result under the row's op
DRAWS: operands per (template, arm, category) from 8 categories per op (sub/add: v4's eight, gen_signed_bank_ml.py
lines 183-215; mul/div: new, seeded rejection sampling). Distractor values come from the OPERAND VALUE UNIVERSE (value
memorisation 0 by construction), rank-balanced over low/mid/high, distinct, digit-substring-free, keep the gold pair the
ONLY pair giving |answer| under ANY operator, and PREFER draws with no attribution collision at all (fallback flagged).
Seeds: v4's blake2b keying (v5_common.seeded), never keyed on the twin except the redraw twin's distractors.
"""
import sys
sys.dont_write_bytecode = True   # no __pycache__: write nothing beyond the files the brief names
import argparse
import collections
import copy
import glob
import hashlib
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import v5_common as C  # noqa: E402
import host_attr_v5 as H  # noqa: E402
import validate_v5 as V  # noqa: E402

SEED = 20260929
NCAT = 8


# ------------------------------------------------------------------ numeral categories
def _ok_v4(big, small, allow_substring=False):
    """gen_signed_bank_ml.py _ok (lines 171-180), verbatim in effect."""
    if small <= 0 or big <= small:
        return False
    d = big - small
    if d == big or d == small:
        return False
    sb, ss, sd = str(big), str(small), str(d)
    if not allow_substring and (ss in sb or sb in ss):
        return False
    if sd == sb or sd == ss:
        return False
    return True


def _v4_pools():
    """gen_signed_bank_ml.py _cat_pools (lines 183-215): the eight categories of the signed bank, (big, small)."""
    c = [[] for _ in range(8)]
    for big in range(2, 10):
        for small in range(1, big):
            if _ok_v4(big, small): c[0].append((big, small))
    for big in range(30, 100):
        for small in range(11, big - 9):
            if _ok_v4(big, small): c[1].append((big, small))
    for big in range(14, 100):
        for small in range(big - 3, big):
            if small >= 11 and _ok_v4(big, small): c[2].append((big, small))
    for x in range(2, 10):
        for y in range(1, x):
            big, small = 10 * x + y, 10 * y + x
            if _ok_v4(big, small): c[3].append((big, small))
    for big in range(1000, 1013):
        for small in range(988, 1000):
            if _ok_v4(big, small): c[4].append((big, small))
    for big in range(1000, 10000):
        for small in range(2, 10):
            if _ok_v4(big, small): c[5].append((big, small))
    for small in range(102, 990):
        if small % 10 == 0: continue
        for r in range(10):
            big = small * 10 + r
            if _ok_v4(big, small, allow_substring=True): c[6].append((big, small))
    for k in range(11, 100):
        for j in range(10, k):
            big, small = k * 10000, j * 10000
            if _ok_v4(big, small): c[7].append((big, small))
    return c


V4_POOLS = _v4_pools()
CAT_NAMES = {
    'sub': ['single_digits', 'two_digit_gap', 'near_equal', 'digit_swap', 'near_equal_1000', 'length_gap',
            'x10_lookalike', 'six_digits'],
    'mul': ['1x1', '1x2', '2x1', '2x2', '3x1', '1x3', '2x3', '4x1'],
    'div': ['1x1', '1x2', '2x2', '1x3', '2x3', '1x4', 'near_equal_2digit', '2x4'],
}
CAT_NAMES['add'] = CAT_NAMES['sub']
MUL_RANGES = [((2, 9), (2, 9)), ((2, 9), (11, 99)), ((11, 99), (2, 9)), ((11, 49), (11, 49)), ((100, 999), (2, 9)),
              ((2, 9), (100, 999)), ((11, 99), (100, 499)), ((1000, 9999), (2, 9))]
DIV_RANGES = [((2, 9), (2, 9)), ((2, 9), (11, 99)), ((11, 99), (11, 99)), ((2, 9), (100, 999)), ((11, 99), (100, 999)),
              ((2, 9), (1000, 9999)), None, ((11, 99), (1000, 2999))]


def _substr(a, b):
    sa, sb = str(a), str(b)
    return sa in sb or sb in sa


def _pair_ok_twins(op, twins):
    """Each twin (M, S, ans): the two operands alone give |ans| only under the gold operator, and the answer is not an
    operand's digit string."""
    for m, s, ans in twins:
        if not H.gold_unique_anyop([m, s], 0, 1, op, ans)[0]:
            return False
        if str(abs(ans)) in (str(m), str(s)):
            return False
    return True


def twins_for(op, signed, pair):
    """[(twin label, M, S, ans, kind)] for the two halves of a minimal pair."""
    x, y = pair
    if op == 'sub' and signed:
        return [('pos', x, y, x - y, 'pos'), ('neg', y, x, y - x, 'neg')]
    if op == 'sub':
        return [('ra', x, y, x - y, 'pos'), ('rb', x, y, x - y, 'pos')]
    if op == 'add':
        return [('ta', x, y, x + y, 'pos'), ('tb', y, x, x + y, 'pos')]
    if op == 'mul':
        return [('ta', x, y, x * y, 'pos'), ('tb', y, x, x * y, 'pos')]
    n = x * y                                   # div: pair = (f1, f2), N = f1*f2
    return [('ta', n, x, y, 'pos'), ('tb', n, y, x, 'pos')]


def draw_pair(op, signed, cat, key):
    """Operands for one (template, arm) cell: (pair, twins)."""
    r = C.seeded('pair', *key, seed=SEED)
    if op in ('sub', 'add'):
        pool = sorted(V4_POOLS[cat])
        r.shuffle(pool)
        for p in pool[:4000]:
            tw = twins_for(op, signed, p)
            if _pair_ok_twins(op, [(m, s, a) for _, m, s, a, _ in tw]):
                return p, tw
        return None, None
    for _ in range(20000):
        if op == 'mul':
            (a0, a1), (b0, b1) = MUL_RANGES[cat]
            g, s = r.randint(a0, a1), r.randint(b0, b1)
            if g == s or _substr(g, s) or _substr(g * s, g) or _substr(g * s, s):
                continue
            p = (g, s)
        else:
            if DIV_RANGES[cat] is None:
                f1 = r.randint(11, 96); f2 = f1 + r.randint(1, 3)
            else:
                (a0, a1), (b0, b1) = DIV_RANGES[cat]
                f1, f2 = r.randint(a0, a1), r.randint(b0, b1)
            if f1 >= f2:
                continue
            n = f1 * f2
            if _substr(f1, f2) or _substr(f1, n) or _substr(f2, n):
                continue
            p = (f1, f2)
        tw = twins_for(op, signed, p)
        if _pair_ok_twins(op, [(m, s, a) for _, m, s, a, _ in tw]):
            return p, tw
    return None, None


# ------------------------------------------------------------------ distractor values
def tier_of(d, refs):
    L = len(str(d))
    same = [x for x in refs if len(str(x)) == L]
    if not same:
        return 'V0_len'
    if any(abs(d - x) <= max(2, x // 10) for x in same):
        return 'V2_near'
    return 'V1_same_len'


class Drawer:
    def __init__(self, universe):
        self.by_len = collections.defaultdict(list)
        for v in sorted(universe):
            self.by_len[len(str(v))].append(v)
        self.fallback = collections.Counter()

    def pick(self, op, twins, extras, refs, tier, key, avoid=()):
        """One distractor value for a cell. twins: [(M, S, ans)] (the value must work for every twin); extras: values
        already placed in the row (per twin identical); refs: the operand values the tier is judged against.
        Returns (value, actual tier, strict) or None."""
        r = C.seeded('dist', *key, seed=SEED)
        opvals = set(v for m, s, _ in twins for v in (m, s))
        ans_s = set(str(abs(a)) for _, _, a in twins)
        lo = min(twins[0][0], twins[0][1]); hi = max(twins[0][0], twins[0][1])
        ref_lens = sorted(set(len(str(x)) for x in refs))
        order = [tier] + [t for t in C.VTIERS if t != tier]
        for t in order:
            if t == 'V0_len':
                lens = [L for L in sorted(self.by_len) if L not in ref_lens and L <= 6]
            else:
                lens = ref_lens
            cand = [d for L in lens for d in self.by_len.get(L, ()) if tier_of(d, refs) == t]
            if not cand:
                continue
            classes = {'low': [d for d in cand if d < lo], 'mid': [d for d in cand if lo < d < hi],
                       'high': [d for d in cand if d > hi]}
            corder = ['low', 'mid', 'high']
            r.shuffle(corder)
            for strict_pass in (True, False):
                for cls in corder:
                    lst = list(classes[cls])
                    r.shuffle(lst)
                    for d in lst[:300]:
                        if d in opvals or d in extras or d in avoid or any(_substr(d, v) for v in opvals) or \
                                any(str(d) in a_ or a_ in str(d) for a_ in ans_s):
                            continue
                        good = True; clean = True
                        for m, s, a in twins:
                            vals = [m, s] + list(extras) + [d]
                            if not H.gold_unique_anyop(vals, 0, 1, op, a)[0]:
                                good = False; break
                            if H.collisions(vals, op):
                                clean = False
                        if not good:
                            continue
                        if clean or not strict_pass:
                            if t != tier:
                                self.fallback[(tier, t)] += 1
                            return d, t, clean
        return None


# ------------------------------------------------------------------ assembly
# A split point is a real sentence start only if the next character is not lowercase or clause punctuation and the
# word before the ender is not a known abbreviation: 'sprzedał {M} szt. koszul', '{M} шт., газировки', 'Mr. Smith'
# (2026-09-29: fix the generator, not the templates; audit pl 23 / ru 41 / uk 31 templates).
ABBREV = frozenset('mr mrs ms dr sr jr sra srta capt lt sgt prof hr fr dhr mevr dott ing'.split())   # titles only:
# a title is followed by a capitalised name; any other abbreviation mid-clause is followed by lowercase or a comma


def real_splits(tpl):
    out = []
    for k in C.split_points(tpl):
        nxt = tpl[k:k + 1]
        before = tpl[:k].rstrip()
        word = before.split()[-1] if before.split() else ''
        if nxt.islower() or nxt in ',;:)' or (word.endswith('.') and word[:-1].lower() in ABBREV):
            continue
        out.append(k)
    return out


def place(facts_tpl, fill, sentences, placements, sep):
    """Insert filled distractor sentences before / between / after the facts, as v4 (gen_signed_bank_ml.py 433-445)."""
    parts = {'pre': [], 'mid': [], 'suf': []}
    for s, p in zip(sentences, placements):
        parts[p].append(s)
    if parts['mid']:
        sp = real_splits(facts_tpl)
        k = sp[0]
        core = fill(facts_tpl[:k].rstrip()) + sep + sep.join(parts['mid']) + sep + fill(facts_tpl[k:].lstrip())
    else:
        core = fill(facts_tpl)
    return sep.join(parts['pre'] + [core] + parts['suf'])


ARMS = ('base', 'T', 'ex', 'sem', 'T+s', 'T+ex+sem')


def arm_cells(k):
    """[(arm, orders, [(cat, qorder, tiers dict)], sentences)] for template ordinal k."""
    t3 = lambda j: C.VTIERS[j % 3]
    return [
        ('base', ['first', 'second'], [((k) % NCAT, 'qlast', {})], ()),
        ('T', ['first', 'second'], [((k + 1) % NCAT, 'qlast', {'T': t3(k)}), ((k + 5) % NCAT, 'qfirst', {'T': t3(k + 1)})], ()),
        ('ex', [('first', 'second')[(k + 1) % 2]], [((k + 3) % NCAT, 'qlast', {'ex': t3(k)})], ('ex',)),
        ('sem', [('first', 'second')[k % 2]], [((k + 7) % NCAT, 'qlast', {'sem': t3(k + 2)})], ('sem',)),
        ('T+s', ['first', 'second'], [((k + 2) % NCAT, 'qlast', {'T': t3(k + 2), ('ex' if k % 2 == 0 else 'sem'): t3(k + 1)})],
         (('ex',) if k % 2 == 0 else ('sem',))),
        ('T+ex+sem', ['first', 'second'], [((k + 6) % NCAT, 'qlast', {'T': t3(k), 'ex': t3(k + 1), 'sem': t3(k + 2)})], ('ex', 'sem')),
    ]


def build(entries, numdep='keep'):
    """entries: [{lang, lead_in, uid, template, tags, verifier, verified}] -> (rows, pairs table, audit counters)."""
    bylang = collections.defaultdict(list)
    for e in entries:
        if numdep == 'drop' and ('numdep' in e.get('tags', []) or e['template'].get('numeral_grammar') == 'number_dependent'):
            continue
        bylang[e['lang']].append(e)
    for lang in bylang:
        bylang[lang].sort(key=lambda e: e['template']['id'])
    refused = collections.Counter()
    plan = []
    # pass 1: operands for every cell, so the operand universe exists before any distractor is drawn
    for lang in sorted(bylang):
        for k, e in enumerate(bylang[lang]):
            t = e['template']; op = t['op']
            signed = bool(t.get('signed')) and 'demoted' not in e.get('tags', [])
            for arm, orders, cats, sents in arm_cells(k):
                for cat, qorder, tiers in cats:
                    pair, tw = draw_pair(op, signed, cat, (lang, t['id'], arm, cat))
                    if pair is None:
                        refused['no_operands:%s/%s/%d' % (op, arm, cat)] += len(orders) * 2
                        continue
                    for order in orders:
                        plan.append((lang, k, e, arm, order, cat, qorder, tiers, sents, pair, tw, signed))
    universe = set(v for p in plan for _, m, s, _, _ in p[10] for v in (m, s))
    dr = Drawer(universe)
    rows, pairs_tab = [], collections.defaultdict(dict)
    for (lang, k, e, arm, order, cat, qorder, tiers, sents, pair, tw, signed) in plan:
        t = e['template']; op = t['op']; lead = e['lead_in'].strip()
        sep = '' if lang in C.NOSPACE else ' '
        use_T = arm.startswith('T')
        facts_tpl = (t['facts_' + order] if use_T else t['base_' + order]).strip()
        split = bool(real_splits(facts_tpl))
        opts = ['pre', 'suf'] + (['mid', 'mid'] if split else [])
        rp = C.seeded('place', lang, t['id'], arm, order, cat, seed=SEED)
        placements = [rp.choice(opts) for _ in sents]
        redraw = (op == 'sub' and not signed)
        mim = t.get('t_mimics')
        # distractor values: per twin only for the redraw twins, else one draw shared by both halves
        groups = [[w] for w in tw] if redraw else [tw]
        vals_by_twin = {}
        failed = False
        avoid_all = []
        for gidx, grp in enumerate(groups):
            twins3 = [(m, s, a) for _, m, s, a, _ in grp]
            extras, meta = [], []
            names = (['T'] if use_T else []) + list(sents)
            for nm in names:
                if nm == 'T' and op in ('mul', 'div') and mim in ('M', 'S'):
                    refs = sorted(set((m if mim == 'M' else s) for _, m, s, _, _ in grp))
                else:
                    refs = sorted(set(v for _, m, s, _, _ in grp for v in (m, s)))
                key = (lang, t['id'], arm, order, cat, nm) + ((grp[0][0],) if redraw else ())
                # the redraw twin must not repeat the first twin's value in the same slot (the two rows would be identical)
                avoid = [avoid_all[len(extras)]] if (redraw and gidx == 1 and len(avoid_all) > len(extras)) else []
                got = dr.pick(op, twins3, extras, refs, tiers.get(nm, 'V1_same_len'), key, avoid)
                if got is None:
                    failed = True
                    break
                extras.append(got[0]); meta.append((nm, got[0], got[1], got[2], tiers.get(nm)))
            if failed:
                break
            if gidx == 0:
                avoid_all = list(extras)
            for w in grp:
                vals_by_twin[w[0]] = meta
        if failed:
            refused['no_distractor:%s/%s/%d' % (op, arm, cat)] += 2
            continue
        pairs_tab['%s|%s' % (lang, t['id'])]['%s/%s/%d' % (arm, order, cat)] = list(pair)
        for twin, m, s, ans, kind in tw:
            meta = vals_by_twin[twin]
            dval = {nm: v for nm, v, _, _, _ in meta}
            fill = lambda x: x.replace('{M}', str(m)).replace('{S}', str(s)).replace('{T}', str(dval.get('T', '')))
            sent_txt = [t[('ex_sentence' if nm == 'ex' else 'sem_sentence')].strip().replace('{D}', str(dval[nm])) for nm in sents]
            facts = place(facts_tpl, fill, sent_txt, placements, sep)
            q = t['question'].strip()
            text = ((facts + sep + q + sep + lead) if qorder == 'qlast' else (q + sep + facts + sep + lead)).rstrip()
            vals = [int(v) for v in C.RUNS.findall(text)]
            gi, gj = vals.index(m), vals.index(s)
            dmeta = {v: (nm, at, st, it_) for nm, v, at, st, it_ in meta}
            ds = [v for v in vals if v in dmeta]
            lo_, hi_ = min(gi, gj), max(gi, gj)
            pos = ['before' if vals.index(d) < lo_ else ('between' if vals.index(d) < hi_ else 'after') for d in ds]
            rung = {'T': C.RUNG_OF_SHAPE[t['shape']], 'ex': C.RUNG_EX, 'sem': C.RUNG_SEM}
            n_d = len(ds)
            tag = {'base': '', 'T': '-T', 'ex': '-ex', 'sem': '-sem', 'T+s': '-Ts', 'T+ex+sem': '-Tes'}[arm]
            variant = 'min_first' if order == 'first' else 'sub_first'
            sid = int(e['uid'].rsplit('u', 1)[1]) * 100 + int(t['id'].rsplit('-', 1)[1])
            row = dict(
                row_id='sg5:%s:A:%d:%s:%s:%s-%d%s' % (lang, sid, variant, qorder, twin, cat, tag),
                pair_key='sg5:%s:A:%d:%s:%s:%d%s' % (lang, sid, variant, qorder, cat, tag),
                status='scored', wild_op=C.WILD_OP[op], lang=lang, stratum='signed', bank='A', domain=t['topic'],
                kind=kind, variant=variant, qorder=qorder, order_kind=kind, fill='int', pair_id=cat,
                has_distractor=bool(n_d), distractor_pos=(None if arm in ('base', 'T') else
                                                              ('d' + placements[0] if arm in ('ex', 'sem') else 'dmulti')),
                substring_pair=(op in ('sub', 'add') and cat == 6), source='signed_bank_v5', text=text,
                list_values=[m, s] + ds, op=C.OPNAME[op], a=m, b=s, ans=ans, commutative=(op in ('add', 'mul')),
                ka=0, kb=0, kans=0, ds=ds, stated_answer=None, answer_correct=None, answer_in_text=False, cut=True,
                slot_mode='whole', selection_eligible=True, headline_eligible=bool(e.get('verified')),
                completion_valid=True, minuend_is_larger=(m > s), minuend_written_first=(gi < gj),
                n_numerals_written=len(vals), answer_cue=lead, story_id=sid, unit=t.get('unit'),
                sign_convention=(t.get('sign_convention') if signed else ''), question=q, frame_gloss=t.get('gloss_en'),
                verifier=e.get('verifier'),
                prov=dict(locator='block.digit_runs (filled by the finaliser on the cluster)', gold_run_idx=None),
                dist_hardness={'base': None, 'T': 'wildT', 'ex': 'v5ex', 'sem': 'v5sem', 'T+s': 'v5multi4',
                               'T+ex+sem': 'v5multi5'}[arm],
                bank_version='v5',
                # v4wild-compatible extras
                dist_arm=arm, extra_slots=(['T'] if use_T else []), wild_shape=t['shape'],
                dist_entity_note=None, dist_sentences=list(sents), dist_positions=placements,
                # v5 metadata
                template_id=t['id'], writer_unit=e['uid'], slice=e.get('slice'), topic=t['topic'],
                quantity_kind=t.get('quantity_kind'), op_short=op, shape=t['shape'], signed=signed,
                twin=twin, twin_kind=('redraw' if redraw else ('divisor_swap' if op == 'div' else 'value_swap')),
                num_cat='%s:%s' % (op, CAT_NAMES[op][cat]), t_mimics=mim, div_mode=t.get('div_mode') or '',
                numdep=('numdep' in e.get('tags', []) or t.get('numeral_grammar') == 'number_dependent'),
                verified=bool(e.get('verified')), tags=list(e.get('tags', [])),
                d_rungs=[rung[dmeta[d][0]] for d in ds], d_names=[dmeta[d][0] for d in ds],
                d_positions=pos, d_tiers=[dmeta[d][1] for d in ds], d_tiers_intended=[dmeta[d][3] for d in ds],
                d_attr_strict=[dmeta[d][2] for d in ds],
                rung_max=(max((C.RUNGS.index(rung[dmeta[d][0]]) for d in ds), default=-1)),
            )
            row.update(H.row_record(vals, op, gi, gj, ans))
            rows.append(row)
    return rows, dict(pairs_tab), dict(refused=refused, fallback=dr.fallback)


# ------------------------------------------------------------------ audit
def audit(rows, stats, min_cell=0):
    out = []
    P = out.append
    bad, ex = V.row_violations(rows)
    P('ROWS %d; languages %d; templates %d' % (len(rows), len(set(r['lang'] for r in rows)), len(set(r['template_id'] for r in rows))))
    P('row-level violations: %s' % (dict(bad) or 'NONE'))
    for e in ex:
        P('   %s numerals %s ans %s: %s' % e)
    P('refusals (rows): %s' % (dict(stats['refused']) or 'none'))
    P('value-tier fallbacks (intended -> drawn): %s' % ({'%s->%s' % k: v for k, v in stats['fallback'].items()} or 'none'))
    c = collections.Counter
    P('by op %s; by arm %s; numerals per row %s' % (dict(c(r['op_short'] for r in rows)), dict(c(r['dist_arm'] for r in rows)),
                                                    dict(sorted(c(r['n_numerals_written'] for r in rows).items()))))
    # the difficulty cells
    three = [r for r in rows if r['n_numerals_written'] == 3]
    cells = {'op x rung x n': c((r['op_short'], r['d_rungs'][0] if len(r['ds']) == 1 else 'multi:' + C.RUNGS[r['rung_max']], r['n_numerals_written']) for r in rows if r['ds']),
             'op x rung x position (3 numerals)': c((r['op_short'], r['d_rungs'][0], r['d_positions'][0]) for r in three),
             'op x rung x tier drawn (3 numerals)': c((r['op_short'], r['d_rungs'][0], r['d_tiers'][0]) for r in three),
             'op x rung x tier planned (3 numerals)': c((r['op_short'], r['d_rungs'][0], r['d_tiers_intended'][0]) for r in three),
             'op x rung x order (3 numerals)': c((r['op_short'], r['d_rungs'][0], r['variant']) for r in three)}
    low = []
    for name, cc in cells.items():
        P('CELLS %s: %d cells, min %d, max %d' % (name, len(cc), min(cc.values()) if cc else 0, max(cc.values()) if cc else 0))
        for k in sorted(cc):
            P('   %-60s %d' % (' / '.join(str(x) for x in k), cc[k]))
            if name not in ('op x rung x n', 'op x rung x tier drawn (3 numerals)') and min_cell and cc[k] < min_cell:
                low.append((name, k, cc[k]))
    if min_cell:
        P('CELL MINIMUM %d: %s' % (min_cell, 'every 3-numeral cell reaches it' if not low else '%d cells below' % len(low)))
    # shortcuts
    O = set(v for r in rows for v in (r['a'], r['b']))
    placed = [(r, d) for r in rows for d in r['ds']]
    mem = sum(1 for _, d in placed if d not in O)
    P('SHORTCUT value memorisation: distractor values never an operand anywhere %d/%d' % (mem, len(placed)))
    for arm in ARMS[1:]:
        g = [r for r in rows if r['dist_arm'] == arm]
        if not g:
            continue
        pat = c()
        rank = c()
        for r in g:
            vals = [int(v) for v in C.RUNS.findall(r['text'])]
            gi, gj = sorted((vals.index(r['a']), vals.index(r['b'])))
            pat['%d%d/%d' % (gi, gj, len(vals))] += 1
            vs = sorted(vals)
            for d in r['ds']:
                i = vs.index(d)
                rank['low' if i == 0 else ('high' if i == len(vs) - 1 else 'mid')] += 1
        best = pat.most_common(1)[0]
        two_largest = sum(1 for r in g if sorted([r['a'], r['b']]) == sorted([int(v) for v in C.RUNS.findall(r['text'])])[-2:])
        P('SHORTCUT %-9s n=%d  best written-position rule %s %d/%d (%.1f%%); two-largest rule %d/%d (%.1f%%); '
          'distractor rank %s' % (arm, len(g), best[0], best[1], len(g), 100.0 * best[1] / len(g), two_largest, len(g),
                                  100.0 * two_largest / len(g), dict(rank)))
    for op in C.OPS:
        g = [r for r in rows if r['op_short'] == op]
        if g:
            size = sum(1 for r in g if r['minuend_is_larger'])
            first = sum(1 for r in g if r['minuend_written_first'])
            P('BASELINE %s: size rule (role slot = the larger) %d/%d (%.1f%%); first-written rule %d/%d (%.1f%%)' % (
                op, size, len(g), 100.0 * size / len(g), first, len(g), 100.0 * first / len(g)))
    col = c((r['op_short'], r['dist_arm']) for r in rows if r['attr_collision'])
    P('ATTRIBUTION rows with any pair collision: %d/%d %s' % (sum(col.values()), len(rows), dict(col) or ''))
    return out, bad, low


def write_bank(rows, pairs_tab, out_dir, report):
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, 'signed_A_int.jsonl')
    with open(p, 'w', encoding='utf-8') as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    for n in ('signed_B_int.jsonl', 'signed_A_dec.jsonl', 'signed_B_dec.jsonl'):
        open(os.path.join(out_dir, n), 'w').close()
    with open(os.path.join(out_dir, 'pairs.json'), 'w', encoding='utf-8') as fh:
        json.dump(pairs_tab, fh, indent=0, sort_keys=True)
    with open(os.path.join(out_dir, 'AUDIT_v5.txt'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(report) + '\n')
    lines = ['%s  %s' % (C.md5_file(os.path.join(out_dir, n)), n) for n in ('signed_A_int.jsonl', 'pairs.json')]
    with open(os.path.join(out_dir, 'SHIP_V5.raw.md5'), 'w') as fh:
        fh.write('\n'.join(lines) + '\n')
    return lines


# ------------------------------------------------------------------ inputs
def entries_from_clean(path):
    cl = C.load_json(path)
    return [dict(e, verified=True) for e in cl['kept']]


def entries_preview(root=HERE):
    """Accepted writer units (latest accept/ stamp 'accepted'), unverified."""
    out = []
    for uid, st in sorted(V.latest_stamps(os.path.join(root, 'accept')).items()):
        if st.get('status') != 'accepted':
            continue
        doc = C.load_json(os.path.join(root, st['file']))
        for it in doc['items']:
            out.append(dict(lang=doc['language_code'], lead_in=doc['lead_in'], uid=doc['writer_unit'],
                            slice=doc['slice'], template=it, tags=[], verifier=None, verified=False))
    return out


def planted_entries():
    out = []
    for k in (1, 2):
        doc, _ = C.planted_unit(k)
        for it in doc['items']:
            out.append(dict(lang='en', lead_in=doc['lead_in'], uid=doc['writer_unit'], slice=doc['slice'],
                            template=it, tags=[], verifier={'tag': 'SELFTEST'}, verified=True))
    return out


# ------------------------------------------------------------------ selftest
def selftest():
    ok = True

    def chk(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print('  %s  %s' % ('ok  ' if cond else 'FAIL', name))

    ents = planted_entries()
    rows, tab, st = build(ents)
    rep, bad, _ = audit(rows, st)
    td = C.selftest_dir()
    m1 = write_bank(rows, tab, os.path.join(td, 'a'), rep)
    rows2, tab2, st2 = build(planted_entries())
    m2 = write_bank(rows2, tab2, os.path.join(td, 'b'), audit(rows2, st2)[0])
    chk('deterministic: two runs give the same md5 (%s)' % m1[0].split()[0][:8], m1 == m2)
    chk('row-level violations NONE (%s)' % (dict(bad) or 'none'), not bad)
    nref = sum(st['refused'].values())
    chk('rows + refused rows = 24 templates x 24 (%d + %d)' % (len(rows), nref), len(rows) + nref == 24 * C.ROWS_PER_TEMPLATE)
    chk('refusals under 5%% (%d/%d)' % (nref, 24 * C.ROWS_PER_TEMPLATE), nref <= 0.05 * 24 * C.ROWS_PER_TEMPLATE)
    pk = collections.Counter(r['pair_key'] for r in rows)
    chk('every pair_key has exactly 2 rows', set(pk.values()) == {2})
    chk('numerals per row cover 2,3,4,5', set(r['n_numerals_written'] for r in rows) == {2, 3, 4, 5})
    chk('all four ops present', set(r['op_short'] for r in rows) == set(C.OPS))
    v4keys = set()
    for p in (os.path.join(C.SIGNED, 'v4', 'signed_A_int.jsonl'), os.path.join(C.SIGNED, 'v4wild', 'signed_A_int.jsonl')):
        if os.path.exists(p):
            with open(p, encoding='utf-8') as fh:
                v4keys |= set(json.loads(fh.readline()))
    chk('every v4 / v4wild row key present on every v5 row (%d keys)' % len(v4keys), v4keys and all(v4keys <= set(r) for r in rows))
    div = [r for r in rows if r['op_short'] == 'div']
    chk('div rows: exact, dividend written in both orders', all(r['a'] % r['b'] == 0 and r['a'] // r['b'] == r['ans'] for r in div)
        and {r['minuend_written_first'] for r in div} == {True, False})
    neg = [r for r in rows if r['kind'] == 'neg']
    chk('sub signed neg rows: minuend smaller, answer negative (%d rows)' % len(neg),
        neg and all(r['a'] < r['b'] and r['ans'] < 0 and r['op_short'] == 'sub' for r in neg))
    red = [r for r in rows if r['twin_kind'] == 'redraw']
    byk = collections.defaultdict(list)
    for r in red:
        byk[r['pair_key']].append(r)
    chk('redraw twins: same operands, different distractors, never identical texts', red and all(
        a['a'] == b['a'] and a['b'] == b['b'] and a['ds'] != b['ds'] and a['text'] != b['text']
        for a, b in (v for v in byk.values() if len(v) == 2) if a['ds']))
    rungs = set(x for r in rows for x in r['d_rungs'])
    chk('all five rungs present %s' % sorted(rungs), rungs == set(C.RUNGS))
    posn = set(x for r in rows for x in r['d_positions'])
    chk('distractor positions before/between/after all present', posn == {'before', 'between', 'after'})
    tiers = collections.Counter(x for r in rows for x in r['d_tiers'])
    chk('all three value tiers drawn %s' % dict(tiers), set(tiers) == set(C.VTIERS))
    vr = sum(1 for r in rows for d in r['ds'] if d not in set(v for q in rows for v in (q['a'], q['b'])))
    chk('value memorisation 0', vr == 0)
    # the attribution helper on generated rows: the gold result attributes as right unless a collision was allowed
    good = 0; tot = 0
    for r in rows:
        if not r['ds']:
            continue
        vals = [int(v) for v in C.RUNS.findall(r['text'])]
        lab, _ = H.attribute(vals, r['op'], vals.index(r['a']), vals.index(r['b']), r['ans'], r['ans'])
        tot += 1; good += (lab == 'right')
    chk('host_attr: greedy = the answer -> right on %d/%d distractor rows' % (good, tot), good == tot)
    ncol = sum(1 for r in rows if r['attr_collision'])
    chk('attribution collisions are rare (%d/%d rows)' % (ncol, len(rows)), ncol <= 0.05 * len(rows))
    fx = [('Dziś sklep sprzedał {M} szt. koszul. Potem sprzedał {S} szt. spodni.', 1),
          ('Склад получил {M} шт., а магазин продал {S} шт. сока.', 0),
          ('Mr. Grey had {M} hens. Mrs. Grey had {S} hens.', 1),
          ('The shop sold {M} cups. Then it sold {S} mugs.', 1)]
    got = [len(real_splits(t)) for t, _ in fx]
    chk('real_splits skips abbreviation periods %s' % got, got == [n for _, n in fx]
        and real_splits(fx[0][0])[0] > fx[0][0].find('koszul'))
    C.selftest_cleanup()
    print('SELFTEST gen_v5: %s' % ('0 fail' if ok else 'FAIL'))
    return ok


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--clean', default=os.path.join(HERE, 'clean', 'clean_v5.json'))
    ap.add_argument('--preview', action='store_true')
    ap.add_argument('--out-dir', default=os.path.join(HERE, 'bank'))
    ap.add_argument('--numdep', default='keep', choices=['keep', 'drop'])
    ap.add_argument('--min-cell', type=int, default=0)
    a = ap.parse_args(argv[1:])
    if a.selftest:
        return 0 if selftest() else 1
    ents = entries_preview() if a.preview else entries_from_clean(a.clean)
    if not ents:
        print('no templates (preview: no accepted units; clean: empty kept list)')
        return 1
    rows, tab, st = build(ents, a.numdep)
    rep, bad, low = audit(rows, st, a.min_cell)
    lines = write_bank(rows, tab, a.out_dir, rep)
    print('\n'.join(rep))
    print('\n'.join(lines))
    return 1 if (bad or low) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
