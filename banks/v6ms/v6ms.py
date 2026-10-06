#!/usr/bin/env python3
"""v6ms.py -- BANK v6ms: a MULTILINGUAL MULTI-STEP bank (2-3 step chains, conditionals, selection, integer ops).

Every row's program and every intermediate value is known by construction. LLM writers (Opus low, one per writer unit =
one language x one stratum x one round, 8 templates) write story templates with number SLOTS; this tool fills them
exactly, many times over. Blind verifiers (Opus medium, one per verifier unit = 5 languages x one round) recover the
program from the text alone; a template is kept only when every one of its blind texts executes to the gold answer.

Design: PLAN_v6ms.md. Writer brief: BRIEF_v6ms_writer.md. Verifier brief: VERIFY_v6ms.md. stdlib only.

usage (every state is recomputed from the files on disk; nothing is appended, nothing overwritten):
  v6ms.py manifest                         write manifest/units.json (deterministic; refuses to change an existing one)
  v6ms.py status [--next K] [--kind writer|verifier] [--tier T1|T2|ALL] [--strata SL,CB,...]
  v6ms.py spec <writer unit>               the unit spec a writer works from (JSON)
  v6ms.py validate <writer file>           -> 'VALIDATE ok 8' or FAIL lines
  v6ms.py close <round|verifier unit>      accept validated units, build the blind + key files of ready verifier units
  v6ms.py format <verifier unit> <file>    verifier output format check -> 'FORMAT ok <n>'
  v6ms.py report                           VERIFY_REPORT_v6ms.md + VERIFY_DISAGREE_v6ms.jsonl (rewritten each time)
  v6ms.py clean <verifier unit>            clean/clean_<V>.json (never overwritten)
  v6ms.py gen --out-dir DIR [--include-unverified] [--units U1,U2]   fill rows (refuses a non-empty DIR)
  v6ms.py launch <round>                   the Workflow args for one chunk (= one round)
  v6ms.py wfjs                             (re)write wf_v6ms.js from the manifest
  v6ms.py selftest
"""
import sys
sys.dont_write_bytecode = True   # set BEFORE any import: never write __pycache__
import argparse
import ast
import collections
import glob
import hashlib
import json
import math
import os
import random
import re
import shutil
import tempfile
import time
import unicodedata
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(HERE, 'vendor')
PINS = {'validate_single.py': 'df1c37d9becc7b1ba552d89989e983f6'}   # copied from _role/singlestep/ (same md5)


def md5f(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


for _n, _m in PINS.items():
    if md5f(os.path.join(VENDOR, _n)) != _m:
        raise SystemExit('REFUSE: vendor/%s md5 changed (pinned %s)' % (_n, _m))
sys.path.insert(0, VENDOR)
import validate_single as VS  # noqa: E402  (leaf checks: digit_chars, number_words_in, script_problem, file_script_problems)

DATA = json.load(open(os.path.join(VENDOR, 'v5_data.json'), encoding='utf-8'))
SLICES = [tuple(s) for s in DATA['slices']]

# ------------------------------------------------------------------ paths
MANIFEST = os.path.join(HERE, 'manifest', 'units.json')
WRITERS = os.path.join(HERE, 'writers')
ACCEPT = os.path.join(HERE, 'accept')
BLIND = os.path.join(HERE, 'blind')
BLIND_KEY = os.path.join(HERE, 'blind_key')
VERIFY = os.path.join(HERE, 'verify')
CLEAN = os.path.join(HERE, 'clean')
ENABLED = os.path.join(HERE, 'manifest', 'ENABLED_STRATA.json')
TOOL = os.path.abspath(__file__)

# ------------------------------------------------------------------ languages, groups, folds
LANGS = ('en', 'de', 'es', 'pl', 'ru', 'el', 'tr', 'ar', 'he', 'fa', 'hi', 'bn', 'ta', 'th', 'vi', 'id', 'sw', 'zh',
         'ja', 'ko')
GROUPS = (('G1', ('en', 'de', 'es', 'pl', 'ru')), ('G2', ('el', 'tr', 'ar', 'he', 'fa')),
          ('G3', ('hi', 'bn', 'ta', 'th', 'vi')), ('G4', ('id', 'sw', 'zh', 'ja', 'ko')))
# leave-language-out folds (PLAN section 6): each fold mixes scripts and families; weak-bank languages spread out
LANG_FOLDS = {'en': 1, 'ar': 1, 'ta': 1, 'ja': 1, 'de': 2, 'he': 2, 'th': 2, 'zh': 2, 'es': 3, 'fa': 3, 'vi': 3,
              'ko': 3, 'ru': 4, 'hi': 4, 'sw': 4, 'id': 4, 'pl': 5, 'el': 5, 'tr': 5, 'bn': 5}
# the alternative (decision D5 b): whole script families held out together
SCRIPT_FOLDS = {'en': 'latin', 'de': 'latin', 'es': 'latin', 'pl': 'latin', 'tr': 'latin', 'vi': 'latin',
                'id': 'latin', 'sw': 'latin', 'ru': 'greek_cyrillic', 'el': 'greek_cyrillic', 'ar': 'abjad',
                'he': 'abjad', 'fa': 'abjad', 'hi': 'brahmic', 'bn': 'brahmic', 'ta': 'brahmic', 'th': 'brahmic',
                'zh': 'cjk', 'ja': 'cjk', 'ko': 'cjk'}
NOSPACE = {'ja', 'zh'}
LEAD_IN = DATA['lead_in']
LANG_NAMES = DATA['names']

# ------------------------------------------------------------------ rounds, strata, tiers
STRATA = ('SL', 'CB', 'SEL', 'INT', 'REP', 'INV', 'CMQ', 'RAT', 'PCT', 'CNV', 'BKP', 'DST')
GEN_OF_STRATUM = {'SL': 'G1', 'CB': 'G2', 'SEL': 'G2', 'INT': 'G2', 'REP': 'G2', 'INV': 'G3', 'CMQ': 'G3',
                  'RAT': 'G3', 'PCT': 'G3', 'CNV': 'G3', 'BKP': 'G3', 'DST': 'G3'}
STRATUM_NAMES = {'SL': 'straight-line 2-3 step chains', 'CB': 'conditionals (a comparison picks the branch)',
                 'SEL': 'comparison-based selection (max / min)', 'INT': 'integer ops (ceil / floor division, remainder)',
                 'REP': 'bounded repetition (each period for N periods)',
                 'INV': 'inverse / unknown start ("how many did she have at first")',
                 'CMQ': 'comparison questions ("how many more / fewer")', 'RAT': 'rates and unit prices',
                 'PCT': 'percent and fraction-of', 'CNV': 'unit conversions with a stated constant',
                 'BKP': 'multi-entity bookkeeping (transfers between owners)',
                 'DST': 'a written number of the scene is a distractor (a role the question does not use)'}
GENERATIONS = {
    'G1': 'straight-line 2-3 step chains (+ - * /, signed), the 20 core languages',
    'G2': 'conditionals / branches, max-min selection, ceil / floor / remainder (+ bounded repetition, off)',
    'G3': 'varied question types: inverse / unknown start, comparison, rates and unit prices, percent and fraction-of, '
          'unit conversions with stated constants, multi-entity bookkeeping, written-number distractors',
    'G4a': 'language expansion to the 36 remaining bank languages (v5x set) -- NOT BUILT: needs the v5x per-language '
           'validators ported into vendor/ (PLAN D13)',
    'G4b': 'distractor / paraphrase pass over VERIFIED templates (new surface, same program) -- NOT BUILT: unit type '
           'designed in PLAN section 3b (D14)'}
G4A_LANGS = ('bg', 'cs', 'hu', 'ro', 'sk', 'sr', 'eu', 'fi', 'is', 'la', 'lt', 'sv', 'gu', 'kn', 'ml', 'mr', 'pa', 'te',
             'hy', 'ka', 'kk', 'mn', 'sq', 'uz', 'ha', 'ms', 'ne', 'tl', 'ur', 'zu', 'am', 'bo', 'km', 'my', 'si', 'yo')


def _rounds():
    R = [('G1r%02d' % (i + 1), 'G1', 'SL') for i in range(8)]
    R += [('G2r%02d' % (i + 1), 'G2', s) for i, s in enumerate(['CB', 'SEL', 'INT'] * 4)]
    R += [('G2r13', 'G2', 'REP'), ('G2r14', 'G2', 'REP')]
    R += [('G3r%02d' % (i + 1), 'G3', s) for i, s in enumerate(['INV', 'CMQ', 'RAT', 'PCT', 'CNV', 'BKP', 'DST'] * 2)]
    return R


ROUNDS3 = _rounds()
ROUNDS = [(r, s) for r, _, s in ROUNDS3]
GEN_OF_ROUND = {r: g for r, g, _ in ROUNDS3}
TIERS = {'T1': {'G1r%02d' % i for i in range(1, 5)} | {'G2r%02d' % i for i in range(1, 7)} | {'G3r%02d' % i for i in range(1, 8)},
         'T2': {'G1r%02d' % i for i in range(1, 9)} | {'G2r%02d' % i for i in range(1, 13)}
         | {'G3r%02d' % i for i in range(1, 15)},
         'ALL': {r for r, _ in ROUNDS}}
DEFAULT_ENABLED = [s for s in STRATA if s != 'REP']    # REP off until the project owner says otherwise (PLAN decision D3)
GATES = {'G2': 'G1r01', 'G3': 'G1r01'}     # a generation's units are offered once its gate round passes its bars
UNIT_TEMPLATES = 8
PILOT_UNITS = ('W6-en-SL-G1r01', 'W6-zh-SL-G1r01')
PILOT_V = 'V6-PILOT'

# ------------------------------------------------------------------ program shapes
# A statement: dict(id, k, args, guard). k in + - * / cdiv fdiv mod max min > >= < <= sel rep+ rep-.
# args: leaf letters A-D or statement ids s1..; 'sel' args = (cond, then, else); guard = None | [cond id, bool].
NONCOMM = {'-', '/', 'cdiv', 'fdiv', 'mod', '>', '>=', '<', '<=', 'rep+', 'rep-'}
CMPS = ('>', '>=', '<', '<=')
SYM = {'+': '+', '-': '-', '*': '*', '/': '/'}
PRETTY = {'+': '+', '-': '−', '*': '×', '/': '÷', '>': '>', '>=': '≥', '<': '<', '<=': '≤'}


def S(i, k, args, guard=None):
    return dict(id='s%d' % i, k=k, args=list(args), guard=guard)


def shape_prog(shape, p):
    """(statements, order-test statement ids) for a shape and its parameters p."""
    if shape == 'S2L':
        return [S(1, p['o1'], 'AB'), S(2, p['o2'], ['s1', 'C'])], ['s1', 's2']
    if shape == 'S2R':
        return [S(1, p['o2'], 'BC'), S(2, p['o1'], ['A', 's1'])], ['s1', 's2']
    if shape == 'S3L':
        return [S(1, p['o1'], 'AB'), S(2, p['o2'], ['s1', 'C']), S(3, p['o3'], ['s2', 'D'])], ['s1', 's2', 's3']
    if shape == 'S3B':
        return [S(1, p['o1'], 'AB'), S(2, p['o3'], 'CD'), S(3, p['o2'], ['s1', 's2'])], ['s1', 's2', 's3']
    if shape == 'CBT':
        return [S(1, p['o1'], 'AB'), S(2, p['cmp'], ['s1', 'C']), S(3, p['o2'], ['s1', 'D'], ['s2', True]),
                S(4, 'sel', ['s2', 's3', 's1'])], ['s2', 's3']
    if shape == 'CBE':
        return [S(1, p['o1'], 'AB'), S(2, p['cmp'], ['s1', 'C']), S(3, p['o2'], ['s1', 'D'], ['s2', True]),
                S(4, p['o3'], ['s1', 'D'], ['s2', False]), S(5, 'sel', ['s2', 's3', 's4'])], ['s2', 's3', 's4']
    if shape == 'CBA':
        return [S(1, '>', 'AB'), S(2, '-', 'AB', ['s1', True]), S(3, '-', 'BA', ['s1', False]),
                S(4, 'sel', ['s1', 's2', 's3']), S(5, p['o2'], ['s4', 'C'])], ['s5']
    if shape == 'SL1':
        return [S(1, p['f'], 'AB'), S(2, p['o'], ['s1', 'C'])], ['s2']
    if shape == 'SL2':
        return [S(1, p['o1'], 'AB'), S(2, p['o1'], 'CD'), S(3, p['f'], ['s1', 's2'])], ['s1', 's2']
    if shape == 'ICE':
        return [S(1, p['o1'], 'AB'), S(2, 'cdiv', ['s1', 'C'])], ['s1', 's2']
    if shape == 'IFL':
        return [S(1, p['o1'], 'AB'), S(2, 'fdiv', ['s1', 'C'])], ['s1', 's2']
    if shape == 'IMO':
        return [S(1, p['o1'], 'AB'), S(2, 'mod', ['s1', 'C'])], ['s1', 's2']
    if shape == 'IC2':
        return [S(1, 'cdiv', 'AB'), S(2, p['o2'], ['s1', 'C'])], ['s1', 's2']
    if shape == 'RPA':
        return [S(1, 'rep' + p['o'], 'ABC')], ['s1']
    if shape == 'IVA':          # unknown start: start (-A +B | +A -B) = C, so start = (C o1 A) o2 B
        return [S(1, p['o1'], 'CA'), S(2, p['o2'], ['s1', 'B'])], ['s1', 's2']
    if shape == 'IVM':          # A equal groups plus B loose make C: group size = (C - B) / A
        return [S(1, '-', 'CB'), S(2, '/', ['s1', 'A'])], ['s1', 's2']
    if shape == 'CMQ':          # how many more: (A o1 B) - C
        return [S(1, p['o1'], 'AB'), S(2, '-', ['s1', 'C'])], ['s1', 's2']
    if shape == 'RTU':          # unit rate then scale: (B / A) x C
        return [S(1, '/', 'BA'), S(2, '*', ['s1', 'C'])], ['s1']
    if shape == 'RTS':          # rate difference over a time: (A - B) x C
        return [S(1, '-', 'AB'), S(2, '*', ['s1', 'C'])], ['s1']
    if shape == 'PCD':          # percent change of a base: B o pct(A, B)
        return [S(1, 'pct', 'AB'), S(2, p['o'], ['B', 's1']), S(3, '*', ['s2', 'C'])], ['s2']
    if shape == 'PCF':          # A out of every B, of C: (C / B) x A
        return [S(1, '/', 'CB'), S(2, '*', ['s1', 'A'])], ['s1']
    if shape == 'CNV':          # A big units of B small units each, then o2 C small units
        return [S(1, '*', 'AB'), S(2, p['o2'], ['s1', 'C'])], ['s2']
    if shape == 'BK1':          # owner starts with A, receives B, gives away C (another owner's count is {T})
        return [S(1, '+', 'AB'), S(2, '-', ['s1', 'C'])], ['s2']
    if shape == 'BK2':          # owner 1 has A, owner 2 has B, owner 1 gives C to owner 2: how many more has owner 2
        return [S(1, '+', 'BC'), S(2, '-', 'AC'), S(3, '-', ['s1', 's2'])], ['s2', 's3']
    if shape in ('DSL', 'DSR'):  # straight-line programs with a role distractor {U} in the scene
        return shape_prog('S2L' if shape == 'DSL' else 'S2R', p)
    raise ValueError(shape)


def signable(cell):
    """the subtraction steps a writer may mark signed (a negative result natural)"""
    if cell['stratum'] in ('SL', 'DST'):
        return [st['id'] for st in cell['prog'] if st['k'] == '-' and not st.get('guard')]
    if cell['shape'] == 'BK2':
        return ['s3']
    return []


STRATUM_OF = {'S2L': 'SL', 'S2R': 'SL', 'S3L': 'SL', 'S3B': 'SL', 'CBT': 'CB', 'CBE': 'CB', 'CBA': 'CB',
              'SL1': 'SEL', 'SL2': 'SEL', 'ICE': 'INT', 'IFL': 'INT', 'IMO': 'INT', 'IC2': 'INT', 'RPA': 'REP',
              'IVA': 'INV', 'IVM': 'INV', 'CMQ': 'CMQ', 'RTU': 'RAT', 'RTS': 'RAT', 'PCD': 'PCT', 'PCF': 'PCT',
              'CNV': 'CNV', 'BK1': 'BKP', 'BK2': 'BKP', 'DSL': 'DST', 'DSR': 'DST'}
ROLE_U = {'DSL', 'DSR'}              # shapes with the role distractor slot {U}
PCT_SHAPES = {'PCD'}                 # shapes whose texts may write '%' right after a slot
OPS4 = ('+', '-', '*', '/')
COMBOS2 = [(a, b) for a in OPS4 for b in OPS4]
COMBOS3 = [(a, b, c) for a in OPS4 for b in OPS4 for c in OPS4]


def unit_cells(lang, stratum, j):
    """The 8 cells of the j-th unit (0-based) of `stratum` in `lang`: [(shape, params)]."""
    li = LANGS.index(lang)
    cells = []
    if stratum == 'SL':
        for c in range(2):
            o1, o2 = COMBOS2[(li * 7 + j * 2 + c) % 16]
            cells.append(('S2L', dict(o1=o1, o2=o2)))
            o1, o2 = COMBOS2[(li * 7 + j * 2 + c + 5) % 16]
            cells.append(('S2R', dict(o1=o1, o2=o2)))
            o1, o2, o3 = COMBOS3[(li * 13 + j * 2 + c) % 64]
            cells.append(('S3L', dict(o1=o1, o2=o2, o3=o3)))
            o1, o2, o3 = COMBOS3[(li * 13 + j * 2 + c + 29) % 64]
            cells.append(('S3B', dict(o1=o1, o2=o2, o3=o3)))
    elif stratum == 'CB':
        for c in range(3):
            n = li * 3 + j * 3 + c
            cells.append(('CBT', dict(o1='+*'[n % 2], cmp=CMPS[(n // 2) % 4], o2='-+'[(n // 8) % 2])))
        for c in range(3):
            n = li * 3 + j * 3 + c + 1
            o2, o3 = (('-', '+'), ('+', '-'))[n % 2]
            cells.append(('CBE', dict(o1='+*'[(n // 2) % 2], cmp=CMPS[(n // 4) % 4], o2=o2, o3=o3)))
        for c in range(2):
            cells.append(('CBA', dict(o2='*+/'[(li + j * 2 + c) % 3])))
    elif stratum == 'SEL':
        for c in range(4):
            n = li + j * 4 + c
            cells.append(('SL1', dict(f=('max', 'min')[n % 2], o='*+-'[(n // 2) % 3])))
        for c in range(4):
            n = li + j * 4 + c + 1
            cells.append(('SL2', dict(f=('max', 'min')[n % 2], o1='*+'[(n // 2) % 2])))
    elif stratum == 'INT':
        for c in range(2):
            n = li + j * 2 + c
            cells.append(('ICE', dict(o1='+*-'[n % 3])))
            cells.append(('IFL', dict(o1='+*-'[(n + 1) % 3])))
            cells.append(('IMO', dict(o1='+*-'[(n + 2) % 3])))
            cells.append(('IC2', dict(o2='*+'[n % 2])))
    elif stratum == 'REP':
        for c in range(8):
            cells.append(('RPA', dict(o='+-'[(li + j + c) % 2])))
    elif stratum == 'INV':
        for c in range(4):
            o1, o2 = (('+', '-'), ('-', '+'))[(li + j + c) % 2]
            cells.append(('IVA', dict(o1=o1, o2=o2)))
        cells += [('IVM', {})] * 4
    elif stratum == 'CMQ':
        for c in range(8):
            cells.append(('CMQ', dict(o1='+-*'[(li + j * 8 + c) % 3])))
    elif stratum == 'RAT':
        cells += [('RTU', {})] * 4 + [('RTS', {})] * 4
    elif stratum == 'PCT':
        for c in range(4):
            cells.append(('PCD', dict(o='-+'[(li + j + c) % 2])))
        cells += [('PCF', {})] * 4
    elif stratum == 'CNV':
        for c in range(8):
            cells.append(('CNV', dict(o2='+-'[(li + j + c) % 2])))
    elif stratum == 'BKP':
        cells += [('BK1', {})] * 4 + [('BK2', {})] * 4
    elif stratum == 'DST':
        for c in range(4):
            o1, o2 = COMBOS2[(li * 7 + j * 4 + c * 3) % 16]
            cells.append(('DSL', dict(o1=o1, o2=o2)))
            o1, o2 = COMBOS2[(li * 7 + j * 4 + c * 3 + 8) % 16]
            cells.append(('DSR', dict(o1=o1, o2=o2)))
    out = []
    for c, (shape, p) in enumerate(cells):
        prog, otest = shape_prog(shape, p)
        sm = stmt_map(prog)
        otest = [x for x in otest if sm[x]['k'] in NONCOMM       # only non-commutative steps test order,
                 and order_sets(dict(prog=prog), x)]              # and only when each side has a leaf of its own
        out.append(dict(cell_id='c%d' % (c + 1), stratum=stratum, shape=shape, params=p, prog=prog,
                        order_test=otest, leaves=leaves_of(prog), role_u=(shape in ROLE_U),
                        pct_ok=(shape in PCT_SHAPES),
                        t_position=('before', 'between', 'after')[(li + j + c) % 3]))
    return out


def leaves_of(prog):
    seen = []
    for st in prog:
        for a in st['args']:
            if len(a) == 1 and a not in seen:
                seen.append(a)
    return sorted(seen)


def stmt_map(prog):
    return {st['id']: st for st in prog}


def leafset(prog, x):
    m = stmt_map(prog)
    if x in m:
        st = m[x]
        args = st['args'][1:] if st['k'] == 'sel' else st['args']
        return set().union(*[leafset(prog, a) for a in args])
    return {x}


def expr(prog, x=None, letters=None):
    """DSL expression of statement x (default: the last one); letters maps leaf -> name."""
    m = stmt_map(prog)
    x = x or prog[-1]['id']
    L = letters or {}
    if x not in m:
        return L.get(x, x)
    st = m[x]
    k, a = st['k'], [expr(prog, y, letters) for y in st['args']]
    if k in SYM:
        return '(%s %s %s)' % (a[0], SYM[k], a[1])
    if k in CMPS:
        return '%s %s %s' % (a[0], k, a[1])
    if k == 'sel':
        return 'ifelse(%s, %s, %s)' % tuple(a)
    if k == 'cdiv':
        return 'ceil(%s / %s)' % tuple(a)
    if k == 'fdiv':
        return 'floor(%s / %s)' % tuple(a)
    if k in ('mod', 'max', 'min', 'pct'):
        return '%s(%s, %s)' % (k, a[0], a[1])
    if k in ('rep+', 'rep-'):
        return '(%s %s %s * %s)' % (a[0], k[3], a[2], a[1])
    raise ValueError(k)


def strip_outer(s):
    if s.startswith('(') and s.endswith(')'):
        d = 0
        for i, c in enumerate(s):
            d += c == '('
            d -= c == ')'
            if d == 0 and i < len(s) - 1:
                return s
        return s[1:-1]
    return s


def readable(cell):
    """The plain program a writer works from (English, the slots kept)."""
    prog, p, sh = cell['prog'], cell['params'], cell['shape']
    pe = lambda x: strip_outer(expr(prog, x)).replace('*', '×').replace('/', '÷').replace(' - ', ' − ')  # noqa: E731
    if sh in ('S2L', 'S2R', 'S3L', 'S3B', 'DSL', 'DSR'):
        lines = []
        for st in prog:
            lines.append('%s = %s' % ('answer' if st is prog[-1] else st['id'], pe_stmt(st)))
        out = '; '.join(lines) + '   [in one line: answer = %s]' % pe(None)
        if sh in ROLE_U:
            out += ('   PLUS {U}: a number of the same scene in a DIFFERENT role (a capacity, a price, a size, a '
                    'count of something else) that the question does not use')
        return out
    if sh == 'CBT':
        return ('total = %s; IF total %s C THEN answer = total %s D ELSE answer = total'
                % (pe('s1'), PRETTY[p['cmp']], PRETTY[p['o2']]))
    if sh == 'CBE':
        return ('total = %s; IF total %s C THEN answer = total %s D ELSE answer = total %s D'
                % (pe('s1'), PRETTY[p['cmp']], PRETTY[p['o2']], PRETTY[p['o3']]))
    if sh == 'CBA':
        return ('IF A > B THEN gap = A − B ELSE gap = B − A (the gap is always the larger minus the smaller); '
                'answer = gap %s C' % PRETTY[p['o2']])
    if sh == 'SL1':
        return '%s = the %s of A and B; answer = %s %s C' % (
            'pick', 'LARGER' if p['f'] == 'max' else 'SMALLER', 'pick', PRETTY[p['o']])
    if sh == 'SL2':
        return ('first = A %s B; second = C %s D; answer = the %s of first and second'
                % (PRETTY[p['o1']], PRETTY[p['o1']], 'LARGER' if p['f'] == 'max' else 'SMALLER'))
    if sh in ('ICE', 'IFL', 'IMO'):
        how = {'ICE': 'answer = total ÷ C ROUNDED UP to a whole number (e.g. how many buses / boxes / trips are needed)',
               'IFL': 'answer = total ÷ C ROUNDED DOWN (e.g. how many FULL boxes / complete sets can be made)',
               'IMO': 'answer = the REMAINDER of total ÷ C (how many are left over after making as many full groups '
                      'of C as possible)'}[sh]
        return 'total = %s; %s' % (pe('s1'), how)
    if sh == 'IC2':
        return ('count = A ÷ B ROUNDED UP (how many are needed); answer = count %s C' % PRETTY[p['o2']])
    if sh == 'RPA':
        return ('start = A; in EACH of C periods (days, weeks, rounds) the amount %s by B; answer = the amount after '
                'the C periods (= A %s C × B)' % ('grows' if p['o'] == '+' else 'shrinks', '+' if p['o'] == '+' else '−'))
    if sh == 'IVA':
        ev = 'gave away / lost A, then received / gained B' if p['o1'] == '+' else 'received / gained A, then gave away / lost B'
        return 'an UNKNOWN start; the owner %s, ending with C; answer = the start (= %s)' % (ev, pe(None))
    if sh == 'IVM':
        return ('A equal groups (boxes, rows) of UNKNOWN size plus B loose items make C items in all; answer = the size '
                'of one group (= (C − B) ÷ A)')
    if sh == 'CMQ':
        return ('amount = %s; answer = how many MORE the amount is than C (or how many FEWER C is), always positive'
                % pe('s1'))
    if sh == 'RTU':
        return 'rate = B ÷ A (B for A: a unit price, a speed, a per-item amount); answer = rate × C'
    if sh == 'RTS':
        return 'A per unit of time against B per unit of time (A is the faster); answer = (A − B) × C units of time'
    if sh == 'PCD':
        return ('B is a base amount (a price, a wage, a weight); A percent of it (A%% of B) is %s; then C of them: '
                'answer = (B %s A%% of B) × C' % ('taken off' if p['o'] == '-' else 'added', PRETTY[p['o']]))
    if sh == 'PCF':
        return 'A out of every B (a fraction A/B written in words with slots), of C in all; answer = C ÷ B × A'
    if sh == 'CNV':
        return ('A big units, each worth B small units (B is a STATED conversion: "one crate holds {B} cans"); answer = '
                'A × B %s C small units' % PRETTY[p['o2']])
    if sh == 'BK1':
        return 'one owner starts with A, receives B from a second owner, then gives C to a third; answer = A + B − C'
    if sh == 'BK2':
        return ('owner 1 has A, owner 2 has B; owner 1 gives C to owner 2; answer = how many more owner 2 now has than '
                'owner 1 = (B + C) − (A − C), negative when owner 1 still has more')
    raise ValueError(sh)


def pe_stmt(st):
    return '%s %s %s' % (st['args'][0], PRETTY[st['k']], st['args'][1])


# ------------------------------------------------------------------ exact execution
class Bad(Exception):
    pass


def execute(prog, env):
    """{id: value} for every statement (untaken arms are computed too) + the executed flag per statement."""
    v = {k: Fraction(x) for k, x in env.items()}
    out, exe = {}, {}
    for st in prog:
        k, a = st['k'], [v[x] if not isinstance(v[x], bool) else v[x] for x in st['args']]
        if k == '+':
            r = a[0] + a[1]
        elif k == '-':
            r = a[0] - a[1]
        elif k == '*':
            r = a[0] * a[1]
        elif k == '/':
            if a[1] == 0:
                raise Bad('div0')
            r = a[0] / a[1]
        elif k in ('cdiv', 'fdiv', 'mod'):
            if a[1] == 0:
                raise Bad('div0')
            q = a[0] / a[1]
            r = Fraction(math.ceil(q)) if k == 'cdiv' else Fraction(math.floor(q)) if k == 'fdiv' else a[0] - a[1] * math.floor(q)
        elif k == 'pct':
            r = a[0] * a[1] / 100
        elif k == 'max':
            r = max(a)
        elif k == 'min':
            r = min(a)
        elif k in CMPS:
            r = {'>': a[0] > a[1], '>=': a[0] >= a[1], '<': a[0] < a[1], '<=': a[0] <= a[1]}[k]
        elif k == 'sel':
            r = a[1] if a[0] else a[2]
        elif k in ('rep+', 'rep-'):
            n = a[2]
            r = a[0] + n * a[1] if k == 'rep+' else a[0] - n * a[1]
        else:
            raise ValueError(k)
        v[st['id']] = r
        out[st['id']] = r
        g = st.get('guard')
        exe[st['id']] = True if not g else (bool(v[g[0]]) == g[1])
    return out, exe


# ------------------------------------------------------------------ the DSL (gold programs and verifier answers)
FUNCS = {'ceil', 'floor', 'mod', 'max', 'min', 'ifelse', 'pct'}
LETTER = re.compile(r'^[A-H]$')


def parse_dsl(s):
    """ast of a DSL expression, or raises ValueError. Allowed: letters A-H, + - * /, ceil floor mod max min ifelse pct,
    comparisons > >= < <= (as the first argument of ifelse), parentheses. No numbers."""
    if not isinstance(s, str) or not s.strip():
        raise ValueError('empty program')
    s = s.replace('×', '*').replace('÷', '/').replace('−', '-').replace('≥', '>=').replace('≤', '<=')
    try:
        t = ast.parse(s.strip(), mode='eval').body
    except SyntaxError as e:
        raise ValueError('syntax: %s' % e.msg)

    def walk(n, cond_ok=False):
        if isinstance(n, ast.Name):
            if not LETTER.match(n.id):
                raise ValueError('unknown name %r (only slot letters A-H)' % n.id)
            return
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            walk(n.left); walk(n.right)
            return
        if isinstance(n, ast.Compare) and cond_ok and len(n.ops) == 1 and isinstance(
                n.ops[0], (ast.Gt, ast.GtE, ast.Lt, ast.LtE)):
            walk(n.left); walk(n.comparators[0])
            return
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS and not n.keywords:
            want = {'ceil': 1, 'floor': 1, 'mod': 2, 'max': 2, 'min': 2, 'ifelse': 3, 'pct': 2}[n.func.id]
            if len(n.args) != want:
                raise ValueError('%s takes %d arguments' % (n.func.id, want))
            for i, a in enumerate(n.args):
                walk(a, cond_ok=(n.func.id == 'ifelse' and i == 0))
            return
        if isinstance(n, ast.Constant):
            raise ValueError('numbers are not allowed in a program (use the slot letters)')
        raise ValueError('not allowed: %s' % type(n).__name__)
    walk(t)
    return t


def dsl_letters(s):
    t = parse_dsl(s)
    fn = {id(n.func) for n in ast.walk(t) if isinstance(n, ast.Call)}
    return sorted({n.id for n in ast.walk(t) if isinstance(n, ast.Name) and id(n) not in fn})


def eval_dsl(s, env):
    t = parse_dsl(s)

    def ev(n):
        if isinstance(n, ast.Name):
            if n.id not in env:
                raise Bad('letter %s not in this text' % n.id)
            return Fraction(env[n.id])
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Add):
                return a + b
            if isinstance(n.op, ast.Sub):
                return a - b
            if isinstance(n.op, ast.Mult):
                return a * b
            if b == 0:
                raise Bad('div0')
            return a / b
        if isinstance(n, ast.Compare):
            a, b = ev(n.left), ev(n.comparators[0])
            o = n.ops[0]
            return (a > b if isinstance(o, ast.Gt) else a >= b if isinstance(o, ast.GtE) else
                    a < b if isinstance(o, ast.Lt) else a <= b)
        f = n.func.id
        if f == 'ifelse':
            return ev(n.args[1]) if ev(n.args[0]) else ev(n.args[2])
        a = [ev(x) for x in n.args]
        if f == 'ceil':
            return Fraction(math.ceil(a[0]))
        if f == 'floor':
            return Fraction(math.floor(a[0]))
        if f == 'mod':
            if a[1] == 0:
                raise Bad('div0')
            return a[0] - a[1] * math.floor(a[0] / a[1])
        if f == 'pct':
            return a[0] * a[1] / 100
        return max(a) if f == 'max' else min(a)
    return ev(t)


# ------------------------------------------------------------------ the filler
SEED = 20261002
CAT = {0: (2, 19), 1: (11, 99), 2: (101, 999), 3: (1001, 9999)}
MAXV = 999999
ONE_STEP_RETRIES = 12                 # redraws to avoid a one-step shortcut to the answer (kept + counted if all hit)


def seeded(*parts):
    h = hashlib.blake2b(('|'.join(str(p) for p in parts)).encode('utf-8'), digest_size=8).digest()
    return random.Random(int.from_bytes(h, 'big') ^ SEED)


def leaf_roles(prog):
    """{leaf: role} with role 'div' (exact divisor), 'idiv' (ceil/floor/mod divisor), 'count' (repetition count),
    'mulf' (a factor), 'plain'."""
    roles = {}
    for st in prog:
        k, a = st['k'], st['args']
        if k == '/' and len(a[1]) == 1:
            roles[a[1]] = 'div'
        elif k == '/':
            for x in leafset(prog, a[1]):
                roles[x] = 'divsub'
        if k in ('cdiv', 'fdiv', 'mod') and len(a[1]) == 1:
            roles[a[1]] = 'idiv'
        if k in ('rep+', 'rep-'):
            roles[a[2]] = 'count'
        if k == 'pct':
            roles[a[0]] = 'pct'
            roles[a[1]] = 'pctbase'
        if k == '*':
            for x in a:
                if len(x) == 1:
                    roles.setdefault(x, 'mulf')
    for x in leaves_of(prog):
        roles.setdefault(x, 'plain')
    return roles


def leaf_range(role, cat):
    if role == 'div':
        return (2, 12)
    if role == 'divsub':
        return (2, 9)
    if role == 'idiv':
        return (3, 40)
    if role == 'count':
        return (2, 6)
    if role == 'pct':
        return (2, 95)
    if role == 'pctbase':
        return (20, 999)
    if role == 'mulf':
        return CAT[min(cat, 2)]
    return CAT[cat]


def flip_kind(cell, signed):
    prog = cell['prog']
    for st in prog:
        if st['k'] in CMPS:
            return ('cond', st['id'])
    for st in prog:
        if st['k'] in ('max', 'min'):
            return ('sel', st['id'])
    for st in prog:
        if st['k'] == '-' and signed.get(st['id']):
            return ('sub', st['id'])
    return (None, None)


def numeric(st):
    return st['k'] not in CMPS


def passthrough(st):
    return st['k'] in ('sel', 'max', 'min')


def check_values(cell, signed, env, twin):
    """(vals, exe) if the leaf assignment satisfies every constraint for this twin, else raises Bad(reason)."""
    prog = cell['prog']
    vals, exe = execute(prog, env)
    m = stmt_map(prog)
    fk, fid = flip_kind(cell, signed)
    for st in prog:
        r = vals[st['id']]
        if isinstance(r, bool):
            a = [vals.get(x, Fraction(env.get(x, 0))) for x in st['args']]
            if a[0] == a[1]:
                raise Bad('cmp_tie')
            continue
        if r.denominator != 1:
            raise Bad('nonint')
        if abs(r) > MAXV:
            raise Bad('big')
        if not exe[st['id']]:
            continue
        if r == 0:
            raise Bad('zero')
        k = st['k']
        a = [vals[x] if x in vals else Fraction(env[x]) for x in st['args']]
        if k == 'pct' and r.denominator != 1:
            raise Bad('pct_frac')
        if k == '-' and r < 0 and not signed.get(st['id']):
            raise Bad('neg_unsigned')
        if k in ('+', '*', '/', 'cdiv', 'fdiv', 'mod', 'rep+', 'rep-', 'pct') and STRATUM_OF[cell['shape']] not in ('SL', 'DST') and r < 0:
            raise Bad('neg')
        if k == '/' and abs(a[1]) < 2:
            raise Bad('div1')
        if k in ('cdiv', 'fdiv', 'mod'):
            if a[0] <= 0 or a[1] < 2 or (a[0] / a[1]).denominator == 1:
                raise Bad('exact_or_neg')
            if k == 'fdiv' and r < 1:
                raise Bad('fdiv0')
        if k in ('max', 'min') and a[0] == a[1]:
            raise Bad('sel_tie')
        if k == 'rep-' and a[0] - a[2] * a[1] <= 0:
            raise Bad('rep_neg')
    sh = cell['shape']
    if sh == 'IVA' and cell['params']['o1'] == '+' and env['C'] <= env['B']:
        raise Bad('iva_story_state')          # start - A = C - B must stay positive
    if sh == 'PCF' and env['A'] >= env['B']:
        raise Bad('pcf_fraction')             # A out of every B needs A < B
    if sh == 'RTS' and env['A'] <= env['B']:
        raise Bad('rts_order')
    if sh == 'BK2' and env['A'] <= env['C']:
        raise Bad('bk2_gives_more_than_has')
    # the twin's flip
    if fk == 'cond':
        if bool(vals[fid]) != (twin == 0):
            raise Bad('flip')
    elif fk == 'sel':
        st = m[fid]
        a = [vals[x] if x in vals else Fraction(env[x]) for x in st['args']]
        if (vals[fid] == a[0]) != (twin == 0):
            raise Bad('flip')
    elif fk == 'sub':
        st = m[fid]
        a = [vals[x] if x in vals else Fraction(env[x]) for x in st['args']]
        if (a[0] < a[1]) != (twin == 1):
            raise Bad('flip')
    fin = vals[prog[-1]['id']]
    written = [Fraction(x) for x in env.values()]
    inter = [vals[st['id']] for st in prog[:-1] if numeric(st) and not passthrough(st) and exe[st['id']]]
    if fin in written:
        raise Bad('final_written')
    if any(x in written for x in inter):
        raise Bad('inter_written')
    if len(set(env.values())) != len(env):
        raise Bad('leaf_dup')
    if any(not 2 <= x <= 9999 for x in env.values()):
        raise Bad('leaf_range')
    return vals, exe


def one_step_hits(written, fin):
    n = 0
    for i, x in enumerate(written):
        for j, y in enumerate(written):
            if i == j:
                continue
            for r in (x + y, x - y, x * y, (Fraction(x, y) if y else None)):
                if r is not None and r == fin:
                    n += 1
    return n


def draw_leaves(cell, signed, key, twin, draw):
    """A leaf assignment for (template key, arm, draw, twin), or None."""
    prog = cell['prog']
    roles = leaf_roles(prog)
    rng = seeded('leaves', *key, draw, twin)
    for attempt in range(6000):
        cat_base = 1 if draw == 0 else 2
        if attempt >= 3000:
            cat_base = 0 if attempt >= 4500 else 1
        env = {}
        for x in leaves_of(prog):
            c = rng.choice([cat_base, max(0, cat_base - 1)]) if draw else cat_base
            lo, hi = leaf_range(roles[x], c)
            env[x] = rng.randint(lo, hi)
        for st in prog:          # a percentage of a base must be a whole number: base = 100/gcd(rate, 100) x k
            if st['k'] == 'pct':
                ra, ba = st['args']
                env[ra] = rng.choice((5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 65, 70, 75, 80, 85, 90))
                q = 100 // math.gcd(env[ra], 100)
                env[ba] = q * rng.randint(max(1, 20 // q), max(2, 2000 // q))
        # repair: an exact division gets its dividend solved through a leaf: the dividend itself, or one leaf of a
        # top-level + / - in the dividend (dividend = divisor x q, q 2..9, sign random)
        m = stmt_map(prog)
        for st in prog:
            if st['k'] != '/':
                continue
            try:
                vv, _ = execute(prog, env)
            except Bad:
                break
            dv = vv[st['args'][1]] if st['args'][1] in vv else Fraction(env[st['args'][1]])
            if dv == 0 or abs(dv) > 999:
                break
            tgt = int(abs(dv)) * rng.randint(2, 9) * rng.choice((1, 1, -1))
            L = st['args'][0]
            if len(L) == 1 and L not in leafset(prog, st['args'][1]):
                env[L] = abs(tgt)
            elif L in m and m[L]['k'] in ('+', '-'):
                X, Y = m[L]['args']
                gv = lambda z: vv[z] if z in vv else Fraction(env[z])  # noqa: E731
                opts = []
                if len(Y) == 1 and Y not in leafset(prog, st['args'][1]):
                    opts.append((Y, int(tgt - gv(X)) if m[L]['k'] == '+' else int(gv(X) - tgt)))
                if len(X) == 1 and X not in leafset(prog, st['args'][1]):
                    opts.append((X, int(tgt - gv(Y)) if m[L]['k'] == '+' else int(tgt + gv(Y))))
                opts = [o for o in opts if 2 <= o[1] <= 9999] or opts[:1]
                if opts:
                    z, val = rng.choice(opts)
                    env[z] = val
        try:
            vals, exe = check_values(cell, signed, env, twin)
        except Bad:
            continue
        return env, vals, exe, attempt + 1
    return None


def draw_distractor(rng, ref_value, avoid, cell, env, mimic=None):
    lo = max(2, int(ref_value * 0.5))
    hi = max(lo + 20, int(ref_value * 1.6) + 2)
    for _ in range(400):
        d = rng.randint(lo, hi)
        if d in avoid:
            continue
        if mimic:
            e2 = dict(env)
            e2[mimic] = d
            try:
                v2, _ = execute(cell['prog'], e2)
                if v2[cell['prog'][-1]['id']] == execute(cell['prog'], env)[0][cell['prog'][-1]['id']]:
                    continue
            except Bad:
                pass
        return d
    return None


# ------------------------------------------------------------------ text helpers
PH = re.compile(r'\{([A-Z])\}')
RUNS = re.compile(r'[0-9]+')
SENT_END = re.compile(r'[.!?。！？؟।]')
QMARKS = '?？؟;;'
TRAIL = "\"'”’»」』)）"
ARITH = '+×*/÷=%−∶'


def placeholders(t):
    return PH.findall(t)


def strip_ph(t):
    return PH.sub(' ', t)


def norm(t):
    t = PH.sub(' ', t).casefold()
    return ' '.join(''.join(c if unicodedata.category(c)[0] in 'LMN' else ' ' for c in t).split())


def grams(t, n=4):
    t = norm(t)
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def jacc(a, b):
    return len(a & b) / max(1, len(a | b))


def dup_text(it):
    return (it.get('facts') or '') + ' ' + (it.get('question') or '')


def split_points(tpl):
    """offsets just after a strong sentence ender lying strictly between the first and the last slot of tpl."""
    pos = [m.start() for m in PH.finditer(tpl)]
    if len(pos) < 2:
        return []
    lo, hi = pos[0] + 3, pos[-1]
    out = []
    for m in SENT_END.finditer(tpl, lo, hi):
        k = m.end()
        while k < len(tpl) and tpl[k] in TRAIL:
            k += 1
        while k < len(tpl) and tpl[k] in '  \t　':
            k += 1
        if lo < k < hi and not tpl[k:k + 1].islower():
            out.append(k)
    return out


def compose(facts_tpl, fill, sentences, placement, question, lead, lang):
    """facts with the extra sentences placed pre / mid / suf, then the question, then the lead-in (as gen_v5)."""
    sep = '' if lang in NOSPACE else ' '
    sp = split_points(facts_tpl)
    if placement == 'mid' and sp and sentences:
        k = sp[len(sp) // 2]
        core = fill(facts_tpl[:k].rstrip()) + sep + sep.join(sentences) + sep + fill(facts_tpl[k:].lstrip())
        parts = [core]
    elif placement == 'pre':
        parts = list(sentences) + [fill(facts_tpl)]
    else:
        parts = [fill(facts_tpl)] + list(sentences)
    body = sep.join(parts)
    return (body + sep + question.strip() + (sep + lead.strip() if lead else '')).strip()


# ------------------------------------------------------------------ manifest
def lang_unit_index(lang, rnd):
    """0-based count of this language's units before round rnd, and the stratum's own index j."""
    k = [r for r, _ in ROUNDS].index(rnd)
    st = dict(ROUNDS)[rnd]
    j = sum(1 for r, s in ROUNDS[:k] if s == st)
    return k, j


def topics_for(lang, k):
    i = LANGS.index(lang)
    a = (k + 7 * i) % (2 * len(SLICES))
    sid, title, topics = SLICES[a // 2]
    h = a % 2
    return sid, title, topics[3 * h:3 * h + 3]


def writer_uid(lang, stratum, rnd):
    return 'W6-%s-%s-%s' % (lang, stratum, rnd)


def build_manifest():
    W, V = [], []
    for rnd, st in ROUNDS:
        for lang in LANGS:
            k, j = lang_unit_index(lang, rnd)
            sid, title, tp = topics_for(lang, k)
            W.append(dict(uid=writer_uid(lang, st, rnd), lang=lang, stratum=st, round=rnd, gen=GEN_OF_ROUND[rnd], j=j, slice=sid,
                          slice_title=title, topics=tp,
                          tiers=[t for t in ('T1', 'T2', 'ALL') if rnd in TIERS[t]]))
        for g, ls in GROUPS:
            V.append(dict(vid='V6-%s-%s' % (g, rnd), round=rnd, gen=GEN_OF_ROUND[rnd], stratum=st, langs=list(ls),
                          units=[writer_uid(l, st, rnd) for l in ls]))
    V.append(dict(vid=PILOT_V, round='pilot', gen='G1', stratum='SL', langs=['en', 'zh'], units=list(PILOT_UNITS)))
    return dict(bank='v6ms', unit_templates=UNIT_TEMPLATES, rounds=ROUNDS3, generations=GENERATIONS, gates=GATES,
                g4a_langs=G4A_LANGS, langs=LANGS, groups=GROUPS,
                lang_folds=LANG_FOLDS, script_folds=SCRIPT_FOLDS, tiers={k: sorted(v) for k, v in TIERS.items()},
                default_enabled=DEFAULT_ENABLED, writer_units=W, verifier_units=V)


def load_manifest():
    return json.load(open(MANIFEST, encoding='utf-8'))


def wunit(uid, man=None):
    man = man or load_manifest()
    for u in man['writer_units']:
        if u['uid'] == uid:
            return u
    raise SystemExit('REFUSE: unknown writer unit %s' % uid)


def vunit(vid, man=None):
    man = man or load_manifest()
    for v in man['verifier_units']:
        if v['vid'] == vid:
            return v
    raise SystemExit('REFUSE: unknown verifier unit %s' % vid)


def enabled_strata():
    if os.path.exists(ENABLED):
        return json.load(open(ENABLED))['enabled']
    return list(DEFAULT_ENABLED)


# ------------------------------------------------------------------ unit state
def unit_files(u):
    d = os.path.join(WRITERS, u['lang'])
    base = os.path.join(d, u['uid'] + '.json')
    out = [base] if os.path.exists(base) else []
    k = 1
    while os.path.exists(os.path.join(d, '%s.r%d.json' % (u['uid'], k))):
        out.append(os.path.join(d, '%s.r%d.json' % (u['uid'], k)))
        k += 1
    return out


def _stamp(p):
    """An acceptance stamp; a relative writer path (as shipped in this repository) is relative to this folder."""
    a = json.load(open(p))
    if not os.path.isabs(a['path']):
        a['path'] = os.path.join(HERE, a['path'])
    return a


def accepted(uid):
    p = os.path.join(ACCEPT, uid + '.json')
    return _stamp(p) if os.path.exists(p) else None


def accepted_items(lang, exclude=None):
    out = []
    for p in sorted(glob.glob(os.path.join(ACCEPT, 'W6-%s-*.json' % lang))):
        a = _stamp(p)
        if a['uid'] == exclude:
            continue
        for it in json.load(open(a['path'], encoding='utf-8'))['items']:
            out.append((it['id'], it))
    return out


def unit_state(u):
    if accepted(u['uid']):
        return 'accepted'
    fs = unit_files(u)
    if not fs:
        return 'pending'
    ok, _ = validate_path(fs[-1], quiet=True)
    return 'valid' if ok else 'written'


def spec(uid, man=None):
    u = wunit(uid, man)
    fs = unit_files(u)
    attempt = len(fs) if not accepted(uid) else len(fs) - 1
    out_path = os.path.join(WRITERS, u['lang'], uid + ('.json' if attempt == 0 else '.r%d.json' % attempt))
    cells = unit_cells(u['lang'], u['stratum'], u['j'])
    cs = []
    for c in cells:
        subs = signable(c)
        cs.append(dict(cell_id=c['cell_id'], shape=c['shape'], stratum=c['stratum'], program=readable(c),
                       dsl=strip_outer(expr(c['prog'])), leaves=c['leaves'],
                       t_position=c['t_position'],
                       alt_must_reverse=sorted({order_pair(c, s) for s in c['order_test']}),
                       signed_steps=subs, role_distractor=c['role_u'], percent_sign_ok=c['pct_ok'],
                       notes=cell_note(c)))
    d = dict(unit_id=uid, language=LANG_NAMES[u['lang']], language_code=u['lang'], stratum=u['stratum'],
             stratum_name=STRATUM_NAMES[u['stratum']], round=u['round'], slice=u['slice'],
             slice_title=u['slice_title'], topics=u['topics'], lead_in=LEAD_IN[u['lang']], attempt=attempt,
             output_path=out_path, cells=cs, language_notes=LANG_NOTES.get(u['lang'], ''))
    if attempt:
        d['previous_attempt'] = fs[-1] if fs else None
    return d


def order_sets(cell, sid):
    """(left-only leaves, right-only leaves) of a statement, or None when one side has no leaf of its own"""
    st = stmt_map(cell['prog'])[sid]
    args = st['args'][1:] if st['k'] == 'sel' else st['args']
    l, r = leafset(cell['prog'], args[0]), leafset(cell['prog'], args[1])
    lo, ro = l - r, r - l
    return (sorted(lo), sorted(ro)) if lo and ro else None


def order_pair(cell, sid):
    l, r = order_sets(cell, sid)
    return 'which is written first: %s or %s' % ('/'.join(l), '/'.join(r))


def cell_note(c):
    n = []
    ks = {st['k'] for st in c['prog']}
    if '/' in ks:
        n.append('every ÷ in this cell comes out exact (we fill it so); never mention leftovers or rounding')
    if c['shape'] in ('ICE', 'IC2'):
        n.append('the division never comes out exact: the question must make clear the count is ROUNDED UP')
    if c['shape'] == 'IFL':
        n.append('the division never comes out exact: the question must ask for FULL / COMPLETE groups only')
    if c['shape'] == 'IMO':
        n.append('the division never comes out exact: the question asks what is LEFT OVER')
    if c['stratum'] in ('CB',):
        n.append('state the rule (the condition and BOTH outcomes) in words in the facts; both branches will be '
                 'taken, on different fills')
    if c['shape'] == 'CBA':
        n.append('the text must make clear that the gap is the larger minus the smaller WHICHEVER is larger; A is '
                 'larger on half the fills and B on the other half')
    if c['stratum'] == 'SEL':
        n.append('the question picks by comparison ("the larger", "whichever is cheaper"); either side wins on '
                 'different fills')
    if c['shape'] == 'RPA':
        n.append('C is the number of periods (filled 2 to 6); B the same change every period')
    return n


# ------------------------------------------------------------------ validation (writer files)
ITEM_KEYS = ('id', 'cell_id', 'shape', 'topic', 'quantity_kind', 't_mimics', 'signed', 'numeral_grammar',
             'agreement_note', 'facts', 'facts_alt', 'base', 'base_alt', 'question', 'ex_sentence', 'sem_sentence',
             'rule_gloss', 'gloss_en', 'notes')
FILE_KEYS = ('writer_unit', 'language_code', 'stratum', 'round', 'topics', 'lead_in', 'attempt', 'items')
TEXT_KEYS = ('facts', 'facts_alt', 'base', 'base_alt', 'question', 'ex_sentence', 'sem_sentence')
NEAR_DUP = 0.45
Q_SPLIT_MIN = 4
Q_KINDS_MIN = 5
Q_NUMDEP_MAX = 2
EN_EXTRA = ('first second third fourth fifth sixth seventh eighth ninth tenth once pair couple both triple quarter '
            'quarters single none zero').split()
LANG_NOTES = {
    'zh': 'Chinese: put a measure word right after each slot ({A}个, {A}箱); never 两/二/半/双; ASCII braces.',
    'ja': 'Japanese: counters after each slot ({A}個, {A}人); kana required; never 二/半/倍.',
    'ar': 'Arabic: put the counted noun BEFORE the slot or use a unit after it ("عدد الصناديق {A}") so the grammar '
          'does not depend on the number.',
    'he': 'Hebrew: noun-after-number agreement varies with the number: prefer "{A} יחידות של", units, or the noun '
          'before the slot.',
    'ru': 'Russian: noun case after a number depends on the number (1 / 2-4 / 5+): prefer a unit abbreviation '
          '("{A} кг", "{A} шт.") or the noun before the slot ("число коробок — {A}").',
    'pl': 'Polish: as Russian: prefer "{A} szt.", "{A} kg" or "liczba X wynosi {A}".',
    'fa': 'Persian: Persian letters (ی ک) required; the noun after a number stays singular, which is invariant.',
    'hi': 'Hindi: ASCII braces; prefer postpositions that do not change with the number.',
    'bn': 'Bengali: use a classifier after the slot ({A}টি) which is invariant.',
    'ta': 'Tamil: prefer a unit or classifier after the slot.',
    'th': 'Thai: classifier after the slot ({A} ชิ้น); a question may end with a question word.',
    'ko': 'Korean: native-Korean counting forms are number-dependent: use Sino-Korean counters ({A}개, {A}명).',
    'tr': 'Turkish: the noun after a number is singular (invariant); suffixes after a slot must not depend on the '
          'number\'s pronunciation: use a unit or an apostrophe-free construction.',
    'sw': 'Swahili: number agreement with noun classes changes with the number word, but slots are digits: write '
          '"{A}" after the noun ("vitabu {A}").',
    'el': 'Greek: prefer the noun before the slot or a unit after it.',
    'vi': 'Vietnamese: a classifier after the slot is invariant.',
}


def text_problems(lang, key, t, leaves, role_u=False, pct_ok=False):
    p = []
    if not isinstance(t, str) or not t.strip():
        return ['%s must be a non-empty string' % key]
    if t != t.strip() or any(c in t for c in '\n\r\t'):
        p.append('%s: outer whitespace or a newline/tab' % key)
    lo, hi = (25, 900) if key in ('facts', 'facts_alt', 'base', 'base_alt') else (8, 400)
    if not lo <= len(t) <= hi:
        p.append('%s: length %d outside %d..%d' % (key, len(t), lo, hi))
    ph = placeholders(t)
    U = ['U'] if role_u else []
    want = {'facts': leaves + ['T'] + U, 'facts_alt': leaves + ['T'] + U, 'base': leaves + U, 'base_alt': leaves + U,
            'question': [], 'ex_sentence': ['X'], 'sem_sentence': ['X']}[key]
    if sorted(ph) != sorted(want):
        p.append('%s: slots %s, need exactly %s once each' % (key, ph, sorted(want) or 'none'))
    if any(c in PH.sub('', t) for c in '{}｛｝'):
        p.append('%s: braces other than the slots' % key)
    for m1, m2 in zip(list(PH.finditer(t)), list(PH.finditer(t))[1:]):
        between = t[m1.end():m2.start()]
        if not any(unicodedata.category(c)[0] == 'L' for c in between):
            p.append('%s: no word between {%s} and {%s}' % (key, m1.group(1), m2.group(1)))
    plain = strip_ph(re.sub(r'(\{[A-Z]\})\s?[%٪％]', r'\1', t) if pct_ok else t)
    d = VS.digit_chars(plain)
    if d:
        p.append('%s: digit characters %r' % (key, ''.join(sorted(set(d)))))
    sym = sorted(set(c for c in plain if c in ARITH))
    if sym:
        p.append('%s: arithmetic symbols %r' % (key, ''.join(sym)))
    if re.search(r'\{[A-Z]\}\s*-\s*\{[A-Z]\}|\s-\s*\{[A-Z]\}|\{[A-Z]\}\s*-\s', t):
        p.append('%s: a minus sign next to a slot' % key)
    nw = VS.number_words_in(lang, plain)
    if lang == 'en':
        low = plain.casefold()
        nw += [w for w in EN_EXTRA if re.search(r"(?<![\w'’])%s(?![\w'’])" % re.escape(w), low)]
    if nw:
        p.append('%s: number words hide a number: %s' % (key, ', '.join(sorted(set(nw)))))
    end = t.rstrip().rstrip(TRAIL).rstrip()
    if key == 'question' and lang != 'th' and (not end or end[-1] not in QMARKS):
        p.append('question must end with a question mark')
    if key != 'question' and lang != 'th' and (not end or not (SENT_END.match(end[-1]) or end[-1] in QMARKS)):
        p.append('%s must end with sentence-final punctuation' % key)
    sp = VS.script_problem(lang, plain)
    if sp:
        p.append('%s: %s' % (key, sp))
    return p


def leaf_order(t):
    return [x for x in placeholders(t) if x in 'ABCD']


def reversed_pair(cell, sid, order):
    """True when the right operand's own leaves are written before the left operand's own leaves"""
    os_ = order_sets(cell, sid)
    if os_ is None:
        return False
    l, r = os_
    pos = {x: i for i, x in enumerate(order)}
    return min(pos[x] for x in r) < min(pos[x] for x in l)


def t_pos(t):
    o = placeholders(t)
    i = o.index('T')
    lv = [k for k, x in enumerate(o) if x in 'ABCD']
    return 'before' if i < lv[0] else ('after' if i > lv[-1] else 'between')


def validate_doc(doc, sp, accepted_its=()):
    """[FAIL messages] for one writer file against its unit spec."""
    P = []
    lang = sp['language_code']
    if not isinstance(doc, dict) or set(doc) != set(FILE_KEYS):
        return ['file keys must be exactly %s' % (FILE_KEYS,)]
    for k, want in (('writer_unit', sp['unit_id']), ('language_code', lang), ('stratum', sp['stratum']),
                    ('round', sp['round']), ('lead_in', sp['lead_in']), ('topics', sp['topics'])):
        if doc[k] != want:
            P.append('%s must be %r' % (k, want))
    items = doc['items']
    if not isinstance(items, list) or len(items) != UNIT_TEMPLATES:
        return P + ['items must hold exactly %d templates' % UNIT_TEMPLATES]
    cells = {c['cell_id']: c for c in unit_cells(lang, sp['stratum'], wunit(sp['unit_id'])['j'])}
    kinds, numdep, splits, topics = set(), 0, 0, collections.Counter()
    sub_total, sub_signed = 0, 0
    for n, it in enumerate(items):
        tag = 'item %d' % (n + 1)
        if not isinstance(it, dict) or set(it) != set(ITEM_KEYS):
            P.append('%s: keys must be exactly %s' % (tag, ITEM_KEYS))
            continue
        cid = 'c%d' % (n + 1)
        if it['id'] != '%s-%02d' % (sp['unit_id'], n + 1):
            P.append('%s: id must be %s-%02d' % (tag, sp['unit_id'], n + 1))
        if it['cell_id'] != cid:
            P.append('%s: cell_id must be %s (file order = cell order)' % (tag, cid))
            continue
        c = cells[cid]
        if it['shape'] != c['shape']:
            P.append('%s: shape must be %s' % (tag, c['shape']))
        lv = c['leaves']
        for k in TEXT_KEYS:
            P += ['%s: %s' % (tag, m) for m in text_problems(lang, k, it[k], lv, c['role_u'], c['pct_ok'])]
        if any(m.startswith(tag + ': ') and 'slots' in m for m in P):
            continue
        fo, ao = leaf_order(it['facts']), leaf_order(it['facts_alt'])
        if fo != sorted(lv):
            P.append('%s: facts must write the slots in the order %s (got %s)' % (tag, ' '.join(sorted(lv)), ' '.join(fo)))
        if leaf_order(it['base']) != fo:
            P.append('%s: base must keep the slot order of facts' % tag)
        if leaf_order(it['base_alt']) != ao:
            P.append('%s: base_alt must keep the slot order of facts_alt' % tag)
        if ao == fo:
            P.append('%s: facts_alt must write the slots in a different order from facts' % tag)
        elif c['order_test'] and not any(reversed_pair(c, s, ao) != reversed_pair(c, s, fo) for s in c['order_test']):
            P.append('%s: facts_alt must change, compared with facts, the answer to at least one of: %s' % (
                tag, '; '.join(sorted({order_pair(c, s) for s in c['order_test']}))))
        if 'T' in placeholders(it['facts']) and t_pos(it['facts']) != c['t_position']:
            P.append('%s: {T} must be written %s the operand slots in facts (spec t_position)' % (
                tag, {'before': 'before all', 'between': 'between (after the first, before the last of)',
                      'after': 'after all'}[c['t_position']]))
        for b, f in (('base', 'facts'), ('base_alt', 'facts_alt')):
            if jacc(grams(it[b]), grams(it[f])) < 0.25:
                P.append('%s: %s must be %s with only the {T} part removed' % (tag, b, f))
        if it['t_mimics'] not in lv:
            P.append('%s: t_mimics must be one of %s' % (tag, lv))
        want_signed = signable(c)
        sg = it['signed']
        if not isinstance(sg, dict) or sorted(sg) != sorted(want_signed) or not all(isinstance(v, bool) for v in sg.values()):
            P.append('%s: signed must be an object {%s} of true/false (empty {} when there is none)' % (
                tag, ', '.join('"%s": ...' % s for s in want_signed)))
        else:
            sub_total += len(sg)
            sub_signed += sum(sg.values())
        if it['numeral_grammar'] not in ('invariant', 'number_dependent'):
            P.append('%s: numeral_grammar must be invariant or number_dependent' % tag)
        numdep += it['numeral_grammar'] == 'number_dependent'
        if it['topic'] not in sp['topics']:
            P.append('%s: topic must be one of your topics' % tag)
        topics[it['topic']] += 1
        kinds.add(str(it['quantity_kind']).strip().lower())
        splits += bool(split_points(it['base']))
        for k in ('rule_gloss', 'gloss_en'):
            if not isinstance(it[k], str) or len(it[k].strip()) < 10:
                P.append('%s: %s must be an English sentence' % (tag, k))
            elif VS.digit_chars(strip_ph(it[k])):
                P.append('%s: %s must not contain digits' % (tag, k))
    if P:
        return P
    fsp = VS.file_script_problems(lang, [it[k] for it in items for k in TEXT_KEYS])
    P += ['file: %s' % m for m in fsp]
    if sub_total >= 2 and sub_signed * 2 < sub_total:
        P.append('at least half of the unit\'s subtraction steps must be signed: true (got %d of %d)' % (sub_signed, sub_total))
    if numdep > Q_NUMDEP_MAX:
        P.append('at most %d templates may be number_dependent (got %d)' % (Q_NUMDEP_MAX, numdep))
    if splits < Q_SPLIT_MIN:
        P.append('at least %d templates need a sentence break between two slots in base (got %d)' % (Q_SPLIT_MIN, splits))
    if len(kinds) < Q_KINDS_MIN:
        P.append('at least %d distinct quantity_kind (got %d)' % (Q_KINDS_MIN, len(kinds)))
    if any(topics[t] < 2 for t in sp['topics']):
        P.append('each of your 3 topics must be used at least twice (got %s)' % dict(topics))
    P += near_dups(items, accepted_its)
    return P


def near_dups(items, accepted_its=()):
    P = []
    G = [(it['id'], grams(dup_text(it))) for it in items]
    for i in range(len(G)):
        for j in range(i + 1, len(G)):
            sc = jacc(G[i][1], G[j][1])
            if sc >= NEAR_DUP:
                P.append('near-duplicate: %s and %s overlap %.2f (limit %.2f): rewrite one as a different situation'
                         % (G[i][0], G[j][0], sc, NEAR_DUP))
    for aid, ait in accepted_its:
        ga = grams(dup_text(ait))
        for iid, g in G:
            sc = jacc(g, ga)
            if sc >= NEAR_DUP:
                P.append('near-duplicate of an accepted template: %s overlaps %s %.2f: rewrite it as a different '
                         'situation' % (iid, aid, sc))
    return P


def validate_path(path, quiet=False, for_accept=False):
    try:
        doc = json.load(open(path, encoding='utf-8'))
    except (OSError, ValueError) as e:
        return False, ['cannot read JSON: %s' % e]
    uid = os.path.basename(path).split('.')[0]
    try:
        u = wunit(uid)
    except SystemExit as e:
        return False, [str(e)]
    sp = spec(uid)
    sp['unit_id'] = uid
    if isinstance(doc, dict) and doc.get('attempt') != (int(re.search(r'\.r(\d+)\.json$', path).group(1))
                                                         if re.search(r'\.r(\d+)\.json$', path) else 0):
        return False, ['attempt must match the file name (0 for .json, K for .rK.json)']
    P = validate_doc(doc, sp, accepted_items(u['lang'], exclude=uid))
    return (not P), P


# ------------------------------------------------------------------ rows
def arms_for(nleaves, role_u=False):
    if role_u:
        return [('base', ('U',)), ('T', ('U', 'T')), ('s', ('U', 's')), ('Ts', ('U', 'T', 's'))]
    if nleaves == 3:
        return [('base', ()), ('T', ('T',)), ('Ts', ('T', 's')), ('Tes', ('T', 'ex', 'sem'))]
    return [('base', ()), ('T', ('T',)), ('s', ('s',)), ('Ts', ('T', 's'))]


def template_rows(lang, uid, it, cell, verified=None, tags=()):
    """32 rows for one template: 4 arms x 2 draws x 2 twins x 2 written orders."""
    rows, refused = [], collections.Counter()
    lead = LEAD_IN[lang]
    signed = it.get('signed') or {}
    prog = cell['prog']
    fid_kind, fid = flip_kind(cell, signed)
    for arm, names in arms_for(len(cell['leaves']), cell.get('role_u')):
        for draw in range(2):
            for twin in range(2):
                best = None
                for rk in range(ONE_STEP_RETRIES):
                    key = (lang, it['id'], arm) + ((rk,) if rk else ())
                    got = draw_leaves(cell, signed, key, twin, draw)
                    if got is None:
                        continue
                    env, vals, exe, tries = got
                    fin = vals[prog[-1]['id']]
                    rng = seeded('dist', lang, it['id'], arm, draw, twin, rk)
                    avoid = set(env.values()) | {int(v) for v in vals.values() if not isinstance(v, bool)
                                                  and v.denominator == 1}
                    ds, ok = [], True
                    for nm in names:
                        sname = nm if nm != 's' else ('ex' if draw == 0 else 'sem')
                        if sname == 'T':
                            d = draw_distractor(rng, env[it['t_mimics']], avoid, cell, env, mimic=it['t_mimics'])
                        elif sname == 'U':
                            d = draw_distractor(rng, env[rng.choice(cell['leaves'])], avoid, cell, env)
                        else:
                            d = draw_distractor(rng, env[rng.choice(cell['leaves'])], avoid, cell, env)
                        if d is None:
                            ok = False
                            break
                        avoid.add(d)
                        ds.append((sname, d))
                    if not ok:
                        continue
                    written = list(env.values()) + [d for _, d in ds]
                    hits = one_step_hits([Fraction(x) for x in written], fin)
                    if best is None or hits < best[-1]:
                        best = (env, vals, exe, tries, fin, ds, written, hits)
                    if hits == 0:
                        break
                if best is None:
                    refused['no_fill:%s' % arm] += 2
                    continue
                env, vals, exe, tries, fin, ds, written, hits = best
                prng = seeded('place', lang, it['id'], arm, draw)
                placement = prng.choice(['pre', 'suf', 'mid', 'mid'])
                for order in ('main', 'alt'):
                    use_T = 'T' in [n for n, _ in ds]
                    tpl = it['facts' if order == 'main' else 'facts_alt'] if use_T else it['base' if order == 'main' else 'base_alt']
                    dv = dict(ds)
                    fill = lambda x: PH.sub(lambda m: str(env[m.group(1)]) if m.group(1) in env else str(dv[m.group(1)]), x)  # noqa: E731
                    sents = [it['ex_sentence' if n == 'ex' else 'sem_sentence'].replace('{X}', str(v))
                             for n, v in ds if n in ('ex', 'sem')]
                    pl = placement if (placement != 'mid' or split_points(tpl)) else 'suf'
                    text = compose(tpl, fill, sents, pl, it['question'], lead, lang)
                    runs = [int(x) for x in RUNS.findall(text)]
                    if len(runs) != len(written) or sorted(runs) != sorted(written) or len(set(runs)) != len(runs):
                        refused['run_mismatch'] += 1
                        continue
                    ridx = {x: runs.index(env[x]) for x in env}
                    lo_, hi_ = min(ridx.values()), max(ridx.values())
                    dist = []
                    for n, v in ds:
                        i = runs.index(v)
                        dist.append(dict(slot=n, value=v, mimics=(it['t_mimics'] if n == 'T' else None), run_idx=i,
                                         position=('before' if i < lo_ else 'after' if i > hi_ else 'between'),
                                         rung={'T': 'inline_lookalike', 'ex': 'sentence_other_kind',
                                               'sem': 'sentence_same_kind', 'U': 'inline_role'}[n]))
                    worder = sorted(env, key=lambda x: ridx[x])
                    steps = []
                    for st in prog:
                        r = vals[st['id']]
                        rec = dict(id=st['id'], k=st['k'], args=st['args'], guard=st.get('guard'),
                                   value=(r if isinstance(r, bool) else int(r)), executed=exe[st['id']])
                        if st['k'] in NONCOMM or st['k'] in ('max', 'min'):
                            a = st['args'][1:] if st['k'] == 'sel' else st['args']
                            av = [vals[x] if x in vals else Fraction(env[x]) for x in a]
                            if not isinstance(av[0], bool):
                                rec['left_value'], rec['right_value'] = int(av[0]), int(av[1])
                                rec['left_smaller'] = av[0] < av[1]
                            rec['left_written_first'] = not reversed_pair(cell, st['id'], worder)
                        if st['k'] == '-' and not st.get('guard'):
                            rec['signed'] = bool(signed.get(st['id']))
                        steps.append(rec)
                    inter = []
                    for st in prog[:-1]:
                        if numeric(st) and not passthrough(st) and exe[st['id']]:
                            v = int(vals[st['id']])
                            inter.append(dict(id=st['id'], value=v, i1_primary=(v not in written and v != int(fin))))
                    br = None
                    for st in prog:
                        if st['k'] == 'sel':
                            c0 = bool(vals[st['args'][0]])
                            br = dict(cond=st['args'][0], cond_value=c0, taken=st['args'][1 if c0 else 2],
                                      untaken=st['args'][2 if c0 else 1],
                                      untaken_value=int(vals[st['args'][2 if c0 else 1]]))
                    sel = None
                    for st in prog:
                        if st['k'] in ('max', 'min'):
                            a = [vals[x] if x in vals else Fraction(env[x]) for x in st['args']]
                            sel = dict(id=st['id'], f=st['k'], chosen=('left' if vals[st['id']] == a[0] else 'right'),
                                       other_value=int(a[1] if vals[st['id']] == a[0] else a[0]))
                    rep = None
                    if cell['shape'] == 'RPA':
                        A0, B0, N0 = env['A'], env['B'], env['C']
                        sg = 1 if cell['params']['o'] == '+' else -1
                        rep = [A0 + sg * k * B0 for k in range(1, N0 + 1)]
                    has_ctrl = any(st['k'] not in SYM for st in prog)
                    eq = None if has_ctrl else 'x=' + strip_outer(expr(prog, letters={x: str(env[x]) for x in env})).replace(' ', '')
                    rid = 'v6:%s:%s:%s:%s:d%d:t%d' % (lang, it['id'].split('-', 1)[1], order, arm, draw, twin)
                    nN = len(runs)
                    rows.append(dict(
                        row_id=rid, pair_key='v6:%s:%s:%s:d%d:t%d' % (lang, it['id'].split('-', 1)[1], arm, draw, twin),
                        order_pair_key='v6:%s:%s:%s:d%d:t%d' % (lang, it['id'].split('-', 1)[1], arm, draw, twin),
                        status='scored', source='bank_v6ms', bank_version='v6ms', bank='A', lang=lang,
                        stratum=cell['stratum'], shape=cell['shape'], domain=it['topic'], op='multistep',
                        wild_op='ams_' + cell['shape'], text=text, question=it['question'], answer_cue=lead,
                        ans=int(fin), a=env['A'], b=env['B'], list_values=runs, ds=[d for _, d in ds],
                        has_distractor=bool(ds), distractor_pos=None, n_numerals_written=nN, slot_mode='whole',
                        fill='int', selection_eligible=True, completion_valid=True, commutative=None,
                        variant=order, qorder='qlast',
                        annotation=(dict(kind='v6ms infix', equation=eq) if eq else None),
                        prov=dict(locator='regex [0-9]+ (the dumper re-checks n_runs against block.digit_runs)',
                                  gold_run_idx=[ridx[x] for x in sorted(env)], n_runs=nN),
                        v6=dict(template_id=it['id'], unit=uid, cell_id=cell['cell_id'], params=cell['params'],
                                program=prog, dsl=strip_outer(expr(prog)), leaves=env,
                                leaf_run_idx=ridx, written_order=worder, steps=steps, final=int(fin),
                                intermediates=inter, branch=br, select=sel, rep_trace=rep, distractors=dist,
                                arm=arm, draw=draw, twin=twin, flip=fid_kind, flip_step=fid, order=order,
                                placement=pl, lang_fold=LANG_FOLDS[lang], script_fold=SCRIPT_FOLDS[lang],
                                tmpl_fold=1 + int(hashlib.md5(it['id'].encode()).hexdigest(), 16) % 5,
                                alt_1step_hits=hits, leaf_tries=tries, numdep=it['numeral_grammar'] == 'number_dependent',
                                verified=verified, tags=list(tags), le5=(nN <= 5))))
    return rows, refused


# ------------------------------------------------------------------ blind files
BLIND_KINDS = (('k1', 'facts', ('T',), 'main'), ('k2', 'facts_alt', ('T',), 'alt'),
               ('k3', 'base', ('ex',), 'main'), ('k4', 'base_alt', ('sem',), 'alt'))
FLAGS = ('unnatural', 'ungrammatical', 'ambiguous', 'hidden_operand', 'states_intermediate', 'wrong_language',
         'number_dependent_grammar', 'another_program_answers', 'distractor_needed', 'cue_mismatch',
         'not_answerable', 'formula_in_question', 'other')
KEEP_FLAGS = ('number_dependent_grammar', 'formula_in_question')   # kept and tagged, not dropped


def blind_text(it, kind, lang):
    """(text with slots renamed by appearance, {blind letter: template slot}, placement)."""
    _, field, extra, _ = kind
    tpl = it[field]
    sents = []
    if 'ex' in extra:
        sents = [it['ex_sentence']]
    if 'sem' in extra:
        sents = [it['sem_sentence']]
    pl = seeded('bplace', it['id'], kind[0]).choice(['pre', 'suf', 'mid'])
    if pl == 'mid' and not split_points(tpl):
        pl = 'suf'
    t = compose(tpl, lambda x: x, sents, pl, it['question'], None, lang)
    letters, mp = iter('ABCDEFGH'), {}

    def rn(m):
        s = m.group(1)
        b = next(letters)
        mp[b] = s
        return '{%s}' % b
    return PH.sub(rn, t), mp, pl


def build_blind(v, items_by_unit):
    """blind + key documents for one verifier unit."""
    texts, key = [], {}
    for uid in v['units']:
        lang = wunit(uid)['lang']
        u = wunit(uid)
        cells = {c['cell_id']: c for c in unit_cells(lang, u['stratum'], u['j'])}
        for it in items_by_unit[uid]:
            c = cells[it['cell_id']]
            for kind in BLIND_KINDS:
                t, mp, pl = blind_text(it, kind, lang)
                texts.append(dict(lang=lang, text=t, _k=(it['id'], kind[0], mp, c['cell_id'], uid, pl)))
    rng = seeded('shuffle', v['vid'])
    rng.shuffle(texts)
    items = []
    for n, x in enumerate(texts):
        bid = '%s-t%03d' % (v['vid'], n + 1)
        tid, k, mp, cid, uid, pl = x['_k']
        items.append(dict(id=bid, lang=x['lang'], text=x['text']))
        key[bid] = dict(template_id=tid, kind=k, letters=mp, cell_id=cid, unit=uid, placement=pl)
    langs = {l: dict(language=LANG_NAMES[l], cue=LEAD_IN[l]) for l in v['langs']}
    return dict(verifier_unit=v['vid'], languages=langs, n=len(items), items=items), dict(verifier_unit=v['vid'], key=key)


def key_fills(it, cell, kind, mp):
    """8 value assignments over the blind letters (both twins x 2 draws x 2 arms' worth) with the gold final."""
    signed = it.get('signed') or {}
    out = []
    inv = {s: b for b, s in mp.items()}
    for draw in range(2):
        for twin in range(2):
            for rep in range(2):
                got = draw_leaves(cell, signed, ('key', it['id'], kind, rep), twin, draw)
                if got is None:
                    continue
                env, vals, _, _ = got
                fin = vals[cell['prog'][-1]['id']]
                rng = seeded('keyd', it['id'], kind, draw, twin, rep)
                e = {inv[x]: env[x] for x in env}
                avoid = set(env.values())
                for s in mp.values():
                    if s in ('T', 'X', 'U'):
                        ref = env[it['t_mimics']] if s == 'T' else env[cell['leaves'][0]]
                        d = draw_distractor(rng, ref, avoid, cell, env, mimic=(it['t_mimics'] if s == 'T' else None)) or 7777
                        avoid.add(d)
                        e[inv[s]] = d
                out.append(dict(env=e, final=str(fin)))
    return out


def check_format(blind, out):
    """[problems] of a verifier output against its blind file."""
    P = []
    if not isinstance(out, dict) or out.get('verifier_unit') != blind['verifier_unit'] or not isinstance(out.get('items'), list):
        return ['top level must be {"verifier_unit": "%s", "items": [...]}' % blind['verifier_unit']]
    want = {x['id']: x for x in blind['items']}
    seen = collections.Counter(i.get('id') for i in out['items'] if isinstance(i, dict))
    for bid in want:
        if seen[bid] != 1:
            P.append('%s: must appear exactly once (got %d)' % (bid, seen[bid]))
    for i in out['items']:
        if not isinstance(i, dict) or set(i) != {'id', 'program', 'unused', 'flags', 'note'}:
            P.append('item keys must be exactly id, program, unused, flags, note: %r' % (i if not isinstance(i, dict) else i.get('id')))
            continue
        if i['id'] not in want:
            P.append('%s: unknown id' % i['id'])
            continue
        letters = sorted(set(placeholders(want[i['id']]['text'])))
        fl = i['flags']
        if not isinstance(fl, list) or any(f not in FLAGS for f in fl):
            P.append('%s: flags must be a list drawn from %s' % (i['id'], ', '.join(FLAGS)))
            fl = []
        if i['program'] is None:
            if not ({'not_answerable', 'ambiguous'} & set(fl)):
                P.append('%s: program null needs the flag not_answerable or ambiguous' % i['id'])
        else:
            try:
                used = dsl_letters(i['program'])
            except ValueError as e:
                P.append('%s: program does not parse: %s' % (i['id'], e))
                continue
            bad = [x for x in used if x not in letters]
            if bad:
                P.append('%s: program uses letters not in the text: %s' % (i['id'], bad))
            if not isinstance(i['unused'], list) or sorted(i['unused']) != sorted(set(letters) - set(used)):
                P.append('%s: unused must list exactly the letters the program does not use: %s' % (
                    i['id'], sorted(set(letters) - set(used))))
        if (fl or i['program'] is None) and not (isinstance(i['note'], str) and i['note'].strip()):
            P.append('%s: a flag or a null program needs a short English note' % i['id'])
    return P


# ------------------------------------------------------------------ commands
def cmd_manifest(a):
    m = build_manifest()
    s = json.dumps(m, ensure_ascii=False, indent=1)
    if os.path.exists(MANIFEST):
        if open(MANIFEST, encoding='utf-8').read() == s:
            print('MANIFEST unchanged %s (%d writer units, %d verifier units)' % (md5f(MANIFEST), len(m['writer_units']), len(m['verifier_units'])))
            return
        raise SystemExit('REFUSE: manifest/units.json exists and differs (never overwritten)')
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    with open(MANIFEST, 'w', encoding='utf-8') as f:
        f.write(s)
    if not os.path.exists(ENABLED):
        json.dump(dict(enabled=DEFAULT_ENABLED, note='strata status --next offers; REP is off (PLAN D3)'),
                  open(ENABLED, 'w'), indent=1)
    print('MANIFEST written %s (%d writer units, %d verifier units)' % (md5f(MANIFEST), len(m['writer_units']), len(m['verifier_units'])))


def v_state(v):
    if os.path.exists(os.path.join(VERIFY, v['vid'] + '.json')) or glob.glob(os.path.join(VERIFY, v['vid'] + '.r*.json')):
        return 'verified'
    if os.path.exists(os.path.join(BLIND, v['vid'] + '.blind.json')):
        return 'blind_ready'
    if all(accepted(u) for u in v['units']):
        return 'closable'
    return 'blocked'


GATE_MATCH, GATE_KEPT = 0.90, 0.75


def gate_state(gen, man=None):
    """(open?, reason). A generation with a gate round is offered only after that round's verifier units are all
    verified with pooled program match >= 90% and templates kept >= 75% (PLAN section 4 bars B2, B3)."""
    g = GATES.get(gen)
    if not g:
        return True, 'no gate'
    man = man or load_manifest()
    vs = [v for v in man['verifier_units'] if v['round'] == g]
    if not all(v_state(v) == 'verified' for v in vs):
        return False, 'gate %s not verified yet' % g
    m = n = k = t = 0
    for v in vs:
        res, tv = template_verdicts(v['vid'])
        m += sum(r['match'] for r in res.values())
        n += len(res)
        k += sum(x['kept'] for x in tv.values())
        t += len(tv)
    ok = n and m >= GATE_MATCH * n and k >= GATE_KEPT * t
    return bool(ok), 'gate %s: match %d/%d, kept %d/%d' % (g, m, n, k, t)


def cmd_status(a):
    man = load_manifest()
    tier = TIERS[a.tier]
    st = a.strata.split(',') if a.strata else enabled_strata()
    W = [u for u in man['writer_units'] if u['round'] in tier and u['stratum'] in st]
    if a.next is None:
        c = collections.Counter((u['round'], unit_state(u)) for u in W)
        for rnd, s in ROUNDS:
            if rnd in tier and s in st:
                print('%s %-4s %s' % (rnd, s, dict((k[1], n) for k, n in c.items() if k[0] == rnd)))
        for v in man['verifier_units']:
            if v['round'] in tier or v['vid'] == PILOT_V:
                if v['stratum'] in st or v['vid'] == PILOT_V:
                    print('%s %s' % (v['vid'], v_state(v)))
        return
    if a.kind == 'writer':
        # round order first, then round-robin over languages inside the round
        gates = {g: gate_state(g, man) for g in GENERATIONS}
        if a.gen:
            W = [u for u in W if u['gen'] == a.gen]
        closed = sorted({u['gen'] for u in W if not gates[u['gen']][0] and not a.ignore_gate})
        for g in closed:
            print('GATED %s: %s (pass --ignore-gate only on the project owner\'s word)' % (g, gates[g][1]))
        out = [u for u in W if unit_state(u) in ('pending', 'written') and (gates[u['gen']][0] or a.ignore_gate)]
        for u in out[:a.next]:
            print(json.dumps(dict(uid=u['uid'], round=u['round'], stratum=u['stratum'], state=unit_state(u))))
        if not out:
            print('NEXT none')
    else:
        out = [v for v in man['verifier_units'] if v['vid'] != PILOT_V and v['round'] in tier and v['stratum'] in st
               and v_state(v) in ('closable', 'blind_ready')]
        for v in out[:a.next]:
            print(json.dumps(dict(vid=v['vid'], state=v_state(v), langs=v['langs'])))
        if not out:
            print('NEXT none')


def cmd_spec(a):
    print(json.dumps(spec(a.uid), ensure_ascii=False, indent=1))


def cmd_validate(a):
    ok, P = validate_path(a.path)
    for p in P[:60]:
        print('FAIL', p)
    if len(P) > 60:
        print('FAIL ... %d more' % (len(P) - 60))
    print('VALIDATE ok %d' % UNIT_TEMPLATES if ok else 'VALIDATE fail %d' % len(P))


def cmd_close(a):
    man = load_manifest()
    if a.target.startswith('V6-'):
        vs = [vunit(a.target, man)]
    else:
        vs = [v for v in man['verifier_units'] if v['round'] == a.target and v['stratum'] in enabled_strata()]
        if not vs:
            raise SystemExit('REFUSE: no verifier units for %s' % a.target)
    units = sorted({u for v in vs for u in v['units']})
    os.makedirs(ACCEPT, exist_ok=True)
    for uid in units:
        if accepted(uid):
            continue
        u = wunit(uid, man)
        fs = unit_files(u)
        if not fs:
            print('UNIT %s pending (no file)' % uid)
            continue
        ok, P = validate_path(fs[-1])
        if not ok:
            print('UNIT %s NOT accepted (%s): %s' % (uid, os.path.basename(fs[-1]), P[0]))
            continue
        json.dump(dict(uid=uid, path=fs[-1], md5=md5f(fs[-1]), attempt=len(fs) - 1,
                       stamped=time.strftime('%Y-%m-%d %H:%M:%S %Z')), open(os.path.join(ACCEPT, uid + '.json'), 'w'))
        print('UNIT %s accepted (attempt %d)' % (uid, len(fs) - 1))
    os.makedirs(BLIND, exist_ok=True)
    os.makedirs(BLIND_KEY, exist_ok=True)
    for v in vs:
        bp = os.path.join(BLIND, v['vid'] + '.blind.json')
        if os.path.exists(bp):
            print('BLIND ok %d texts -> blind/%s.blind.json (exists)' % (json.load(open(bp))['n'], v['vid']))
            continue
        miss = [u for u in v['units'] if not accepted(u)]
        if miss:
            print('BLOCKED %s: not accepted %s' % (v['vid'], ' '.join(miss)))
            continue
        ibu = {u: json.load(open(accepted(u)['path'], encoding='utf-8'))['items'] for u in v['units']}
        b, k = build_blind(v, ibu)
        for bid, kk in k['key'].items():
            u = wunit(kk['unit'], man)
            cell = {c['cell_id']: c for c in unit_cells(u['lang'], u['stratum'], u['j'])}[kk['cell_id']]
            it = [x for x in ibu[kk['unit']] if x['id'] == kk['template_id']][0]
            kk['fills'] = key_fills(it, cell, kk['kind'], kk['letters'])
            kk['gold_dsl'] = strip_outer(expr(cell['prog'], letters={s: bl for bl, s in kk['letters'].items()}))
        json.dump(k, open(os.path.join(BLIND_KEY, v['vid'] + '.key.json'), 'w'), ensure_ascii=False, indent=1)
        json.dump(b, open(bp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('BLIND ok %d texts -> blind/%s.blind.json' % (b['n'], v['vid']))


def cmd_format(a):
    bp = os.path.join(BLIND, a.vid + '.blind.json')
    blind = json.load(open(bp, encoding='utf-8'))
    try:
        out = json.load(open(a.path, encoding='utf-8'))
    except (OSError, ValueError) as e:
        print('FORMAT fail: cannot read JSON: %s' % e)
        return
    P = check_format(blind, out)
    for p in P[:60]:
        print('FAIL', p)
    print('FORMAT ok %d' % blind['n'] if not P else 'FORMAT fail %d' % len(P))


def verdicts(vid):
    """{blind id: dict(match, flags, ...)} for one verified unit (latest verify file)."""
    fs = sorted(glob.glob(os.path.join(VERIFY, vid + '.r*.json'))) or [os.path.join(VERIFY, vid + '.json')]
    out = json.load(open(fs[-1], encoding='utf-8'))
    key = json.load(open(os.path.join(BLIND_KEY, vid + '.key.json'), encoding='utf-8'))['key']
    res = {}
    for i in out['items']:
        k = key[i['id']]
        match, why = False, ''
        if i['program'] is not None:
            try:
                match = all(eval_dsl(i['program'], f['env']) == Fraction(f['final']) for f in k['fills']) and bool(k['fills'])
                if not match:
                    why = 'executes to a different answer'
            except (Bad, ValueError, ZeroDivisionError) as e:
                why = 'error %s' % e
        else:
            why = 'no program'
        res[i['id']] = dict(match=match, why=why, flags=i['flags'], note=i['note'], program=i['program'],
                            gold=k['gold_dsl'], **{x: k[x] for x in ('template_id', 'kind', 'unit', 'cell_id')})
    return res


def template_verdicts(vid):
    res = verdicts(vid)
    T = collections.defaultdict(list)
    for bid, r in res.items():
        T[r['template_id']].append(r)
    out = {}
    for tid, rs in T.items():
        block = sorted({f for r in rs for f in r['flags'] if f not in KEEP_FLAGS})
        miss = [r['kind'] for r in rs if not r['match']]
        out[tid] = dict(kept=(not block and not miss and len(rs) == len(BLIND_KINDS)), mismatch=miss, flags=block,
                        tags=sorted({f for r in rs for f in r['flags'] if f in KEEP_FLAGS}))
    return res, out


def cmd_report(a):
    man = load_manifest()
    lines = ['# BANK v6ms: verification report (rewritten by `v6ms.py report`)', '']
    dis = []
    tot = collections.Counter()
    by = collections.defaultdict(collections.Counter)
    for v in man['verifier_units']:
        if v_state(v) != 'verified':
            continue
        res, tv = template_verdicts(v['vid'])
        for bid, r in res.items():
            lang = wunit(r['unit'], man)['lang']
            u = wunit(r['unit'], man)
            shape = {c['cell_id']: c for c in unit_cells(lang, u['stratum'], u['j'])}[r['cell_id']]['shape']
            for key in (('lang', lang), ('shape', shape), ('kind', r['kind'])):
                by[key]['texts'] += 1
                by[key]['match'] += r['match']
                by[key]['flagged'] += bool(r['flags'])
            tot['texts'] += 1
            tot['match'] += r['match']
            tot['flagged'] += bool(r['flags'])
            if not r['match'] or r['flags']:
                dis.append(dict(id=bid, **r))
        for tid, t in tv.items():
            lang = tid.split('-')[1]
            by[('tlang', lang)]['templates'] += 1
            by[('tlang', lang)]['kept'] += t['kept']
            tot['templates'] += 1
            tot['kept'] += t['kept']
        lines.append('- %s: %d texts, program match %d/%d, templates kept %d/%d' % (
            v['vid'], len(res), sum(r['match'] for r in res.values()), len(res), sum(t['kept'] for t in tv.values()), len(tv)))
    lines += ['', 'ALL: texts %d, program match %d/%d, flagged %d/%d; templates kept %d/%d' % (
        tot['texts'], tot['match'], tot['texts'], tot['flagged'], tot['texts'], tot['kept'], tot['templates']), '']
    for dim in ('lang', 'shape', 'kind'):
        lines.append('| %s | match | flagged |' % dim)
        lines.append('|---|---|---|')
        for (d, k), c in sorted(by.items()):
            if d == dim:
                lines.append('| %s | %d/%d | %d/%d |' % (k, c['match'], c['texts'], c['flagged'], c['texts']))
        lines.append('')
    lines.append('| language | templates kept |')
    lines.append('|---|---|')
    for (d, k), c in sorted(by.items()):
        if d == 'tlang':
            lines.append('| %s | %d/%d |' % (k, c['kept'], c['templates']))
    open(os.path.join(HERE, 'VERIFY_REPORT_v6ms.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    with open(os.path.join(HERE, 'VERIFY_DISAGREE_v6ms.jsonl'), 'w', encoding='utf-8') as f:
        for d in dis:
            f.write(json.dumps(d, ensure_ascii=False) + '\n')
    print('\n'.join(lines[-40:]))
    print('REPORT ok -> VERIFY_REPORT_v6ms.md, %d disagreements -> VERIFY_DISAGREE_v6ms.jsonl' % len(dis))


def cmd_clean(a):
    os.makedirs(CLEAN, exist_ok=True)
    p = os.path.join(CLEAN, 'clean_%s.json' % a.vid)
    if os.path.exists(p):
        raise SystemExit('REFUSE: %s exists (never overwritten)' % p)
    _, tv = template_verdicts(a.vid)
    json.dump(dict(verifier_unit=a.vid, templates=tv), open(p, 'w'), indent=1)
    print('CLEAN %s: kept %d/%d -> %s' % (a.vid, sum(t['kept'] for t in tv.values()), len(tv), p))


def clean_status():
    st = {}
    for p in glob.glob(os.path.join(CLEAN, 'clean_*.json')):
        d = json.load(open(p))
        for tid, t in d['templates'].items():
            if d['verifier_unit'] == PILOT_V and tid in st:
                continue
            st[tid] = t
    return st


def cmd_gen(a):
    man = load_manifest()
    if os.path.isdir(a.out_dir) and os.listdir(a.out_dir):
        raise SystemExit('REFUSE: %s is not empty (never overwritten)' % a.out_dir)
    os.makedirs(a.out_dir, exist_ok=True)
    cl = clean_status()
    units = a.units.split(',') if a.units else [u['uid'] for u in man['writer_units'] if accepted(u['uid'])]
    rows, refused, skipped = [], collections.Counter(), collections.Counter()
    for uid in units:
        acc = accepted(uid)
        if not acc:
            skipped['not_accepted'] += 1
            continue
        u = wunit(uid, man)
        cells = {c['cell_id']: c for c in unit_cells(u['lang'], u['stratum'], u['j'])}
        for it in json.load(open(acc['path'], encoding='utf-8'))['items']:
            c = cl.get(it['id'])
            if c is None and not a.include_unverified:
                skipped['unverified_template'] += 1
                continue
            if c is not None and not c['kept']:
                skipped['dropped_by_verifier'] += 1
                continue
            r, rf = template_rows(u['lang'], uid, it, cells[it['cell_id']], verified=(c is not None),
                                  tags=(c or {}).get('tags', ()))
            rows += r
            refused += rf
    le5 = [r for r in rows if r['n_numerals_written'] <= 5]
    n6 = [r for r in rows if r['n_numerals_written'] > 5]
    for name, rs in (('rows_le5.jsonl', le5), ('rows_n6.jsonl', n6)):
        with open(os.path.join(a.out_dir, name), 'w', encoding='utf-8') as f:
            for r in rs:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
    audit = audit_rows(rows)
    rep = dict(rows=len(rows), le5=len(le5), n6=len(n6), refused=dict(refused), skipped=dict(skipped), audit=audit,
               md5={n: md5f(os.path.join(a.out_dir, n)) for n in ('rows_le5.jsonl', 'rows_n6.jsonl')},
               code_md5=md5f(TOOL))
    json.dump(rep, open(os.path.join(a.out_dir, 'GEN_REPORT.json'), 'w'), indent=1)
    print(json.dumps(rep, indent=1))


def audit_rows(rows):
    """row-level invariants + the balance tables (n/total everywhere)."""
    bad = collections.Counter()
    tab = collections.defaultdict(collections.Counter)
    for r in rows:
        v = r['v6']
        prog = v['program']
        try:
            vals, exe = execute(prog, v['leaves'])
        except Bad:
            bad['exec'] += 1
            continue
        if int(vals[prog[-1]['id']]) != r['ans']:
            bad['final'] += 1
        if eval_dsl(v['dsl'], v['leaves']) != r['ans']:
            bad['dsl'] += 1
        runs = [int(x) for x in RUNS.findall(r['text'])]
        if [runs[i] for i in r['prov']['gold_run_idx']] != [v['leaves'][x] for x in sorted(v['leaves'])]:
            bad['run_idx'] += 1
        if any(i['value'] in runs for i in v['intermediates']) or r['ans'] in runs:
            bad['written_intermediate'] += 1
        tab['n_numerals']['%d' % r['n_numerals_written']] += 1
        tab['stratum'][r['stratum']] += 1
        if v['branch']:
            tab['branch_true'][r['shape']] += v['branch']['cond_value']
            tab['branch_n'][r['shape']] += 1
        if v['select']:
            tab['sel_left'][r['shape']] += v['select']['chosen'] == 'left'
            tab['sel_n'][r['shape']] += 1
        for s in v['steps']:
            if s['k'] == '-' and 'left_smaller' in s and s.get('signed'):
                tab['signed_sub_smaller_first'][r['shape']] += s['left_smaller']
                tab['signed_sub_n'][r['shape']] += 1
            if s['k'] in NONCOMM and 'left_written_first' in s:
                tab['noncomm_left_written_first']['all'] += s['left_written_first']
                tab['noncomm_n']['all'] += 1
        tab['i1_primary']['yes'] += sum(i['i1_primary'] for i in v['intermediates'])
        tab['i1_primary']['all'] += len(v['intermediates'])
        tab['alt_1step_hit']['rows'] += bool(v['alt_1step_hits'])
    return dict(violations=dict(bad) or 'NONE', tables={k: dict(c) for k, c in tab.items()})


def cmd_launch(a):
    man = load_manifest()
    gen = GEN_OF_ROUND[a.round]
    ok, why = gate_state(gen, man)
    if not ok and not a.ignore_gate:
        raise SystemExit('REFUSE: %s is gated (%s)' % (a.round, why))
    W = [u['uid'] for u in man['writer_units'] if u['round'] == a.round and u['stratum'] in enabled_strata()
         and unit_state(u) in ('pending', 'written')]
    for k in range(0, len(W), 5):
        print(json.dumps(dict(round=a.round, units=W[k:k + 5], stages=['write'])))
    print(json.dumps(dict(round=a.round, stages=['close', 'verify'])))


def cmd_wfjs(a):
    man = load_manifest()
    R = collections.OrderedDict()
    for rnd, st in ROUNDS:
        R[rnd] = dict(units=[u['uid'] for u in man['writer_units'] if u['round'] == rnd],
                      groups={v['vid']: dict(langs=' '.join(v['langs']), texts=5 * UNIT_TEMPLATES * len(BLIND_KINDS))
                              for v in man['verifier_units'] if v['round'] == rnd})
    R['pilot'] = dict(units=list(PILOT_UNITS), groups={PILOT_V: dict(langs='en zh', texts=len(PILOT_UNITS) * UNIT_TEMPLATES * len(BLIND_KINDS))})
    tpl = open(os.path.join(HERE, 'wf_v6ms.template.js'), encoding='utf-8').read()
    js = tpl.replace('/*ROUNDS*/{}', json.dumps(R))
    p = os.path.join(HERE, 'wf_v6ms.js')
    open(p, 'w', encoding='utf-8').write(js)
    print('WFJS ok %s %s' % (p, md5f(p)))


# ------------------------------------------------------------------ selftest
SYN_WORDS = ('alder birch cedar dune ember fjord grove heath inlet juniper kestrel lagoon meadow nettle orchid '
             'pebble quarry rowan sorrel thistle upland valley willow yarrow zephyr amber basil clover dahlia '
             'fennel garnet hazel iris jasmine kelp laurel myrtle nutmeg olive poplar quince rosemary saffron '
             'tansy umber violet wheat yew').split()


def synth_unit(uid):
    """A synthetic writer file that satisfies every validator rule (selftests only; never a bank input)."""
    sp = spec(uid)
    lang = sp['language_code']
    u = wunit(uid)
    cells = unit_cells(lang, u['stratum'], u['j'])
    items = []
    for n, c in enumerate(cells):
        rng = random.Random(1000 * n + 7)
        w = lambda k=3: ' '.join(rng.choice(SYN_WORDS) for _ in range(k))  # noqa: E731
        lv = c['leaves']
        import itertools
        alt = None
        for perm in itertools.permutations(lv):
            perm = list(perm)
            if perm == lv:
                continue
            if not c['order_test'] or any(reversed_pair(c, x, perm) != reversed_pair(c, x, lv) for x in c['order_test']):
                alt = perm
                break

        words = {x: '%s {%s} %s' % (w(), x, w(2)) for x in lv}
        tw = '%s {T} %s' % (w(), w(2))
        uw = '%s {U} %s' % (w(), w(2))

        def facts(order, with_t, tpos):
            parts = [words[x] for x in order] + ([uw] if c['role_u'] else [])
            if with_t:
                k = {'before': 0, 'between': 1, 'after': len(parts)}[tpos]
                parts.insert(k, tw)
            return '. '.join(p[0].upper() + p[1:] for p in parts) + '.'
        tpos = c['t_position']
        f = facts(lv, True, tpos)
        fa = facts(alt, True, 'after')
        b = facts(lv, False, None)
        ba = facts(alt, False, None)
        subs = signable(c)
        items.append(dict(id='%s-%02d' % (uid, n + 1), cell_id=c['cell_id'], shape=c['shape'],
                          topic=sp['topics'][n % 3], quantity_kind='kind%s' % 'abcdefgh'[n],
                          t_mimics=lv[0], signed={s: True for s in subs}, numeral_grammar='invariant',
                          agreement_note='synthetic', facts=f, facts_alt=fa, base=b, base_alt=ba,
                          question='How many %s %s %s?' % (w(), w(), w()), ex_sentence='%s {X} %s.' % (w().capitalize(), w()),
                          sem_sentence='%s {X} %s.' % (w().capitalize(), w()), rule_gloss='synthetic rule gloss',
                          gloss_en='synthetic english gloss', notes=''))
    return dict(writer_unit=uid, language_code=lang, stratum=sp['stratum'], round=sp['round'], topics=sp['topics'],
                lead_in=sp['lead_in'], attempt=0, items=items)


def selftest():
    global WRITERS, ACCEPT, BLIND, BLIND_KEY, VERIFY, CLEAN
    fails = []
    n = [0]

    def chk(name, cond):
        n[0] += 1
        if not cond:
            fails.append(name)
            print('FAIL', name)
    tmp = tempfile.mkdtemp(prefix='v6ms_selftest_', dir=HERE)
    saved = (WRITERS, ACCEPT, BLIND, BLIND_KEY, VERIFY, CLEAN)
    WRITERS, ACCEPT, BLIND, BLIND_KEY, VERIFY, CLEAN = [os.path.join(tmp, x) for x in
                                                        ('writers', 'accept', 'blind', 'blind_key', 'verify', 'clean')]
    try:
        man = build_manifest()
        chk('manifest units', len(man['writer_units']) == len(ROUNDS) * len(LANGS))
        chk('manifest verifier units', len(man['verifier_units']) == len(ROUNDS) * len(GROUPS) + 1)
        chk('every language has a lead-in', all(LEAD_IN.get(l) for l in LANGS))
        chk('folds cover all languages', sorted(LANG_FOLDS) == sorted(LANGS) and sorted(SCRIPT_FOLDS) == sorted(LANGS))
        chk('groups cover all languages once', sorted(l for _, ls in GROUPS for l in ls) == sorted(LANGS))
        # topics distinct per language over all rounds
        for l in LANGS:
            tp = [tuple(topics_for(l, k)[2]) for k in range(len(ROUNDS))]
            chk('distinct topics %s' % l, len(set(tp)) == len(tp))
        # every cell of every stratum fills: exactness, flips, constraints
        for st in STRATA:
            for l in ('en', 'zh', 'ar'):
                for j in range(2):
                    for c in unit_cells(l, st, j):
                        signed = {s['id']: True for s in c['prog'] if s['k'] == '-' and not s.get('guard')} if st == 'SL' else {}
                        for twin in (0, 1):
                            g = draw_leaves(c, signed, ('st', l, c['cell_id'], j), twin, 0)
                            chk('fill %s %s %s/%s twin %d' % (st, l, c['shape'], c['params'], twin), g is not None)
                            if g:
                                env, vals, exe, _ = g
                                d = eval_dsl(strip_outer(expr(c['prog'])), env)
                                chk('dsl == exec %s' % c['shape'], d == vals[c['prog'][-1]['id']])
        # SL op-combo coverage over all languages and 4 SL rounds
        cov = collections.Counter()
        for l in LANGS:
            for j in range(4):
                for c in unit_cells(l, 'SL', j):
                    if c['shape'] in ('S2L', 'S2R'):
                        cov[(c['params']['o1'], c['params']['o2'])] += 1
        chk('SL 2-step combos all used', len(cov) == 16 and min(cov.values()) >= 10)
        # DSL
        chk('dsl ok', eval_dsl('ifelse(A + B >= C, A + B - D, A + B)', dict(A=5, B=6, C=10, D=3)) == 8)
        chk('dsl ceil', eval_dsl('ceil((A + B) / C)', dict(A=5, B=6, C=4)) == 3)
        chk('dsl mod', eval_dsl('mod(A * B, C)', dict(A=5, B=6, C=7)) == 2)
        for badp in ('A + 2', 'import(A)', 'A > B', '__x__', 'ceil(A, B)'):
            try:
                parse_dsl(badp)
                chk('dsl refuses %s' % badp, False)
            except ValueError:
                chk('dsl refuses %s' % badp, True)
        # synthetic units: validate, mutate, accept, blind, verify, report, gen
        os.makedirs(WRITERS)
        for uid in PILOT_UNITS + ('W6-en-CB-G2r01', 'W6-ar-SEL-G2r02', 'W6-hi-INT-G2r03', 'W6-ko-REP-G2r13') + tuple(
                'W6-en-%s-G3r%02d' % (s, i + 1) for i, s in enumerate(['INV', 'CMQ', 'RAT', 'PCT', 'CNV', 'BKP', 'DST'])):
            u = wunit(uid, man) if os.path.exists(MANIFEST) else [x for x in man['writer_units'] if x['uid'] == uid][0]
            doc = synth_unit(uid)
            if u['lang'] != 'en':
                # synthetic Latin text fails the script check on purpose for non-Latin languages: check that, then
                # validate it as if English text were allowed (the rest of the rules)
                P = validate_doc(doc, dict(spec(uid), unit_id=uid))
                chk('script check fires for synthetic %s' % uid, any('letters are' in p for p in P))
                continue
            P = validate_doc(doc, dict(spec(uid), unit_id=uid))
            chk('synthetic %s validates (%s)' % (uid, P[:2]), not P)
            for mut, field, newval, expect in (
                    ('digit', 'question', 'How many 3 cats?', 'digit'),
                    ('numberword', 'question', 'How many cats and two dogs?', 'number words'),
                    ('missing slot', 'base', 'Alder birch cedar {A} dune.', 'slots'),
                    ('symbol', 'question', 'How many A+B cats?', 'arithmetic'),
                    ('no qmark', 'question', 'Tell me the cats.', 'question mark')):
                d2 = json.loads(json.dumps(doc))
                d2['items'][0][field] = newval
                P2 = validate_doc(d2, dict(spec(uid), unit_id=uid))
                chk('mutation %s caught' % mut, any(expect in p for p in P2))
            d2 = json.loads(json.dumps(doc))
            d2['items'][0]['facts_alt'] = d2['items'][0]['facts']
            chk('alt order must differ', any('different order' in p for p in validate_doc(d2, dict(spec(uid), unit_id=uid))))
            d2 = json.loads(json.dumps(doc))
            d2['items'][1]['question'] = d2['items'][0]['question']
            d2['items'][1]['facts'] = d2['items'][0]['facts'].replace('{T}', '{X}').replace('{X}', '{T}')
            P2 = validate_doc(d2, dict(spec(uid), unit_id=uid))
            chk('item-level copy caught %s' % P2[:3], bool(P2))
            its = json.loads(json.dumps(doc['items'][:2]))
            its[1]['facts'], its[1]['question'] = its[0]['facts'], its[0]['question']
            chk('near-dup within a unit', any('near-duplicate' in p for p in near_dups(its)))
            chk('near-dup vs accepted', any('accepted' in p for p in near_dups(doc['items'][:1], [('acc-1', doc['items'][0])])))
            chk('no near-dup in the synthetic unit', not near_dups(doc['items']))
            os.makedirs(os.path.join(WRITERS, u['lang']), exist_ok=True)
            json.dump(doc, open(os.path.join(WRITERS, u['lang'], uid + '.json'), 'w'), indent=1)
            ok, P = validate_path(os.path.join(WRITERS, u['lang'], uid + '.json'))
            chk('validate_path %s %s' % (uid, P[:1]), ok)
            # rows
            cells = {c['cell_id']: c for c in unit_cells(u['lang'], u['stratum'], u['j'])}
            allrows = []
            for it in doc['items']:
                rows, rf = template_rows(u['lang'], uid, it, cells[it['cell_id']])
                chk('32 rows %s %s (refused %s)' % (it['id'], it['shape'], dict(rf)), len(rows) == 32)
                allrows += rows
                if cells[it['cell_id']]['stratum'] in ('CB',):
                    br = [r['v6']['branch']['cond_value'] for r in rows]
                    chk('branch balance %s' % it['id'], sum(br) * 2 == len(br))
            au = audit_rows(allrows)
            chk('audit %s NONE (%s)' % (uid, au['violations']), au['violations'] == 'NONE')
            nn = collections.Counter(r['n_numerals_written'] for r in allrows)
            chk('numeral counts in 3..6 %s' % dict(nn), set(nn) <= {3, 4, 5, 6} and 6 in nn)
            if u['stratum'] == 'SL':
                t = au['tables']
                sm = sum(t['signed_sub_smaller_first'].values())
                sn = sum(t['signed_sub_n'].values())
                chk('signed subtraction smaller-first on some rows (%d/%d)' % (sm, sn), 0 < sm < sn)
        # blind for the pilot unit set (en units only are valid here): fake a 1-unit verifier
        os.makedirs(ACCEPT)
        for uid in ('W6-en-SL-G1r01', 'W6-en-CB-G2r01'):
            p = os.path.join(WRITERS, 'en', uid + '.json')
            json.dump(dict(uid=uid, path=p, md5=md5f(p), attempt=0), open(os.path.join(ACCEPT, uid + '.json'), 'w'))
        fake_v = dict(vid='V6-SELFTEST', langs=['en'], units=['W6-en-SL-G1r01', 'W6-en-CB-G2r01'])
        ibu = {u: json.load(open(os.path.join(WRITERS, 'en', u + '.json')))['items'] for u in fake_v['units']}
        b, k = build_blind(fake_v, ibu)
        chk('blind size', b['n'] == 2 * UNIT_TEMPLATES * len(BLIND_KINDS))
        chk('blind texts carry no T/X letters', all('{T}' not in x['text'] and '{X}' not in x['text'] for x in b['items']))
        for bid, kk in k['key'].items():
            u = wunit(kk['unit'], man) if os.path.exists(MANIFEST) else [x for x in man['writer_units'] if x['uid'] == kk['unit']][0]
            cell = {c['cell_id']: c for c in unit_cells(u['lang'], u['stratum'], u['j'])}[kk['cell_id']]
            it = [x for x in ibu[kk['unit']] if x['id'] == kk['template_id']][0]
            kk['fills'] = key_fills(it, cell, kk['kind'], kk['letters'])
            kk['gold_dsl'] = strip_outer(expr(cell['prog'], letters={s: bl for bl, s in kk['letters'].items()}))
        os.makedirs(BLIND)
        os.makedirs(BLIND_KEY)
        os.makedirs(VERIFY)
        json.dump(b, open(os.path.join(BLIND, 'V6-SELFTEST.blind.json'), 'w'))
        json.dump(k, open(os.path.join(BLIND_KEY, 'V6-SELFTEST.key.json'), 'w'))
        good = dict(verifier_unit='V6-SELFTEST', items=[])
        for x in b['items']:
            kk = k['key'][x['id']]
            letters = sorted(set(placeholders(x['text'])))
            used = dsl_letters(kk['gold_dsl'])
            good['items'].append(dict(id=x['id'], program=kk['gold_dsl'], unused=sorted(set(letters) - set(used)),
                                      flags=[], note=''))
        chk('format ok on gold answers %s' % check_format(b, good)[:2], not check_format(b, good))
        json.dump(good, open(os.path.join(VERIFY, 'V6-SELFTEST.json'), 'w'))
        global vunit_saved
        res, tv = template_verdicts_local('V6-SELFTEST')
        chk('gold answers match %d/%d' % (sum(r['match'] for r in res.values()), len(res)), all(r['match'] for r in res.values()))
        chk('all templates kept', all(t['kept'] for t in tv.values()))
        wrong = json.loads(json.dumps(good))
        nwrong = 0
        for i in wrong['items']:
            lt = sorted(set(placeholders([x for x in b['items'] if x['id'] == i['id']][0]['text'])))
            if i['unused']:
                # use the distractor in place of the first used letter
                u0 = dsl_letters(i['program'])[0]
                i['program'] = re.sub(r'\b%s\b' % u0, i['unused'][0], i['program'])
                i['unused'] = sorted(set(lt) - set(dsl_letters(i['program'])))
                nwrong += 1
        json.dump(wrong, open(os.path.join(VERIFY, 'V6-SELFTEST.r1.json'), 'w'))
        res2, _ = template_verdicts_local('V6-SELFTEST')
        chk('distractor-swapped answers mismatch (%d of %d swapped)' % (sum(not r['match'] for r in res2.values()), nwrong),
            sum(not r['match'] for r in res2.values()) >= nwrong * 0.95)
        bad = json.loads(json.dumps(good))
        bad['items'][0]['program'] = 'A + 7'
        bad['items'].pop()
        chk('format catches numbers and a missing id', len(check_format(b, bad)) >= 2)
    finally:
        WRITERS, ACCEPT, BLIND, BLIND_KEY, VERIFY, CLEAN = saved
        shutil.rmtree(tmp, ignore_errors=True)
    print('SELFTEST v6ms: %d checked, %d fail' % (n[0], len(fails)))
    return not fails


def template_verdicts_local(vid):
    return template_verdicts(vid)


def main(argv):
    ap = argparse.ArgumentParser(prog='v6ms.py')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('manifest')
    p = sub.add_parser('status')
    p.add_argument('--next', type=int)
    p.add_argument('--kind', default='writer', choices=['writer', 'verifier'])
    p.add_argument('--tier', default='T1', choices=sorted(TIERS))
    p.add_argument('--strata', default='')
    p.add_argument('--gen', default='', choices=['', 'G1', 'G2', 'G3'])
    p.add_argument('--ignore-gate', action='store_true')
    p = sub.add_parser('spec')
    p.add_argument('uid')
    p = sub.add_parser('validate')
    p.add_argument('path')
    p = sub.add_parser('close')
    p.add_argument('target')
    p = sub.add_parser('format')
    p.add_argument('vid')
    p.add_argument('path')
    sub.add_parser('report')
    p = sub.add_parser('clean')
    p.add_argument('vid')
    p = sub.add_parser('gen')
    p.add_argument('--out-dir', required=True)
    p.add_argument('--include-unverified', action='store_true')
    p.add_argument('--units', default='')
    p = sub.add_parser('launch')
    p.add_argument('round')
    p.add_argument('--ignore-gate', action='store_true')
    sub.add_parser('wfjs')
    sub.add_parser('selftest')
    a = ap.parse_args(argv)
    if a.cmd == 'selftest':
        sys.exit(0 if selftest() else 1)
    if a.cmd != 'manifest' and not os.path.exists(MANIFEST):
        raise SystemExit('REFUSE: run `v6ms.py manifest` first')
    dict(manifest=cmd_manifest, status=cmd_status, spec=cmd_spec, validate=cmd_validate, close=cmd_close,
         format=cmd_format, report=cmd_report, clean=cmd_clean, gen=cmd_gen, launch=cmd_launch, wfjs=cmd_wfjs)[a.cmd](a)


if __name__ == '__main__':
    main(sys.argv[1:])
