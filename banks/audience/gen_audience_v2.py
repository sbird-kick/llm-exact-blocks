#!/usr/bin/env python3
"""gen_audience_v2.py -- audience bank v2: the v1 generator (gen_audience.py, frozen, imported unchanged) with two fill
fixes and one metadata label. DEMO FIT bank (not pre-registered; not a result). stdlib only.

Why (2026-10-01, after the v1 blind verification, verify_demo/report/VERIFY_REPORT_demo.md): B3 failed 11/199 on
  (a) the fill value 1 in a slot followed by a plural noun ("1 goals", "there are 1 coops"), and
  (b) a filled value that coincidentally equals another numeral (W2-018 "9 floors ... 9 school days"), so a second
      pair of numbers gives the same answer.

What changes against v1 (everything else is gen_audience.py itself: templates, validation, audit, constraints, seeds):
  1. PLURAL rule: a slot is "plural" when one of the (at most 3) lowercase words that follow it, before punctuation or
     a stop word, is a plural noun (ends in -s and is not in NONPL, or is in IRREG, which also holds "were" / "are").
     A plural slot never takes the value 1. The per-slot table is printed by --plural and written to the metadata.
  2. DISTINCT rule: the numerals of one text are pairwise different. The only exemption is ALLOW_EQUAL (W4-046,
     "We multiplied 3 by 3 to get 9": a square is the same pair twice, so no second pair can answer; without the
     exemption the template falls to 3 fills < MIN_FILL and v1's own validity check would drop it).
  3. The candidate stream is v1's: same seed string 'aud-v1:<tid>', same randint calls, same order. A candidate that
     breaks rule 1 or 2 is skipped with `continue` AFTER it is drawn, so no RNG is consumed differently.
  4. IN-PLACE refill: v1's first N_FILL distinct candidates keep their positions (and row_ids). Each one that breaks a
     rule is replaced, in order, by the next legal distinct candidate of the SAME stream after v1's last one. A hole
     with no replacement left in the 20000-draw budget is dropped (its row_id is simply absent). So every v1 row whose
     fill is legal is byte-identical in v2, except the label in 5.
  5. ANSWER-IN-TEXT label: the six templates whose writer op is 'answer_given' (W4-044..W4-049: the answer is already
     written in the text, by design) get row fields answer_in_text=true, design_class='lookup_echo'. Decided AFTER the
     v1 verdict. Their text is unchanged.
  Replaced rows carry source='audience_bank_v2' and v2_refill=<reason>; unchanged rows keep source='audience_bank_v1'.

  python3 gen_audience_v2.py --plural                    # the plural-slot table (for review)
  python3 gen_audience_v2.py --final --audit audit.json  # -> bank_v2/ (audience_bank_v2.jsonl, census, meta, md5)
  python3 gen_audience_v2.py --selftest                  # v2 vs v1, must end SELFTEST PASS n/n
The v1 files (gen_audience.py, writers/, audit.json, bank/) are read only and never written.
"""
import sys
sys.dont_write_bytecode = True
import argparse, collections, hashlib, json, os, random, re

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_audience as g1                                    # the frozen v1 generator (md5 4c24ab7c), imported unchanged

V1_BANK = os.path.join(HERE, 'bank', 'audience_bank.jsonl')
V1_MD5 = '79faccfff54544866ca897e5921f6b20'
OUT = os.path.join(HERE, 'bank_v2')
STOP = {'of', 'and', 'or', 'to', 'by', 'plus', 'minus', 'together', 'in', 'on', 'at', 'with', 'from', 'is', 'was',
        'equals', 'for', 'then', 'but'}
NONPL = {'bonus', 'plus', 'minus', 'is', 'was', 'has', 'its', 'this', 'his', 'as', 'us', 'yes', 'less', 'across',
         'picks'}                                            # 'picks': "Bus number {D1} picks up" is a verb
IRREG = {'people', 'feet', 'children', 'men', 'women', 'teeth', 'mice', 'geese', 'were', 'are'}
ALLOW_EQUAL = {'W4-046': 'A by B = C with A in [2,3], B in [3,4]: "3 by 3" is one pair (a square), no second pair'}
ANSWER_GIVEN_OP = 'answer_given'
SLOT_RE = g1.SLOT_RE


def md5f(p):
    return hashlib.md5(open(p, 'rb').read()).hexdigest()


def plural_slots(t):
    """{slot: (is_plural, words looked at)}"""
    out = {}
    for m in SLOT_RE.finditer(t['text']):
        mm = re.match(r"\s+([a-z']+)(?:\s+([a-z']+))?(?:\s+([a-z']+))?", t['text'][m.end():])
        ws = []
        for w in (mm.groups() if mm else ()):
            if w is None or w in STOP:
                break
            ws.append(w)
        out[m.group(1)] = (any((w.endswith('s') and w not in NONPL) or w in IRREG for w in ws), ws)
    return out


def why_illegal(t, vals, pl):
    why = []
    if any(pl[s][0] and vals[s] == 1 for s in vals):
        why.append('one_before_plural')
    if t['tid'] not in ALLOW_EQUAL and len(set(vals.values())) < len(vals):
        why.append('equal_numerals')
    return why


def draw_v2(t, n, check_only=False):
    """v1's draw() loop, verbatim in its candidate logic, + the in-place refill of illegal fills (module docstring 3-4).
    Returns [(vals, ans, filled, slot_index, refill_reason_or_None)] in slot order (holes dropped)."""
    rng = random.Random(int(hashlib.md5(('aud-v1:' + t['tid']).encode()).hexdigest(), 16))
    pl = plural_slots(t)
    v1, extra, seen = [], [], set()
    for _ in range(20000):
        vals = {s: rng.randint(r[0], r[1]) for s, r in t['slots'].items()}
        try:
            if not all(g1.ev(c, vals) for c in t['constraints']):
                continue
            ans = g1.ev(t['answer'], vals)
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
        if len(v1) < n:                                       # v1's own fill, in v1's position
            v1.append((vals, ans, filled, why_illegal(t, vals, pl)))
            continue
        if why_illegal(t, vals, pl):                          # past v1's last fill: only legal refills
            continue
        extra.append((vals, ans, filled))
        if len(extra) >= sum(bool(w) for (_, _, _, w) in v1):
            break
    out, it = [], iter(extra)
    for i, (vals, ans, filled, why) in enumerate(v1):
        if not why:
            out.append((vals, ans, filled, i, None))
            continue
        nxt = next(it, None)
        if nxt is not None:
            out.append(nxt + (i, '+'.join(why)))
    return out


def check_v2(t):
    """v1's check() with v2's draw (so the MIN_FILL rule counts legal fills)"""
    def d(t_, n, check_only=False):
        x = draw_v2(t_, n)
        return x if isinstance(x, str) else [y[:3] for y in x]
    orig = g1.draw
    g1.draw = d
    try:
        return g1.check(t)
    finally:
        g1.draw = orig


def make_rows_v2(t):
    """v1's make_rows() row schema, field for field; row_id index = the v1 slot index"""
    rows = []
    order = SLOT_RE.findall(t['text'])
    for (vals, ans, filled, i, why) in draw_v2(t, g1.N_FILL):
        if re.search(r'the answer is\s*:?\s*$', filled, re.I) or filled[-1] in g1.DIRECT:
            raise SystemExit('REFUSE: %s fill ends in the cue / a direct char' % t['tid'])
        text = (filled + ' ' + g1.CUE).strip()
        runs = re.findall(r'\d+', text)
        if runs != [str(vals[s]) for s in order]:
            raise SystemExit('REFUSE: %s runs %s != slot values' % (t['tid'], runs))
        gold = [order.index(s) for s in t['operands']]
        single = t['category'] == 'single'
        a_ = vals[t['operands'][0]]
        b_ = vals[t['operands'][1]] if len(t['operands']) > 1 else t.get('word_operand')
        r = dict(
            row_id='aud:%s:%02d' % (t['tid'], i), template_id=t['tid'], category=t['category'],
            op=g1.LONG[t['op']] if single else t['op'], opshort=t['op'], cls=t['op'] if single else 'OTHER',
            in_set=single, gate_label='fire' if single else 'abstain', family='aud-' + t['category'],
            a=a_, b=b_, ans=int(ans), list_values=[vals[s] for s in order], n_numerals_written=len(runs), k=len(runs),
            prov=dict(gold_run_idx=gold, gold_run_values=[str(vals[s]) for s in t['operands']],
                      locator='regex \\d+ (comma-free ASCII)', n_runs=len(runs)),
            lang='en', status='scored', slot_mode='whole', cut=True, grade='demo',
            source='audience_bank_v1' if why is None else 'audience_bank_v2',
            tags=t.get('tags', []), word_operand=t.get('word_operand'), text=text)
        if why is not None:
            r['v2_refill'] = why
        if t['op'] == ANSWER_GIVEN_OP:
            r['answer_in_text'] = True
            r['design_class'] = 'lookup_echo'
        rows.append(r)
    return rows


def template_set():
    """v1's template selection (mechanically valid, no duplicate text, audit OK) -- recomputed with check_v2"""
    T = g1.load_templates()
    dup_t = {k for k, v in collections.Counter(t['text'] for t in T).items() if v > 1}
    V = {t['tid']: check_v2(t) for t in T}
    au = {x['tid']: x for x in json.load(open(os.path.join(HERE, 'audit.json')))}
    keep = [t for t in T if not V[t['tid']] and t['text'] not in dup_t and au.get(t['tid'], {}).get('verdict') == 'OK']
    return T, V, keep


def build(out=OUT):
    T, V, keep = template_set()
    bad = {k: v for k, v in V.items() if v}
    print('templates kept %d (v1 kept 199); invalid under v2 rules: %s' % (len(keep), bad))
    os.makedirs(os.path.join(out, 'dump'), exist_ok=True)
    allrows, per = [], collections.defaultdict(list)
    for t in keep:
        rs = make_rows_v2(t)
        allrows += rs
        per[t['category']] += rs
    texts = collections.Counter(r['text'] for r in allrows)
    if max(texts.values()) > 1:
        raise SystemExit('REFUSE: duplicate row texts across templates')
    with open(os.path.join(out, 'audience_bank_v2.jsonl'), 'w') as f:
        for r in allrows:
            f.write(json.dumps(r, sort_keys=True) + '\n')
    for c in g1.CATS:
        with open(os.path.join(out, 'dump', 'AUD_%s.jsonl' % c), 'w') as f:
            for r in per[c]:
                f.write(json.dumps(r, sort_keys=True) + '\n')
    meta = {}
    for t in keep:
        pl = plural_slots(t)
        meta[t['tid']] = dict(category=t['category'], op=t['op'], plural_slots=sorted(s for s in pl if pl[s][0]),
                              allow_equal=ALLOW_EQUAL.get(t['tid']),
                              answer_in_text=t['op'] == ANSWER_GIVEN_OP,
                              design_class='lookup_echo' if t['op'] == ANSWER_GIVEN_OP else None,
                              rows=sum(r['template_id'] == t['tid'] for r in allrows),
                              rows_refilled=sum(r['template_id'] == t['tid'] and 'v2_refill' in r for r in allrows))
    json.dump(dict(note='audience bank v2 template metadata; answer_in_text labels decided 2026-10-01 AFTER the v1 '
                        'blind-verification verdict (B3 11/199); text unchanged', templates=meta),
              open(os.path.join(out, 'templates_meta_v2.json'), 'w'), indent=1, sort_keys=True)
    census = dict(templates=len(keep), rows=len(allrows),
                  by_category={c: dict(templates=len({r['template_id'] for r in per[c]}), rows=len(per[c])) for c in g1.CATS},
                  by_cls=dict(collections.Counter(r['cls'] for r in allrows)),
                  max_runs=max(r['prov']['n_runs'] for r in allrows),
                  refilled=dict(collections.Counter(r['v2_refill'] for r in allrows if 'v2_refill' in r)),
                  answer_in_text_templates=sorted(k for k, m in meta.items() if m['answer_in_text']))
    json.dump(census, open(os.path.join(out, 'census_v2.json'), 'w'), indent=1, sort_keys=True)
    files = ['audience_bank_v2.jsonl', 'census_v2.json', 'templates_meta_v2.json'] + \
            ['dump/AUD_%s.jsonl' % c for c in g1.CATS]
    with open(os.path.join(out, 'BANK_v2.md5'), 'w') as f:
        for fn in files:
            f.write('%s  %s\n' % (md5f(os.path.join(out, fn)), fn))
    print('bank v2: %d templates, %d rows %s -> %s' % (len(keep), len(allrows), census['by_category'], out))
    return allrows


def compare(v2path=os.path.join(OUT, 'audience_bank_v2.jsonl')):
    """v1 vs v2 by row_id. 'unchanged' = byte-identical JSON after removing the two answer_in_text label fields."""
    if md5f(V1_BANK) != V1_MD5:
        raise SystemExit('REFUSE: v1 bank md5 changed')
    v1 = {json.loads(l)['row_id']: l.strip() for l in open(V1_BANK)}
    v2 = {json.loads(l)['row_id']: l.strip() for l in open(v2path)}

    def strip(line):
        d = json.loads(line)
        d.pop('answer_in_text', None); d.pop('design_class', None)
        return json.dumps(d, sort_keys=True)
    unchanged = [k for k in v1 if k in v2 and strip(v2[k]) == v1[k]]
    replaced = [k for k in v1 if k in v2 and strip(v2[k]) != v1[k]]
    dropped = [k for k in v1 if k not in v2]
    added = [k for k in v2 if k not in v1]
    return v1, v2, unchanged, replaced, dropped, added


def selftest():
    res = []

    def ck(name, ok):
        res.append(bool(ok)); print('  %s %s' % ('ok  ' if ok else 'FAIL', name))
    T = {t['tid']: t for t in g1.load_templates()}
    v1, v2, unch, repl, drop, add = compare()
    R1 = {k: json.loads(l) for k, l in v1.items()}
    R2 = {k: json.loads(l) for k, l in v2.items()}
    ck('v1 bank md5 %s pinned; v1 rows %d, v2 rows %d' % (V1_MD5[:8], len(v1), len(v2)), len(v1) == 3163)
    ck('templates: v1 %d, v2 %d, same set' % (len({r['template_id'] for r in R1.values()}),
                                              len({r['template_id'] for r in R2.values()})),
       {r['template_id'] for r in R1.values()} == {r['template_id'] for r in R2.values()})
    pl = {tid: plural_slots(t) for tid, t in T.items()}

    def order(tid):
        return SLOT_RE.findall(T[tid]['text'])

    def ill(r):
        vals = dict(zip(order(r['template_id']), r['list_values']))
        return why_illegal(T[r['template_id']], vals, pl[r['template_id']])
    n1p = [k for k, r in R2.items() if 'one_before_plural' in ill(r)]
    ck('v2: rows with 1 before a plural noun (slot rule): %d/%d' % (len(n1p), len(R2)), not n1p)
    def text_one_plural(text):
        """the same rule re-applied on the filled TEXT at every numeral 1 (catches slot-to-text mapping bugs)"""
        hits = []
        for m in re.finditer(r'(?<!\d)1(?!\d)', text):
            mm = re.match(r"\s+([a-z']+)(?:\s+([a-z']+))?(?:\s+([a-z']+))?", text[m.end():])
            for w in (mm.groups() if mm else ()):
                if w is None or w in STOP:
                    break
                if (w.endswith('s') and w not in NONPL) or w in IRREG:
                    hits.append(text[max(0, m.start() - 20):m.end() + 25])
                    break
        return hits
    rx_bad = [k for k, r in R2.items() if text_one_plural(r['text'][:-len(' The answer is')])]
    rx_v1 = [k for k, r in R1.items() if text_one_plural(r['text'][:-len(' The answer is')])]
    ck('text re-check "1 <up to 3 words incl. a plural>": v2 %d/%d (v1 had %d/%d)' % (
        len(rx_bad), len(R2), len(rx_v1), len(R1)), not rx_bad and len(rx_v1) > 0)
    dup = [k for k, r in R2.items() if len(set(r['list_values'])) < len(r['list_values'])
           and r['template_id'] not in ALLOW_EQUAL]
    dup_allowed = [k for k, r in R2.items() if len(set(r['list_values'])) < len(r['list_values'])
                   and r['template_id'] in ALLOW_EQUAL]
    ck('v2: rows with two equal numerals outside ALLOW_EQUAL: %d/%d (inside ALLOW_EQUAL W4-046: %d)' % (
        len(dup), len(R2), len(dup_allowed)), not dup)
    v1_legal = [k for k, r in R1.items() if not ill(r)]
    v1_illegal = [k for k, r in R1.items() if ill(r)]
    ck('every v1 row with a legal fill is unchanged in v2 (byte-identical, label fields aside): %d/%d legal; '
       'unchanged %d' % (sum(k in unch for k in v1_legal), len(v1_legal), len(unch)),
       set(v1_legal) == set(unch))
    ck('every v1 row with an illegal fill is replaced or dropped: %d/%d (replaced %d, dropped %d), none kept' % (
        len(set(repl) | set(drop)), len(v1_illegal), len(repl), len(drop)),
       set(v1_illegal) == set(repl) | set(drop) and not add)
    ck('replaced rows carry source audience_bank_v2 + v2_refill, unchanged rows source v1: %d + %d' % (
        sum(R2[k]['source'] == 'audience_bank_v2' and 'v2_refill' in R2[k] for k in repl),
        sum(R2[k]['source'] == 'audience_bank_v1' and 'v2_refill' not in R2[k] for k in unch)),
       all(R2[k]['source'] == 'audience_bank_v2' and 'v2_refill' in R2[k] for k in repl)
       and all(R2[k]['source'] == 'audience_bank_v1' for k in unch))
    # the refills come from v1's own candidate stream: re-run v1's draw with a large n and find each refill text
    # after v1's 16 fills, in order
    okstream, nchk = 0, 0
    for tid in sorted({R2[k]['template_id'] for k in repl}):
        stream = [f for (_, _, f) in g1.draw(T[tid], 400)]
        v1_texts = [R1[k]['text'] for k in sorted(R1) if R1[k]['template_id'] == tid]
        new = [R2[k]['text'][:-len(' The answer is')] for k in sorted(repl) if R2[k]['template_id'] == tid]
        pos = [stream.index(x) if x in stream else -1 for x in new]
        nchk += 1
        okstream += all(p >= len(v1_texts) for p in pos) and pos == sorted(pos)
    ck('refill texts are later candidates of v1\'s own seeded stream (after v1\'s fills, in order): %d/%d templates' % (
        okstream, nchk), okstream == nchk)
    gold_bad = 0
    for k, r in R2.items():
        t = T[r['template_id']]
        vals = dict(zip(order(r['template_id']), r['list_values']))
        gold_bad += g1.ev(t['answer'], vals) != r['ans'] or not all(g1.ev(c, vals) for c in t['constraints'])
        gold_bad += re.findall(r'\d+', r['text']) != [str(v) for v in r['list_values']]
    ck('v2 gold == template answer, constraints hold, numerals == regex runs: bad %d/%d' % (gold_bad, len(R2)),
       gold_bad == 0)
    ait = sorted({r['template_id'] for r in R2.values() if r.get('answer_in_text')})
    ck('answer_in_text label on exactly the answer_given templates %s, every row of them' % ait,
       ait == sorted(tid for tid, t in T.items() if t['op'] == ANSWER_GIVEN_OP and tid in {r['template_id'] for r in R2.values()})
       and all(r.get('answer_in_text') for r in R2.values() if T[r['template_id']]['op'] == ANSWER_GIVEN_OP))
    ck('plural rule seen failing on v1: v1 rows with 1 before a plural %d, with equal numerals %d' % (
        sum('one_before_plural' in ill(r) for r in R1.values()), sum('equal_numerals' in ill(r) for r in R1.values())),
       sum('one_before_plural' in ill(r) for r in R1.values()) > 0)
    ck('the v1 flagged fills are gone from v2: %s' % ['aud:W1-020:14', 'aud:W2-018:06', 'aud:W3-012:05'],
       all(k not in v2 or v2[k] != v1[k] for k in ('aud:W1-020:14', 'aud:W2-018:06', 'aud:W3-012:05', 'aud:W2-013:00',
                                                     'aud:W2-032:01', 'aud:W3-008:03', 'aud:W3-052:12', 'aud:W4-049:11')))
    n = sum(res)
    print('SELFTEST %s %d/%d' % ('PASS' if n == len(res) else 'FAIL', n, len(res)))
    return n == len(res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plural', action='store_true'); ap.add_argument('--final', action='store_true')
    ap.add_argument('--audit', default=''); ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--out', default=OUT)
    a = ap.parse_args()
    if a.plural:
        for t in g1.load_templates():
            for s, (p, ws) in plural_slots(t).items():
                lo, hi = t['slots'][s]
                print('%s %s %s range [%d,%d] words %s' % ('PLURAL' if p else 'plain ', t['tid'], s, lo, hi, ws))
        return 0
    if a.final:
        if os.path.abspath(a.out) == os.path.abspath(os.path.join(HERE, 'bank')):
            raise SystemExit('REFUSE: never write into the frozen v1 bank/')
        if a.audit and os.path.abspath(a.audit) != os.path.join(HERE, 'audit.json'):
            raise SystemExit('REFUSE: v2 uses the v1 audit.json')
        build(a.out)
        return 0
    if a.selftest:
        return 0 if selftest() else 1


if __name__ == '__main__':
    sys.exit(main())
