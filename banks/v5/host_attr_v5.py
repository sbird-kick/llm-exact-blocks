#!/usr/bin/env python3
"""host_attr_v5.py -- op-general pair attribution for k-numeral rows (stdlib only).

    python3 host_attr_v5.py --selftest
    python3 host_attr_v5.py --bank <signed_A_int.jsonl> [--greedy <rows.jsonl with row_id, greedy_int>]

WHY. host_selection.py (signed/) scores the host's operand SELECTION by attribution: it compares the host's greedy
integer, in magnitude, against |a-b|, |a-d|, |b-d|. That works only for subtraction with exactly three numerals
(REPORT_21664.md section 3d: on the 1,264 v4wild addition and product rows it found 0 right and 4 spurious wrong).
This module does the same thing for any of the four operators and any number of numerals:

  candidate_table(vals, op)  every candidate pair and the result it gives under the row's op -- BOTH orders for sub
                             and div (x - y and y - x; x / y and y / x, exact integer quotients only), one entry per
                             unordered pair for add and mul;
  collisions(vals, op)       the attribution keys (sub: |x - y|; add: x + y; mul: x * y; div: the exact quotient in
                             either order) that two or more DIFFERENT pairs share -- a greedy integer equal to such a
                             key cannot be attributed to one pair;
  gold_unique_anyop(...)     the bank's one-pair-only rule, strict form: the only pair of the row's numerals that
                             gives |ans| under ANY of the four operators is the gold pair (so a pair+operator mix-up
                             can never look right), and the gold pair gives |ans| only under the gold operator;
  attribute(...)             label the host's greedy integer: right / wrong / collision / echo / unattributable / none,
                             plus exact (the signed answer itself) -- the same classes as host_selection.py.
gen_v5.py prefers draws with NO collision at all (so every greedy integer that equals any pair's result names one
pair) and records candidate_table + collision on every row (fields attr_pairs, attr_collision).
Indices are numeral positions in WRITTEN order, the same indexing as the finaliser's prov.gold_run_idx.
"""
import sys
sys.dont_write_bytecode = True   # no __pycache__: write nothing beyond the files the brief names
import argparse
import collections
import itertools
import json
import sys

OPS = ('add', 'sub', 'mul', 'div')
ROW_OP = {'addition': 'add', 'subtraction': 'sub', 'product': 'mul', 'division': 'div',
          'add': 'add', 'sub': 'sub', 'mul': 'mul', 'div': 'div'}


def op_result(op, x, y):
    """The result of `x op y`; None where it is not a whole number (division that does not come out even)."""
    if op == 'add':
        return x + y
    if op == 'mul':
        return x * y
    if op == 'sub':
        return x - y
    if op == 'div':
        return x // y if (y and x % y == 0) else None
    raise ValueError(op)


def key_of(op, r):
    """The attribution key: what a greedy integer is compared against. Subtraction by magnitude (the host's sign is
    judged separately, as in host_selection.py)."""
    return None if r is None else (abs(r) if op == 'sub' else r)


def candidate_table(vals, op):
    """[(i, j, result)] for every candidate pair; ordered (i != j) for sub/div, unordered (i < j) for add/mul."""
    op = ROW_OP[op]
    n = len(vals)
    if op in ('sub', 'div'):
        return [(i, j, op_result(op, vals[i], vals[j])) for i in range(n) for j in range(n) if i != j]
    return [(i, j, op_result(op, vals[i], vals[j])) for i, j in itertools.combinations(range(n), 2)]


def keyed_pairs(vals, op):
    """attribution key -> set of UNORDERED pairs (frozenset of two indices) that produce it under op."""
    out = collections.defaultdict(set)
    for i, j, r in candidate_table(vals, op):
        k = key_of(ROW_OP[op], r)
        if k is not None:
            out[k].add(frozenset((i, j)))
    return out


def collisions(vals, op):
    """{key: [pairs]} for every key two or more different pairs share (empty dict = fully attributable row)."""
    return {k: sorted(tuple(sorted(p)) for p in ps) for k, ps in keyed_pairs(vals, op).items() if len(ps) > 1}


def anyop_hits(vals, target):
    """{unordered pair: [ops]} of every pair that gives |target| under any operator (sub by magnitude, div exact in
    either order)."""
    t = abs(target)
    hits = collections.defaultdict(list)
    for i, j in itertools.combinations(range(len(vals)), 2):
        x, y = vals[i], vals[j]
        for op in OPS:
            rs = (op_result(op, x, y), op_result(op, y, x)) if op in ('sub', 'div') else (op_result(op, x, y),)
            if any(key_of('sub', r) == t if op == 'sub' else r == t for r in rs if r is not None):
                hits[(i, j)].append(op)
    return dict(hits)


def gold_unique_anyop(vals, gi, gj, op, ans):
    """(ok, reason). ok = the gold pair is the only pair giving |ans| under any operator, and only under its own op."""
    g = tuple(sorted((gi, gj)))
    hits = anyop_hits(vals, ans)
    others = [p for p in hits if p != g]
    if g not in hits or ROW_OP[op] not in hits[g]:
        return False, 'gold pair does not give the answer'
    if others:
        return False, 'second pair %s gives the answer under %s' % (others[0], hits[others[0]])
    if len(hits[g]) > 1:
        return False, 'gold pair also gives the answer under %s' % [o for o in hits[g] if o != ROW_OP[op]]
    return True, ''


def gold_unique_ownop(vals, gi, gj, op, ans):
    """The looser v4 rule (audit_bank_v4.py lines 72-74), reported beside the strict one: under the row's own op only."""
    op = ROW_OP[op]
    hits = [(i, j) for i, j, r in candidate_table(vals, op) if r is not None and key_of(op, r) == key_of(op, ans)]
    return len(set(frozenset(h) for h in hits)) == 1


def attribute(vals, op, gi, gj, ans, greedy):
    """Label the host's greedy integer on one row. Returns (label, detail).
       none           no integer in the continuation
       right          the greedy integer's key is produced by the gold pair and by no other pair
       collision      it is produced by the gold pair AND another pair (cannot be attributed)
       wrong          it is produced only by other pair(s) -> detail = those pairs
       echo           it equals a prompt numeral (copying, not computing)
       unattributable none of the above (arithmetic noise, a refusal, ...)
    detail['exact'] is True when the greedy integer equals the signed answer itself."""
    if greedy is None:
        return 'none', {}
    op = ROW_OP[op]
    g = int(greedy)
    k = abs(g) if op == 'sub' else g
    pairs = keyed_pairs(vals, op).get(k, set())
    gold = frozenset((gi, gj))
    det = {'exact': g == ans}
    if pairs:
        if gold in pairs:
            return ('right' if len(pairs) == 1 else 'collision'), det
        det['pairs'] = sorted(tuple(sorted(p)) for p in pairs)
        return 'wrong', det
    if k in set(abs(v) for v in vals):
        return 'echo', det
    return 'unattributable', det


def row_record(vals, op, gi, gj, ans):
    """The per-row fields gen_v5.py stores: attr_pairs [[i, j, result]], attr_collision, attr_collision_keys."""
    tab = candidate_table(vals, op)
    col = collisions(vals, op)
    return dict(attr_pairs=[[i, j, r] for i, j, r in tab], attr_collision=bool(col),
                attr_collision_keys=sorted(col), attr_gold=[gi, gj])


def selftest():
    ok = True

    def chk(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print('  %s  %s' % ('ok  ' if cond else 'FAIL', name))

    # subtraction: 7, 9, 5 with gold 7-5=2 -> 9-7 also 2: a collision on the gold key
    chk('sub 7,9,5: collision on key 2', collisions([7, 9, 5], 'sub') == {2: [(0, 1), (0, 2)]})
    chk('sub 7,9,5: gold not unique (any op)', not gold_unique_anyop([7, 9, 5], 0, 2, 'sub', 2)[0])
    chk('sub 7,9,5: greedy 2 -> collision', attribute([7, 9, 5], 'sub', 0, 2, 2, 2)[0] == 'collision')
    # subtraction, clean: 40, 17, 9 gold 40-17=23 (wrong pairs give 31 and 8)
    chk('sub 40,17,9 clean', collisions([40, 17, 9], 'sub') == {} and gold_unique_anyop([40, 17, 9], 0, 1, 'sub', 23)[0])
    chk('sub greedy -23 -> right, not exact', attribute([40, 17, 9], 'sub', 0, 1, 23, -23) == ('right', {'exact': False}))
    chk('sub greedy 31 -> wrong (0,2)', attribute([40, 17, 9], 'sub', 0, 1, 23, 31) == ('wrong', {'exact': False, 'pairs': [(0, 2)]}))
    chk('sub greedy 17 -> echo', attribute([40, 17, 9], 'sub', 0, 1, 23, 17)[0] == 'echo')
    chk('sub greedy 5 -> unattributable', attribute([40, 17, 9], 'sub', 0, 1, 23, 5)[0] == 'unattributable')
    chk('greedy None -> none', attribute([40, 17, 9], 'sub', 0, 1, 23, None)[0] == 'none')
    # addition: 12, 30, 18 gold 12+18=30 -> the answer is written (echo) ; 12, 25, 18 gold 12+18=30: 12+25=37, 25+18=43
    chk('add 12,25,18 clean and unique', collisions([12, 25, 18], 'add') == {} and gold_unique_anyop([12, 25, 18], 0, 2, 'add', 30)[0])
    chk('add greedy 43 -> wrong (1,2)', attribute([12, 25, 18], 'add', 0, 2, 30, 43)[1].get('pairs') == [(1, 2)])
    # cross-operator trap: add row 3, 4, 9 gold 3+9=12, but 3*4 = 12 too
    chk('add 3,4,9: 3*4 also gives 12 -> refused by the any-op rule', not gold_unique_anyop([3, 4, 9], 0, 2, 'add', 12)[0])
    chk('add 3,4,9: own-op rule alone passes it', gold_unique_ownop([3, 4, 9], 0, 2, 'add', 12))
    # multiplication: 6, 7, 3 gold 6*7=42; 7*3 = 21, 6*3 = 18
    chk('mul 6,7,3 clean', collisions([6, 7, 3], 'mul') == {} and gold_unique_anyop([6, 7, 3], 0, 1, 'mul', 42)[0])
    chk('mul collision 2,12,6,4', collisions([2, 12, 6, 4], 'mul') == {24: [(0, 1), (2, 3)]})
    # division, both orders: 84, 7, 12 gold 84/7=12 -> the answer is written; 84, 7, 21: 84/21=4 and 21/7=3
    chk('div table has both orders, exact only', sorted(r for _, _, r in candidate_table([84, 7, 21], 'div') if r is not None) == [3, 4, 12])
    chk('div 84,7,21 clean and unique', collisions([84, 7, 21], 'div') == {} and gold_unique_anyop([84, 7, 21], 0, 1, 'div', 12)[0])
    chk('div greedy 4 -> wrong (0,2)', attribute([84, 7, 21], 'div', 0, 1, 12, 4)[1].get('pairs') == [(0, 2)])
    chk('div 72,8,3 greedy 9 -> right', attribute([72, 8, 3], 'div', 0, 1, 9, 9)[0] == 'right')
    chk('div collision 36,4,9,3,12 (36/4=9 and 36/12=3 and 9/3=3, 12/4=3)', 3 in collisions([36, 4, 9, 3, 12], 'div'))
    # gold pair giving the answer under a second op: 4 - 2 = 2 = 4 / 2
    chk('sub 4,2,50: gold also gives 2 by division -> refused', not gold_unique_anyop([4, 2, 50], 0, 1, 'sub', 2)[0])
    rec = row_record([84, 7, 21], 'division', 0, 1, 12)
    chk('row_record fields', set(rec) == {'attr_pairs', 'attr_collision', 'attr_collision_keys', 'attr_gold'} and
        len(rec['attr_pairs']) == 6 and rec['attr_collision'] is False)
    print('SELFTEST host_attr_v5: %s' % ('0 fail' if ok else 'FAIL'))
    return ok


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--bank', default='')
    ap.add_argument('--greedy', default='', help='jsonl with row_id and greedy_int (e.g. a dump meta export)')
    a = ap.parse_args(argv[1:])
    if a.selftest or not a.bank:
        return 0 if selftest() else 1
    import re
    runs = re.compile(r'[0-9]+')
    greedy = {}
    if a.greedy:
        for line in open(a.greedy, encoding='utf-8'):
            r = json.loads(line)
            greedy[r['row_id']] = r.get('greedy_int')
    lab = collections.Counter()
    cells = collections.defaultdict(collections.Counter)
    ncol = n = 0
    for line in open(a.bank, encoding='utf-8'):
        r = json.loads(line)
        vals = [int(x) for x in runs.findall(r['text'])]
        gi, gj = vals.index(r['a']), vals.index(r['b'])
        n += 1
        ncol += bool(collisions(vals, r['op']))
        if a.greedy:
            l, _ = attribute(vals, r['op'], gi, gj, r['ans'], greedy.get(r['row_id']))
            lab[l] += 1
            cells['%s/%s' % (ROW_OP[r['op']], r.get('dist_arm'))][l] += 1
    print('rows %d; rows with any attribution collision %d/%d' % (n, ncol, n))
    if a.greedy:
        rw = lab['right'] + lab['wrong']
        print('labels %s; selection right/(right+wrong) %d/%d' % (dict(lab), lab['right'], rw))
        for k in sorted(cells):
            c = cells[k]
            print('  %-24s right %d wrong %d collision %d echo %d unattr %d none %d' % (
                k, c['right'], c['wrong'], c['collision'], c['echo'], c['unattributable'], c['none']))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
