#!/usr/bin/env python3
"""gen_audience.py -- DEMO FIT audience bank (not pre-registered; not a result). stdlib only.

Reads the writers' template files (writers/W1..W4.json), validates every template mechanically, fills each one
N_FILL times with a seeded generator, and writes rows in the oosprose bank schema so hsig_operandstate_v2b.py dumps them.

  python3 gen_audience.py --validate                      # template checks only; writes validate.json
  python3 gen_audience.py --audit-sample                  # one filled row per valid template -> audit_sample.jsonl
  python3 gen_audience.py --final --audit audit.json      # drop WRONG / AMBIGUOUS, write bank/ + BANK.md5
Text rule (the demo's prep()): text = filled.strip() + ' The answer is'; the filled text must not already end in the
cue and must not end in the dumper's direct set. Runs = maximal \\d+ runs of the final text (no other digits exist).
"""
import argparse, collections, hashlib, json, math, os, random, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CUE = 'The answer is'
DIRECT = "([{-–—/«「（$£€¥－"
N_FILL = 16          # fills per template (fewer when the template has fewer distinct satisfying fills)
MIN_FILL = 4
MAX_RUNS = 6
CATS = ('single', 'multi', 'oos', 'noarith', 'lookalike')
LONG = {'add': 'addition', 'sub': 'subtraction', 'mul': 'product', 'div': 'division'}
KEYS = {'tid', 'category', 'op', 'text', 'slots', 'constraints', 'answer', 'operands', 'distractors', 'tags', 'note'}
SLOT_RE = re.compile(r'\{([A-Z][A-Z0-9]*)\}')
FORBIDDEN = re.compile(r'(redteam|v5e2|e2_|svamp|singleeq|gsm8k|blind|key\.json|KEY_WITHHELD|ANSWERS_withheld|haiku_ab)', re.I)


def round_to(x, m):
    return ((x + m // 2) // m) * m


def digit_sum(x):
    return sum(int(c) for c in str(abs(int(x))))


ENV = dict(abs=abs, max=max, min=min, round_to=round_to, isqrt=math.isqrt, gcd=math.gcd, digit_sum=digit_sum)


def ev(expr, vals):
    return eval(expr, {'__builtins__': {}}, dict(ENV, **vals))


def md5f(p):
    return hashlib.md5(open(p, 'rb').read()).hexdigest()


def load_templates():
    T = []
    for n in (1, 2, 3, 4):
        p = os.path.join(HERE, 'writers', 'W%d.json' % n)
        if FORBIDDEN.search(p):
            raise SystemExit('REFUSE: %s' % p)
        T += json.load(open(p))
    return T


def check(t):
    """-> list of problems (empty = valid)"""
    bad = []
    miss = {'tid', 'category', 'op', 'text', 'slots', 'constraints', 'answer', 'operands', 'distractors'} - set(t)
    if miss:
        return ['missing keys %s' % sorted(miss)]
    if t['category'] not in CATS:
        bad.append('category %s' % t['category'])
    if t['category'] == 'single' and t['op'] not in LONG:
        bad.append('single op %s' % t['op'])
    txt = t['text']
    names = SLOT_RE.findall(txt)
    if len(names) != len(set(names)):
        bad.append('a slot appears twice')
    if set(names) != set(t['slots']):
        bad.append('slots %s != text slots %s' % (sorted(t['slots']), sorted(set(names))))
    if re.search(r'\d', SLOT_RE.sub('', txt)):
        bad.append('literal digit outside slots')
    if re.search(r'the answer is', txt, re.I):
        bad.append('contains the cue')
    if not txt.strip() or txt.strip()[-1] not in '?.':
        bad.append('does not end in ? or .')
    if not set(t['operands']) <= set(t['slots']) or not set(t['distractors']) <= set(t['slots']):
        bad.append('operands/distractors not slots')
    if set(t['operands']) & set(t['distractors']):
        bad.append('operand is also a distractor')
    for s, r in t['slots'].items():
        if not (isinstance(r, list) and len(r) == 2 and all(isinstance(x, int) for x in r) and 0 <= r[0] < r[1] <= 9999):
            bad.append('slot range %s %s' % (s, r))
    if len(names) > MAX_RUNS:
        bad.append('more than %d numerals' % MAX_RUNS)
    if t['category'] == 'single':
        if 'word_operand' in t:
            if not (t['op'] == 'mul' and len(t['operands']) == 1):
                bad.append('word_operand outside a 1-operand mul')
        elif len(t['operands']) != 2:
            bad.append('single needs 2 operands')
    if not t['operands']:
        bad.append('no operands')
    if bad:
        return bad
    fills = draw(t, N_FILL, check_only=True)
    if isinstance(fills, str):
        return [fills]
    if len(fills) < MIN_FILL:
        bad.append('only %d distinct satisfying fills (< %d)' % (len(fills), MIN_FILL))
    return bad


def draw(t, n, check_only=False):
    rng = random.Random(int(hashlib.md5(('aud-v1:' + t['tid']).encode()).hexdigest(), 16))
    out, seen = [], set()
    for _ in range(20000):
        vals = {s: rng.randint(r[0], r[1]) for s, r in t['slots'].items()}
        try:
            if not all(ev(c, vals) for c in t['constraints']):
                continue
            ans = ev(t['answer'], vals)
        except (ZeroDivisionError, ValueError, OverflowError):
            continue
        except Exception as e:
            return 'eval error: %r' % e
        if isinstance(ans, float):
            if not ans.is_integer():
                continue
            ans = int(ans)
        if not isinstance(ans, int) or isinstance(ans, bool) or ans < 0:
            continue
        if t['category'] == 'single':
            x = vals[t['operands'][0]]
            y = t.get('word_operand') if 'word_operand' in t else vals[t['operands'][1]]
            want = {'add': x + y, 'sub': x - y, 'mul': x * y, 'div': x // y if y and x % y == 0 else None}[t['op']]
            if want != ans:
                return 'answer %s != %s(%s, %s) = %s' % (ans, t['op'], x, y, want)
        filled = SLOT_RE.sub(lambda m: str(vals[m.group(1)]), t['text']).strip()
        if filled in seen:
            continue
        seen.add(filled)
        out.append((vals, ans, filled))
        if len(out) >= n:
            break
    return out


def make_rows(t):
    rows = []
    order = SLOT_RE.findall(t['text'])
    for i, (vals, ans, filled) in enumerate(draw(t, N_FILL)):
        if re.search(r'the answer is\s*:?\s*$', filled, re.I) or filled[-1] in DIRECT:
            raise SystemExit('REFUSE: %s fill ends in the cue / a direct char' % t['tid'])
        text = (filled + ' ' + CUE).strip()
        runs = re.findall(r'\d+', text)
        if runs != [str(vals[s]) for s in order]:
            raise SystemExit('REFUSE: %s runs %s != slot values' % (t['tid'], runs))
        gold = [order.index(s) for s in t['operands']]
        single = t['category'] == 'single'
        op_short = t['op'] if single else t['op']
        a_ = vals[t['operands'][0]]
        b_ = vals[t['operands'][1]] if len(t['operands']) > 1 else t.get('word_operand')
        rows.append(dict(
            row_id='aud:%s:%02d' % (t['tid'], i), template_id=t['tid'], category=t['category'],
            op=LONG[t['op']] if single else t['op'], opshort=op_short, cls=t['op'] if single else 'OTHER',
            in_set=single, gate_label='fire' if single else 'abstain', family='aud-' + t['category'],
            a=a_, b=b_, ans=int(ans), list_values=[vals[s] for s in order], n_numerals_written=len(runs), k=len(runs),
            prov=dict(gold_run_idx=gold, gold_run_values=[str(vals[s]) for s in t['operands']],
                      locator='regex \\d+ (comma-free ASCII)', n_runs=len(runs)),
            lang='en', status='scored', slot_mode='whole', cut=True, grade='demo', source='audience_bank_v1',
            tags=t.get('tags', []), word_operand=t.get('word_operand'), text=text))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--validate', action='store_true'); ap.add_argument('--audit-sample', action='store_true')
    ap.add_argument('--final', action='store_true'); ap.add_argument('--audit', default='')
    ap.add_argument('--out', default=os.path.join(HERE, 'bank'))
    a = ap.parse_args()
    T = load_templates()
    tids = [t.get('tid') for t in T]
    V = {}
    for t in T:
        V[t['tid']] = check(t)
    dup_t = [k for k, v in collections.Counter(t['text'] for t in T).items() if v > 1]
    if len(set(tids)) != len(tids):
        raise SystemExit('REFUSE: duplicate tids')
    good = [t for t in T if not V[t['tid']] and t['text'] not in dup_t]
    cnt = collections.Counter(t['category'] for t in T)
    gcnt = collections.Counter(t['category'] for t in good)
    print('templates %d/%d mechanically valid; by category all %s valid %s; duplicate texts %d' % (
        len(good), len(T), dict(cnt), dict(gcnt), len(dup_t)))
    for k, v in V.items():
        if v:
            print('  INVALID %s: %s' % (k, '; '.join(v)))
    if a.validate:
        json.dump(dict(valid=[t['tid'] for t in good], invalid={k: v for k, v in V.items() if v}),
                  open(os.path.join(HERE, 'validate.json'), 'w'), indent=1)
        return 0
    if a.audit_sample:
        with open(os.path.join(HERE, 'audit_sample.jsonl'), 'w') as f:
            for t in good:
                r = make_rows(t)[0]
                lab = ('single-step %s (%s): fire' % (r['op'], t['op'])) if t['category'] == 'single' else \
                      ('%s / %s: abstain (not a single + - x / step)' % (t['category'], t['op']))
                f.write(json.dumps(dict(tid=t['tid'], text=r['text'], category=t['category'], op=t['op'],
                                        claimed_label=lab, gold_answer=r['ans'],
                                        gold_operands=r['prov']['gold_run_values'],
                                        word_operand=t.get('word_operand'))) + '\n')
        print('audit sample: %d rows -> audit_sample.jsonl' % len(good))
        return 0
    if a.final:
        au = {x['tid']: x for x in json.load(open(a.audit))}
        keep = [t for t in good if au.get(t['tid'], {}).get('verdict') == 'OK']
        drop = [(t['tid'], au.get(t['tid'], {}).get('verdict', 'NOT AUDITED')) for t in good if t not in keep]
        print('audit: OK %d/%d; dropped %s' % (len(keep), len(good), drop))
        os.makedirs(os.path.join(a.out, 'dump'), exist_ok=True)
        allrows = []
        per = collections.defaultdict(list)
        for t in keep:
            rs = make_rows(t)
            allrows += rs
            per[t['category']] += rs
        texts = collections.Counter(r['text'] for r in allrows)
        if max(texts.values()) > 1:
            raise SystemExit('REFUSE: duplicate row texts across templates')
        with open(os.path.join(a.out, 'audience_bank.jsonl'), 'w') as f:
            for r in allrows:
                f.write(json.dumps(r, sort_keys=True) + '\n')
        for c in CATS:
            with open(os.path.join(a.out, 'dump', 'AUD_%s.jsonl' % c), 'w') as f:
                for r in per[c]:
                    f.write(json.dumps(r, sort_keys=True) + '\n')
        census = dict(templates=len(keep), rows=len(allrows),
                      by_category={c: dict(templates=len({r['template_id'] for r in per[c]}), rows=len(per[c])) for c in CATS},
                      by_cls=dict(collections.Counter(r['cls'] for r in allrows)),
                      max_runs=max(r['prov']['n_runs'] for r in allrows), dropped=drop)
        json.dump(census, open(os.path.join(a.out, 'census.json'), 'w'), indent=1, sort_keys=True)
        files = ['audience_bank.jsonl', 'census.json'] + ['dump/AUD_%s.jsonl' % c for c in CATS]
        with open(os.path.join(a.out, 'BANK.md5'), 'w') as f:
            for fn in files:
                f.write('%s  %s\n' % (md5f(os.path.join(a.out, fn)), fn))
        print('bank: %d templates, %d rows %s -> %s' % (len(keep), len(allrows), census['by_category'], a.out))
        return 0


if __name__ == '__main__':
    sys.exit(main())
