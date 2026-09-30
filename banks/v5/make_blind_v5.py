#!/usr/bin/env python3
"""make_blind_v5.py -- blind files for the BANK v5 Opus-medium verifiers (stdlib only).

    python3 make_blind_v5.py V5-g1-u01 [V5-g2-u01 ...]     # one verifier unit each (deps must be ACCEPTED)
    python3 make_blind_v5.py --ready [--tier T2]            # every verifier unit status_v5 calls ready
    python3 make_blind_v5.py --selftest

One verifier unit = one group of 5 languages x one unit number = the 5 accepted writer units W5-<lang>-uNN, 12
templates each. Every template becomes FOUR blind texts, so that every string the writer wrote is read blind once:
    first      facts_first  + question                      (3 numerals: {M} {S} {T})
    second     facts_second + question                      (3 numerals)
    base_ex    ex_sentence  + base_first + question         (3 numerals: {D} {M} {S})
    base_sem   base_second  + sem_sentence + question       (3 numerals: {M} {S} {D})
The slots are RENAMED in order of appearance to {A} {B} {C}, so the file says nothing about which slot the writer
labelled the minuend / dividend or which is the distractor; the 240 texts are shuffled by a stable hash across
languages, templates and variants (opaque ids <unit>-tNNN). The key (blind id -> template, variant, op, and the
letter -> writer-slot map) goes to blind_key/, which verifiers never read.
`--base-sample F` keeps the two base texts for a seeded fraction F of the templates only (the verification-sampling
option of DESIGN_v5.md section 6; default 1.0 = full). Files are never overwritten: an existing blind file must be
byte-identical to the regenerated one, else the run is refused.
"""
import sys
sys.dont_write_bytecode = True   # no __pycache__: write nothing beyond the files the brief names
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import v5_common as C  # noqa: E402
import validate_v5 as V  # noqa: E402

SEED = 'v5-blind-1'
LETTERS = 'ABCDE'
VARIANTS = ('first', 'second', 'base_ex', 'base_sem')


def compose(it, variant, sep):
    """(text with writer slots, role of each slot token in order)."""
    q = it['question'].strip()
    if variant == 'first':
        t = it['facts_first'].strip() + sep + q
    elif variant == 'second':
        t = it['facts_second'].strip() + sep + q
    elif variant == 'base_ex':
        t = it['ex_sentence'].strip() + sep + it['base_first'].strip() + sep + q
    else:
        t = it['base_second'].strip() + sep + it['sem_sentence'].strip() + sep + q
    return t


def rename(t, variant):
    """Rename {M} {S} {T} {D} to {A} {B} {C} in order of appearance -> (text, {letter: writer slot})."""
    role_of_d = 'Dx' if variant == 'base_ex' else 'Ds'
    toks = [(m.start(), m.group(1)) for m in C.PH.finditer(t)]
    mp, out, last = {}, [], 0
    for n, (pos, s) in enumerate(toks):
        L = LETTERS[n]
        mp[L] = role_of_d if s == 'D' else s
        out.append(t[last:pos]); out.append('{%s}' % L); last = pos + len(s) + 2
    out.append(t[last:])
    return ''.join(out), mp


def build_blind(v, root, manifest, base_sample=1.0):
    """(blind dict, key dict) for verifier unit record v, from its accepted writer units."""
    stamps = V.latest_stamps(os.path.join(root, 'accept'))
    units = {u['uid']: u for u in manifest['writer_units']}
    texts, langs = [], {}
    for d in v['deps']:
        st = stamps.get(d)
        if not st or st.get('status') != 'accepted':
            raise ValueError('writer unit %s is not accepted' % d)
        doc = C.load_json(os.path.join(root, st['file']))
        lang = doc['language_code']
        sep = '' if lang in C.NOSPACE else ' '
        langs[lang] = dict(language=doc['language'], cue=doc['lead_in'])
        for it in doc['items']:
            r = C.seeded('basesample', v['uid'], it['id'])
            take_base = base_sample >= 1.0 or r.random() < base_sample
            for var in VARIANTS:
                if var.startswith('base') and not take_base:
                    continue
                txt, mp = rename(compose(it, var, sep), var)
                texts.append((hashlib.md5(('%s|%s|%s|%s' % (SEED, v['uid'], it['id'], var)).encode()).hexdigest(),
                              lang, txt, dict(template=it['id'], writer_unit=d, lang=lang, variant=var, op=it['op'],
                                              shape=it['shape'], signed=bool(it['signed']), div_mode=it['div_mode'],
                                              slots=mp, base_sampled=take_base)))
    texts.sort()
    items, key = [], {}
    for n, (_, lang, txt, k) in enumerate(texts):
        bid = '%s-t%03d' % (v['uid'], n + 1)
        items.append(dict(id=bid, lang=lang, text=txt))
        key[bid] = k
    return dict(verifier_unit=v['uid'], languages=langs, items=items), key


def write_one(v, root, manifest, base_sample=1.0):
    b, k = build_blind(v, root, manifest, base_sample)
    bp, kp = os.path.join(root, v['blind']), os.path.join(root, v['key'])
    new_b = json.dumps(b, ensure_ascii=False, indent=1) + '\n'
    new_k = json.dumps(k, ensure_ascii=False, indent=1) + '\n'
    for p, txt in ((bp, new_b), (kp, new_k)):
        if os.path.exists(p):
            with open(p, encoding='utf-8') as fh:
                if fh.read() != txt:
                    raise ValueError('%s exists and differs; never overwritten' % p)
        else:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w', encoding='utf-8') as fh:
                fh.write(txt)
    return len(b['items'])


def fake_tree():
    """A temp tree with two ACCEPTED planted English units and a one-unit manifest (selftests of this file and check_v5)."""
    import status_v5 as S
    root = C.selftest_dir()
    fm = S.build_manifest(langs=('en',), groups=(('en',),), max_units=2, lead_in={'en': 'The answer is'})
    for u in fm['writer_units']:
        u['topics'] = list(C.PLANT_TOPICS); u['slice'] = 'SELFTEST'
        u['t_first_position'] = C.fixture_positions(C.planted_unit(u['unit'])[0])
    fm['verifier_units'] = [dict(fm['verifier_units'][0], deps=['W5-en-u01', 'W5-en-u02'])]
    for k in (1, 2):
        d, _ = C.planted_unit(k)
        C.dump_json(os.path.join(root, 'writers/en/W5-en-u%02d.json' % k), d)
    S.accept(root, fm, clock=lambda: 'selftest')
    return root, fm


def selftest():
    ok = True

    def chk(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print('  %s  %s' % ('ok  ' if cond else 'FAIL', name))

    root, fm = fake_tree()
    v = fm['verifier_units'][0]
    b, k = build_blind(v, root, fm)
    chk('96 texts (2 units x 12 templates x 4), unique opaque ids', len(b['items']) == 96 == len(k) and
        len(set(i['id'] for i in b['items'])) == 96)
    chk('no label leaks: item keys id/lang/text only', all(set(i) == {'id', 'lang', 'text'} for i in b['items']))
    chk('slots renamed: every text has exactly {A} {B} {C} and no writer slot name',
        all(sorted(C.placeholders(i['text'])) == ['A', 'B', 'C'] for i in b['items']))
    chk('slot maps cover M and S on every text', all({'M', 'S'} <= set(x['slots'].values()) for x in k.values()))
    vs = [k[i['id']]['variant'] for i in b['items'][:16]]
    ops = [k[i['id']]['op'] for i in b['items'][:16]]
    chk('variants and ops interleaved in the first 16 texts', len(set(vs)) >= 3 and len(set(ops)) >= 3)
    chk('deterministic', build_blind(v, root, fm) == (b, k))
    n = write_one(v, root, fm)
    chk('write_one writes 96 and a re-run is a no-op', n == 96 and write_one(v, root, fm) == 96)
    with open(os.path.join(root, v['blind']), 'a') as fh:
        fh.write(' ')
    try:
        write_one(v, root, fm); refused = False
    except ValueError:
        refused = True
    chk('an existing, different blind file is refused, never overwritten', refused)
    b2, k2 = build_blind(v, root, fm, base_sample=0.25)
    nb = sum(1 for x in k2.values() if x['variant'].startswith('base'))
    chk('base sampling 0.25 keeps %d of 48 base texts and all 48 order texts' % nb,
        0 < nb < 48 and sum(1 for x in k2.values() if not x['variant'].startswith('base')) == 48)
    t, mp = rename('X {D} y {M} z {S}.', 'base_ex')
    chk('rename maps {D} of base_ex to Dx', t == 'X {A} y {B} z {C}.' and mp == {'A': 'Dx', 'B': 'M', 'C': 'S'})
    fm2 = json.loads(json.dumps(fm))
    fm2['verifier_units'][0]['deps'] = ['W5-en-u01', 'W5-en-u02', 'W5-en-u09']
    try:
        build_blind(fm2['verifier_units'][0], root, fm2); blocked = False
    except ValueError:
        blocked = True
    chk('a verifier unit with a non-accepted writer unit is refused', blocked)
    shutil.rmtree(root)
    C.selftest_cleanup()
    print('SELFTEST make_blind_v5: %s' % ('0 fail' if ok else 'FAIL'))
    return ok


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('units', nargs='*')
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--ready', action='store_true')
    ap.add_argument('--tier', default=None, choices=list(C.TIERS))
    ap.add_argument('--base-sample', type=float, default=1.0)
    a = ap.parse_args(argv[1:])
    if a.selftest:
        return 0 if selftest() else 1
    m = C.load_json(os.path.join(HERE, 'manifest_v5.json'))
    vus = {v['uid']: v for v in m['verifier_units']}
    todo = list(a.units)
    if a.ready:
        import status_v5 as S
        _, vu, _, vs = S.all_states(HERE, m, a.tier)
        todo += [v['uid'] for v in vu if vs[v['uid']][0] == 'ready']
    rc = 0
    for uid in todo:
        try:
            n = write_one(vus[uid], HERE, m, a.base_sample)
            print('BLIND ok %d texts -> %s' % (n, vus[uid]['blind']))
        except (ValueError, KeyError) as e:
            print('BLIND REFUSED %s: %s' % (uid, e)); rc = 1
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv))
