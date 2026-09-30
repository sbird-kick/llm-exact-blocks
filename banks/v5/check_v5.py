#!/usr/bin/env python3
"""check_v5.py -- BANK v5 blind verification: the format gate for verifiers, the writer-vs-verifier comparison, and
the cleaning rule (stdlib only).

    python3 check_v5.py --format <blind/V5-gG-uNN.blind.json> <verify/V5-gG-uNN.json>   # verifiers run this
    python3 check_v5.py --report                      # every finished verify file -> VERIFY_REPORT_v5.md + VERIFY_DISAGREE_v5.jsonl
    python3 check_v5.py --clean [--out clean/clean_v5.json]   # verified templates -> the generator's input
    python3 check_v5.py --selftest

What the verifier answers per text (VERIFY_v5.md), and what it is compared with (the key, which it never sees):
  op              add / sub / mul / div / other       vs the template's op
  operands        the TWO slot letters the question uses        vs the letters of the writer's {M} and {S}
  role            sub: the letter subtracted FROM; div: the letter DIVIDED (the dividend); else null
                                                                vs the letter of the writer's {M}
  signed_natural  sub only: would a negative answer read naturally?   vs the writer's `signed`
  flags, note
CLEANING RULE (per template; all four of its texts, or the two order texts when bases were sampled):
  D1 drop when any text's op, operand pair or role (sub/div) differs from the writer's labels;
  D2 drop when any text carries a flag other than number_dependent_grammar (that flag alone keeps the template and
     tags it `numdep`, as in DIVMOD clean_div.py D2);
  D4 a signed sub template that a verifier reads as NOT signed-natural on any text is kept but DEMOTED (tag `demoted`):
     gen_v5.py then fills it minuend-larger only, with the redraw twin.
  A template whose base texts were not in the blind sample (make_blind_v5 --base-sample < 1) is tagged
  `bases_unverified`; its rows carry the tag so a quoted number can exclude them.
Templates whose verifier unit is not done yet are listed as pending, never kept.
"""
import sys
sys.dont_write_bytecode = True   # no __pycache__: write nothing beyond the files the brief names
import argparse
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import v5_common as C  # noqa: E402

OPS_V = ('add', 'sub', 'mul', 'div', 'other')
FLAGS = ('unnatural', 'ungrammatical', 'ambiguous', 'hidden_operand', 'not_single_step', 'wrong_language',
         'number_dependent_grammar', 'another_pair_answers', 'leftover_or_rounding', 'cue_mismatch', 'other')
KEEP_FLAG = 'number_dependent_grammar'
ITEM_KEYS = {'id', 'op', 'operands', 'role', 'signed_natural', 'flags', 'note'}


def fmt_fails(blind, ver):
    f = []
    if not isinstance(ver, dict) or set(ver) != {'verifier_unit', 'items'}:
        return ['top level must be an object with exactly verifier_unit, items']
    if ver['verifier_unit'] != blind['verifier_unit']:
        f.append('verifier_unit %r must be %r' % (ver['verifier_unit'], blind['verifier_unit']))
    text = {i['id']: i['text'] for i in blind['items']}
    got = collections.Counter()
    for it in ver['items'] if isinstance(ver['items'], list) else []:
        if not isinstance(it, dict) or set(it) != ITEM_KEYS:
            f.append('item %r: keys must be exactly %s' % (it if not isinstance(it, dict) else it.get('id'), sorted(ITEM_KEYS)))
            continue
        i = it['id']
        got[i] += 1
        if i not in text:
            continue
        letters = set(C.placeholders(text[i]))
        if it['op'] not in OPS_V:
            f.append('%s: op %r not one of %s' % (i, it['op'], ' '.join(OPS_V)))
        ops_ = it['operands']
        if not (isinstance(ops_, list) and len(ops_) == 2 and len(set(ops_)) == 2 and all(x in letters for x in ops_)):
            if it['op'] != 'other' or ops_ is not None:
                f.append('%s: operands must be two different slot letters of the text (%s), or null with op "other"' % (i, sorted(letters)))
        if it['op'] in ('sub', 'div'):
            if not (isinstance(ops_, list) and it['role'] in ops_):
                f.append('%s: role must be one of the two operand letters for sub / div' % i)
        elif it['role'] is not None:
            f.append('%s: role must be null unless op is sub or div' % i)
        if it['op'] == 'sub':
            if not isinstance(it['signed_natural'], bool):
                f.append('%s: signed_natural must be true or false for sub' % i)
        elif it['signed_natural'] is not None:
            f.append('%s: signed_natural must be null unless op is sub' % i)
        if not isinstance(it['flags'], list) or any(x not in FLAGS for x in it['flags']):
            f.append('%s: flags must be a list drawn from %s' % (i, ' '.join(FLAGS)))
        if not isinstance(it['note'], str):
            f.append('%s: note must be a string' % i)
        elif (it['flags'] or it['op'] == 'other') and not it['note'].strip():
            f.append('%s: a flag or op "other" needs a note' % i)
    missing = [i for i in text if got[i] == 0]
    if missing:
        f.append('missing ids: %s' % ' '.join(missing[:20]))
    dup = [i for i, n in got.items() if n > 1]
    if dup:
        f.append('ids more than once: %s' % ' '.join(dup[:20]))
    extra = [i for i in got if i not in text]
    if extra:
        f.append('unknown ids: %s' % ' '.join(extra[:20]))
    return f


def expected(k):
    inv = {v: L for L, v in k['slots'].items()}
    return dict(op=k['op'], operands=sorted([inv['M'], inv['S']]), role=inv['M'] if k['op'] in ('sub', 'div') else None,
                signed=k['signed'] if k['op'] == 'sub' else None)


def judge(k, v):
    """(ok_op, ok_operands, ok_role or None, signed agreement or None, drop reasons, tags)."""
    e = expected(k)
    ok_op = v['op'] == e['op']
    ok_opr = isinstance(v['operands'], list) and sorted(v['operands']) == e['operands']
    ok_role = (v['role'] == e['role']) if e['role'] else None
    sg = (v['signed_natural'] == e['signed']) if (e['signed'] is not None and v['op'] == 'sub') else None
    why, tags = [], []
    if not ok_op:
        why.append('D1 op %s (want %s)' % (v['op'], e['op']))
    if not ok_opr:
        why.append('D1 operands %s (want %s)' % (v['operands'], e['operands']))
    if ok_role is False:
        why.append('D1 role %s (want %s)' % (v['role'], e['role']))
    fl = [x for x in v['flags'] if x != KEEP_FLAG]
    if fl:
        why.append('D2 flags %s' % ','.join(fl))
    if KEEP_FLAG in v['flags']:
        tags.append('numdep')
    if e['signed'] and v['op'] == 'sub' and v['signed_natural'] is False:
        tags.append('demoted')
    return ok_op, ok_opr, ok_role, sg, why, tags


def done_units(root, manifest):
    """[(verifier unit, blind, key, verify)] for every verifier unit whose latest verify file passes the format gate."""
    import status_v5 as S
    out = []
    for v in manifest['verifier_units']:
        bp = os.path.join(root, v['blind'])
        att = S.verify_attempts(root, v['uid'])
        if not os.path.exists(bp) or not att:
            continue
        bl, ve = C.load_json(bp), C.load_json(att[max(att)])
        if fmt_fails(bl, ve):
            continue
        out.append((v, bl, C.load_json(os.path.join(root, v['key'])), ve))
    return out


def report(root, manifest, write=True):
    per = collections.defaultdict(collections.Counter)
    conf, fl, rows = collections.Counter(), collections.Counter(), []
    for v, bl, key, ve in done_units(root, manifest):
        text = {i['id']: i['text'] for i in bl['items']}
        for it in ve['items']:
            k = key[it['id']]
            ok_op, ok_opr, ok_role, sg, why, tags = judge(k, it)
            c = per[k['lang']]
            c['n'] += 1; c['op'] += ok_op; c['operands'] += ok_opr
            if ok_role is not None:
                c['n_role'] += 1; c['role'] += ok_role
            if sg is not None:
                c['n_signed'] += 1; c['signed'] += sg
            c['all'] += ok_op and ok_opr and ok_role is not False
            c['flagged'] += bool(it['flags'])
            conf[(k['op'], it['op'])] += 1
            for x in it['flags']:
                fl[x] += 1
            if why or it['flags'] or sg is False:
                rows.append(dict(blind_id=it['id'], lang=k['lang'], template=k['template'], variant=k['variant'],
                                 text=text[it['id']], want=expected(k), got={x: it[x] for x in ('op', 'operands', 'role', 'signed_natural')},
                                 flags=it['flags'], note=it['note'], reasons=why))
    out = ['# BANK v5 -- blind verification report (check_v5.py)', '',
           '| lang | texts | op | operands | role (sub/div) | signed (sub) | all three | flagged |', '|---|---|---|---|---|---|---|---|']
    tot = collections.Counter()
    for lang in sorted(per, key=lambda l: C.LANGS.index(l) if l in C.LANGS else 99):
        c = per[lang]; tot.update(c)
        out.append('| %s | %d | %d/%d | %d/%d | %d/%d | %d/%d | %d/%d | %d/%d |' % (
            lang, c['n'], c['op'], c['n'], c['operands'], c['n'], c['role'], c['n_role'], c['signed'], c['n_signed'],
            c['all'], c['n'], c['flagged'], c['n']))
    c = tot
    out.append('| **all** | %d | %d/%d | %d/%d | %d/%d | %d/%d | %d/%d | %d/%d |' % (
        c['n'], c['op'], c['n'], c['operands'], c['n'], c['role'], c['n_role'], c['signed'], c['n_signed'], c['all'], c['n'],
        c['flagged'], c['n']))
    out += ['', '## op: writer (rows) x verifier (columns)', '', '| writer | ' + ' | '.join(OPS_V) + ' |', '|---|' + '---|' * len(OPS_V)]
    for o in C.OPS:
        out.append('| %s | ' % o + ' | '.join(str(conf[(o, x)]) for x in OPS_V) + ' |')
    out += ['', '## flags (texts carrying each flag)', ''] + (['- %s: %d' % kv for kv in fl.most_common()] or ['- none'])
    if write:
        with open(os.path.join(root, 'VERIFY_REPORT_v5.md'), 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(out) + '\n')
        with open(os.path.join(root, 'VERIFY_DISAGREE_v5.jsonl'), 'w', encoding='utf-8') as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    return out, tot, rows


def clean(root, manifest):
    """-> dict(kept, dropped, pending_units)."""
    import validate_v5 as V
    stamps = V.latest_stamps(os.path.join(root, 'accept'))
    verdict = collections.defaultdict(lambda: dict(why=[], tags=set(), n=0, variants=set()))
    covered = set()
    for v, bl, key, ve in done_units(root, manifest):
        covered.update(v['deps'])
        for it in ve['items']:
            k = key[it['id']]
            _, _, _, _, why, tags = judge(k, it)
            d = verdict[k['template']]
            d['n'] += 1; d['why'] += ['%s: %s' % (k['variant'], w) for w in why]; d['tags'].update(tags)
            d['variants'].add(k['variant'])
    kept, dropped, pending = [], [], []
    for u in manifest['writer_units']:
        st = stamps.get(u['uid'])
        if not st or st.get('status') != 'accepted':
            continue
        if u['uid'] not in covered:
            pending.append(u['uid'])
            continue
        doc = C.load_json(os.path.join(root, st['file']))
        for it in doc['items']:
            d = verdict.get(it['id'])
            if d is None or d['n'] == 0:
                pending.append(it['id'])
                continue
            tags = sorted(d['tags'] | ({'bases_unverified'} if not {'base_ex', 'base_sem'} <= d['variants'] else set()))
            if 'demoted' in tags and not it.get('signed'):
                tags.remove('demoted')
            if d['why']:
                dropped.append(dict(template=it['id'], lang=doc['language_code'], reasons=d['why']))
            else:
                kept.append(dict(lang=doc['language_code'], lead_in=doc['lead_in'], uid=doc['writer_unit'],
                                 slice=doc['slice'], template=it, tags=tags,
                                 verifier=dict(tag='V5', texts_read=d['n'], tags=tags)))
    return dict(kept=kept, dropped=dropped, pending_units=pending)


def write_clean(root, manifest, out):
    res = clean(root, manifest)
    txt = json.dumps(res, ensure_ascii=False, indent=1) + '\n'
    if os.path.exists(out):
        with open(out, encoding='utf-8') as fh:
            if fh.read() != txt:
                print('REFUSED: %s exists and differs; name a new --out (files are never overwritten)' % out)
                return 1
    else:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, 'w', encoding='utf-8') as fh:
            fh.write(txt)
    by = collections.defaultdict(collections.Counter)
    for e in res['kept']:
        by[e['lang']]['kept'] += 1
        by[e['lang']]['numdep'] += 'numdep' in e['tags']; by[e['lang']]['demoted'] += 'demoted' in e['tags']
    for e in res['dropped']:
        by[e['lang']]['dropped'] += 1
    lines = ['# BANK v5 cleaning (check_v5.py --clean)', '', '| lang | kept | dropped | numdep-tagged | demoted |', '|---|---|---|---|---|']
    for lang in sorted(by):
        c = by[lang]
        lines.append('| %s | %d | %d | %d | %d |' % (lang, c['kept'], c['dropped'], c['numdep'], c['demoted']))
    lines.append('')
    lines.append('kept %d, dropped %d, pending (unverified) %d; md5 of %s: %s' % (
        len(res['kept']), len(res['dropped']), len(res['pending_units']), os.path.basename(out), C.md5_file(out)))
    notes = os.path.splitext(out)[0] + '_NOTES.md'
    if not os.path.exists(notes):
        with open(notes, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    return 0


def selftest():
    import copy
    import shutil
    import make_blind_v5 as MB
    ok = True

    def chk(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print('  %s  %s' % ('ok  ' if cond else 'FAIL', name))

    root, fm = MB.fake_tree()
    v = fm['verifier_units'][0]
    MB.write_one(v, root, fm)
    bl, key = C.load_json(os.path.join(root, v['blind'])), C.load_json(os.path.join(root, v['key']))

    def perfect():
        items = []
        for i in bl['items']:
            e = expected(key[i['id']])
            items.append(dict(id=i['id'], op=e['op'], operands=list(e['operands']), role=e['role'],
                              signed_natural=e['signed'], flags=[], note=''))
        return dict(verifier_unit=v['uid'], items=items)

    p = perfect()
    chk('perfect verify file passes the format gate', fmt_fails(bl, p) == [])
    C.dump_json(os.path.join(root, v['out']), p)
    out, tot, rows = report(root, fm, write=False)
    chk('perfect: op / operands / all 96/96, role %d/%d, 0 disagreement rows' % (tot['role'], tot['n_role']),
        tot['n'] == 96 and tot['op'] == tot['operands'] == tot['all'] == 96 and tot['role'] == tot['n_role'] and not rows)
    res = clean(root, fm)
    chk('perfect: clean keeps all 24 templates', len(res['kept']) == 24 and not res['dropped'])
    # mutations
    q = copy.deepcopy(p)
    first_sub = next(i for i, it in enumerate(q['items']) if it['op'] == 'sub')
    q['items'][first_sub]['role'] = [x for x in q['items'][first_sub]['operands'] if x != q['items'][first_sub]['role']][0]
    tid_role = key[q['items'][first_sub]['id']]['template']
    first_div = next(i for i, it in enumerate(q['items']) if it['op'] == 'div')
    q['items'][first_div]['flags'] = ['number_dependent_grammar']; q['items'][first_div]['note'] = 'case ending'
    tid_nd = key[q['items'][first_div]['id']]['template']
    signed_sub = next(i for i, it in enumerate(q['items']) if it['op'] == 'sub' and it['signed_natural'] is True
                      and key[it['id']]['template'] != tid_role)
    q['items'][signed_sub]['signed_natural'] = False
    tid_dem = key[q['items'][signed_sub]['id']]['template']
    first_add = next(i for i, it in enumerate(q['items']) if it['op'] == 'add')
    q['items'][first_add]['flags'] = ['unnatural']; q['items'][first_add]['note'] = 'odd'
    tid_un = key[q['items'][first_add]['id']]['template']
    chk('mutated file still passes the format gate', fmt_fails(bl, q) == [])
    C.dump_json(os.path.join(root, 'verify', v['uid'] + '.r1.json'), q)
    out, tot, rows = report(root, fm, write=False)
    chk('one role miss -> role %d/%d, all 95/96; 4 disagreement rows' % (tot['role'], tot['n_role']),
        tot['role'] == tot['n_role'] - 1 and tot['all'] == 95 and len(rows) == 4)
    res = clean(root, fm)
    kept = {e['template']['id']: e for e in res['kept']}
    chk('role miss drops its template (D1)', tid_role not in kept and any(d['template'] == tid_role for d in res['dropped']))
    chk('unnatural flag drops its template (D2)', tid_un not in kept)
    chk('numdep flag alone keeps + tags', tid_nd in kept and 'numdep' in kept[tid_nd]['tags'])
    chk('signed read as unnatural demotes, keeps', tid_dem in kept and 'demoted' in kept[tid_dem]['tags'])
    chk('kept + dropped = 24', len(res['kept']) + len(res['dropped']) == 24)
    # format failures
    b2 = copy.deepcopy(p)
    b2['items'] = b2['items'][1:] + [dict(b2['items'][1])]
    b2['items'][0]['flags'] = ['unnatural']
    b2['items'][2]['role'] = None if b2['items'][2]['op'] in ('sub', 'div') else 'A'
    b2['items'][3]['operands'] = ['A', 'Z']
    f = fmt_fails(bl, b2)
    chk('format catches missing id, duplicate id, flag without note, bad role, bad operand letter (%d)' % len(f), len(f) >= 5)
    # gen_v5 accepts the clean output
    import gen_v5 as G
    ents = [dict(e, verified=True) for e in res['kept']]
    rows_, tab, st = G.build(ents)
    bad = G.V.row_violations(rows_)[0]
    dem = [r for r in rows_ if r['template_id'] == tid_dem]
    chk('gen_v5 fills the cleaned set with 0 violations; the demoted template is filled unsigned (redraw)',
        not bad and dem and all(r['twin_kind'] == 'redraw' and r['kind'] == 'pos' for r in dem))
    shutil.rmtree(root)
    C.selftest_cleanup()
    print('SELFTEST check_v5: %s' % ('0 fail' if ok else 'FAIL'))
    return ok


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--format', nargs=2, metavar=('BLIND', 'VERIFY'))
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--clean', action='store_true')
    ap.add_argument('--out', default=os.path.join(HERE, 'clean', 'clean_v5.json'))
    a = ap.parse_args(argv[1:])
    if a.selftest:
        return 0 if selftest() else 1
    if a.format:
        try:
            bl, ve = C.load_json(a.format[0]), C.load_json(a.format[1])
        except (OSError, ValueError) as e:
            print('FORMAT FAIL cannot read: %s' % e)
            return 1
        f = fmt_fails(bl, ve)
        for x in f:
            print('FAIL ' + x)
        print('FORMAT ok %d' % len(bl['items']) if not f else 'FORMAT FAIL %d problem(s)' % len(f))
        return 1 if f else 0
    m = C.load_json(os.path.join(HERE, 'manifest_v5.json'))
    if a.report:
        out, _, rows = report(HERE, m)
        print('\n'.join(out))
        print('disagreeing or flagged texts: %d -> VERIFY_DISAGREE_v5.jsonl' % len(rows))
        return 0
    if a.clean:
        return write_clean(HERE, m, a.out)
    ap.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
