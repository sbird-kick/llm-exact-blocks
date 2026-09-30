#!/usr/bin/env python3
"""status_v5.py -- the work manifest and the resumable, quota-window-friendly state of BANK v5 (stdlib only).

    python3 status_v5.py --write-manifest            # manifest_v5.json: every writer and verifier unit, stable ids
    python3 status_v5.py [--tier T2]                 # per-unit state from the files on disk; totals per language / tier
    python3 status_v5.py --next 20 [--kind writer|verifier] [--tier T2]   # the next N units to run (deterministic)
    python3 status_v5.py --accept [--tier T2]        # judge validated writer units against everything accepted so far
    python3 status_v5.py --selftest                  # manifest / status / next / accept on a fake tree

UNITS (the workflows run in chunks across quota resets):
  writer unit   W5-<lang>-uNN = (language, unit NN, one half-slice of 3 scenario topics, the 12-template quota:
                1 per op x shape). Writes ONLY writers/<lang>/W5-<lang>-uNN.json (attempt 0) or .rK.json (attempt K).
  verifier unit V5-gG-uNN = (verifier group G of 5 languages, unit NN): the 5 writer units W5-<each lang>-uNN, 240
                shuffled blind texts. Blind files blind/<id>.blind.json (+ blind_key/, never read by verifiers), output
                verify/<id>.json (or .rK.json).
NOTHING IS EVER OVERWRITTEN OR APPENDED: every attempt is its own file, every acceptance judgement its own stamp
(accept/<uid>.a<K>.json). State is recomputed from the files alone:
  writer    pending (no file) | invalid (latest attempt fails validate_v5) | valid (awaiting --accept) |
            rejected (near-duplicate of an accepted unit; re-queued as attempt K+1 with the duplicated ids) | accepted
  verifier  blocked (a writer unit it needs is not accepted) | ready (make the blind file) | blinded (run the
            verifier) | invalid (the verify file fails check_v5 --format) | done
--next prints, for a writer unit, the whole writer-facing SPEC (topics, lead_in, t_first_position, output path,
attempt, templates to rewrite): the orchestrator pastes it into the writer's prompt, so no writer opens the manifest.
--next walks the units in manifest order, which is unit number first and language (or group) second, so a partial run
is balanced across languages; it prints writer units in state pending / invalid / rejected and verifier units in
state ready / blinded / invalid.
--accept processes valid writer units in manifest order; each is compared (char-4-gram Jaccard >= 0.45, the
validate_v5 rule) with every template of its language already accepted, INCLUDING units accepted earlier in the same
pass, and gets an accepted or rejected stamp.
"""
import sys
sys.dont_write_bytecode = True   # no __pycache__: write nothing beyond the files the brief names
import argparse
import collections
import glob
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import v5_common as C  # noqa: E402
import validate_v5 as V  # noqa: E402

# cost anchors (ledger lines; see DESIGN_v5.md section 6)
WRITER_UNIT_TOKENS = (90000, 125000)    # DIVMOD step-1 writer: 1,873,842 tokens / 20 writers = 93,692 for 90 texts
VERIFIER_UNIT_TOKENS = (101000, 182000)  # DIVMOD Opus: 210-253 tokens/text, x2-3 for 3-5-numeral stories, x240 texts
TEXTS_PER_TEMPLATE = 4


# ------------------------------------------------------------------ manifest
def build_manifest(langs=C.LANGS, groups=C.GROUPS, max_units=C.MAX_UNITS, lead_in=None):
    lead_in = lead_in or {l: C.verified_lead_in(l) for l in langs}
    wu = []
    for k in range(1, max_units + 1):
        for lang in langs:
            sid, title, h, topics = C.unit_assignment(lang, k) if lang in C.LANGS else ('SELFTEST', 'selftest', 0, list(C.PLANT_TOPICS))
            uid = C.writer_uid(lang, k)
            wu.append(dict(uid=uid, lang=lang, unit=k, tier=C.unit_tier(k), slice=sid, slice_title=title, half=h,
                           topics=topics, lead_in=lead_in[lang], t_first_position=C.t_first_positions(lang, k),
                           out_dir='writers/%s' % lang,
                           first_file='writers/%s/%s.json' % (lang, uid), templates=C.UNIT_TEMPLATES,
                           est_tokens_sonnet=list(WRITER_UNIT_TOKENS)))
    vu = []
    for k in range(1, max_units + 1):
        for g, langs_g in enumerate(groups):
            uid = C.verifier_uid(g, k)
            vu.append(dict(uid=uid, group=g + 1, unit=k, tier=C.unit_tier(k), languages=list(langs_g),
                           deps=[C.writer_uid(l, k) for l in langs_g], blind='blind/%s.blind.json' % uid,
                           key='blind_key/%s.key.json' % uid, out='verify/%s.json' % uid,
                           texts=C.UNIT_TEMPLATES * TEXTS_PER_TEMPLATE * len(langs_g),
                           est_tokens_opus=list(VERIFIER_UNIT_TOKENS)))
    quota = dict(templates=C.UNIT_TEMPLATES, per_op_shape=C.Q_CELL, sub_signed_min=C.Q_SUB_SIGNED_MIN,
                 t_position_each=[C.Q_POS_MIN, C.Q_POS_MAX], split_min=C.Q_SPLIT_MIN, kinds_min=C.Q_KINDS_MIN,
                 verb_max=C.Q_VERB_MAX, numdep_max=C.Q_NUMDEP_MAX, topic_uses=[C.Q_TOPIC_MIN, C.Q_TOPIC_MAX],
                 near_dup=C.NEAR_DUP)
    return dict(bank='v5', note='Every unit of BANK v5 work, listed up front (status_v5.py --write-manifest). '
                                'Order = unit number first, language / group second (the --next order).',
                tiers={t: dict(units_per_language=n, templates=n * C.UNIT_TEMPLATES * len(langs),
                               rows=n * C.UNIT_TEMPLATES * len(langs) * C.ROWS_PER_TEMPLATE,
                               writer_units=n * len(langs), verifier_units=n * len(groups)) for t, n in C.TIERS.items()},
                quota=quota, writer_units=wu, verifier_units=vu)


def write_manifest(path):
    m = build_manifest()
    missing = [u['lang'] for u in m['writer_units'] if not u['lead_in']]
    if missing:
        print('REFUSED: no verified lead_in for %s' % sorted(set(missing)))
        return 1
    txt = json.dumps(m, ensure_ascii=False, indent=1) + '\n'
    if os.path.exists(path):
        with open(path, encoding='utf-8') as fh:
            if fh.read() == txt:
                print('manifest unchanged: %s (md5 %s)' % (path, C.md5_file(path)))
                return 0
        print('REFUSED: %s exists and differs; it is never overwritten (move it aside by hand if the design changed)' % path)
        return 1
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(txt)
    print('wrote %s: %d writer units, %d verifier units (md5 %s)' % (path, len(m['writer_units']), len(m['verifier_units']),
                                                                     C.md5_file(path)))
    return 0


# ------------------------------------------------------------------ state from disk
def attempts(root, lang, uid):
    """{K: path} of the writer attempts on disk."""
    out = {}
    for p in glob.glob(os.path.join(root, 'writers', lang, uid + '*.json')):
        b = os.path.basename(p)[:-5]
        if b == uid:
            out[0] = p
        elif b.startswith(uid + '.r') and b[len(uid) + 2:].isdigit():
            out[int(b[len(uid) + 2:])] = p
    return out


def verify_attempts(root, uid):
    out = {}
    for p in glob.glob(os.path.join(root, 'verify', uid + '*.json')):
        b = os.path.basename(p)[:-5]
        if b == uid:
            out[0] = p
        elif b.startswith(uid + '.r') and b[len(uid) + 2:].isdigit():
            out[int(b[len(uid) + 2:])] = p
    return out


def writer_state(root, u, manifest, cache=None):
    """(state, info) for one writer unit."""
    att = attempts(root, u['lang'], u['uid'])
    if not att:
        return 'pending', dict(next_attempt=0, out=os.path.join('writers', u['lang'], u['uid'] + '.json'))
    k = max(att)
    stamp = os.path.join(root, 'accept', '%s.a%d.json' % (u['uid'], k))
    nxt = os.path.join('writers', u['lang'], '%s.r%d.json' % (u['uid'], k + 1))
    rel = os.path.relpath(att[k], root)
    if os.path.exists(stamp):
        st = C.load_json(stamp)
        if st['status'] == 'accepted':
            return 'accepted', dict(attempt=k, file=rel)
        return 'rejected', dict(attempt=k, file=rel, next_attempt=k + 1, out=nxt, duplicates=st.get('duplicates', []))
    try:
        doc = C.load_json(att[k])
        fails = V.validate_unit(doc, u, None, C.prior_corpus(u['lang'], include_examples=(u['slice'] != 'SELFTEST')), att[k])
    except (ValueError, OSError) as e:
        fails = ['FAIL file [json] %s' % e]
    if fails:
        return 'invalid', dict(attempt=k, file=rel, next_attempt=k + 1, out=nxt, fails=len(fails), first_fail=fails[0])
    return 'valid', dict(attempt=k, file=rel)


def verifier_state(root, v, wstates):
    if any(wstates.get(d, ('pending',))[0] != 'accepted' for d in v['deps']):
        return 'blocked', dict(waiting=[d for d in v['deps'] if wstates.get(d, ('pending',))[0] != 'accepted'])
    if not os.path.exists(os.path.join(root, v['blind'])):
        return 'ready', {}
    att = verify_attempts(root, v['uid'])
    if not att:
        return 'blinded', dict(out=v['out'])
    k = max(att)
    import check_v5 as CK
    try:
        fails = CK.fmt_fails(C.load_json(os.path.join(root, v['blind'])), C.load_json(att[k]))
    except ValueError as e:
        fails = [str(e)]
    if fails:
        return 'invalid', dict(attempt=k, next_out='verify/%s.r%d.json' % (v['uid'], k + 1), fails=len(fails))
    return 'done', dict(attempt=k, file=os.path.relpath(att[k], root))


def all_states(root, manifest, tier=None):
    wu = [u for u in manifest['writer_units'] if not tier or C.TIERS[tier] >= u['unit']]
    vu = [v for v in manifest['verifier_units'] if not tier or C.TIERS[tier] >= v['unit']]
    ws = {u['uid']: writer_state(root, u, manifest) for u in wu}
    vs = {v['uid']: verifier_state(root, v, ws) for v in vu}
    return wu, vu, ws, vs


def writer_spec(u, info):
    """Everything a writer needs about its unit, so no writer ever opens the 0.7 MB manifest."""
    spec = dict(unit_id=u['uid'], language=C.LANG_NAMES.get(u['lang'], u['lang']), language_code=u['lang'],
                unit=u['unit'], slice=u['slice'], slice_title=u['slice_title'], topics=u['topics'],
                lead_in=u['lead_in'], t_first_position=u['t_first_position'],
                output_path=os.path.join(HERE, info.get('out', u['first_file'])), attempt=info.get('next_attempt', 0))
    if info.get('attempt') is not None and info.get('next_attempt'):
        spec['previous_attempt'] = os.path.join(HERE, info['file'])
        spec['rewrite_templates'] = sorted(set(d['template'] for d in info.get('duplicates', []))) or 'all flagged by the validator'
        if info.get('duplicates'):
            spec['duplicates_of_accepted'] = info['duplicates']
    return spec


def next_units(root, manifest, n, kind='writer', tier=None):
    wu, vu, ws, vs = all_states(root, manifest, tier)
    out = []
    if kind == 'writer':
        for u in wu:
            s, info = ws[u['uid']]
            if s in ('pending', 'invalid', 'rejected'):
                out.append((u['uid'], s, dict(info, spec=writer_spec(u, info))))
    else:
        for v in vu:
            s, info = vs[v['uid']]
            if s in ('ready', 'blinded', 'invalid'):
                out.append((v['uid'], s, info))
    return out[:n]


def accept(root, manifest, tier=None, clock=None):
    """Judge every 'valid' writer unit in manifest order; one new stamp per judged attempt."""
    wu, _, ws, _ = all_states(root, manifest, tier)
    done = []
    for u in wu:
        s, info = ws[u['uid']]
        if s != 'valid':
            continue
        path = os.path.join(root, info['file'])
        doc = C.load_json(path)
        acc = V.accepted_items(u['lang'], exclude_uid=u['uid'], accept_dir=os.path.join(root, 'accept'), root=root)
        dups = []
        for it in doc['items']:
            sh = C.shingles(C.dup_text(it))
            for tid, ait in acc:
                j = C.jaccard(sh, C.shingles(C.dup_text(ait)))
                if j >= C.NEAR_DUP:
                    dups.append(dict(template=it['id'], accepted_template=tid, jaccard=round(j, 3)))
        stamp = dict(uid=u['uid'], lang=u['lang'], attempt=info['attempt'], file=info['file'], md5=C.md5_file(path),
                     status='rejected' if dups else 'accepted', duplicates=dups,
                     checked_against=sorted(set(t.rsplit('-', 1)[0] for t, _ in acc)),
                     stamped_at=(clock or (lambda: time.strftime('%Y-%m-%d %H:%M:%S %Z')))())
        sp = os.path.join(root, 'accept', '%s.a%d.json' % (u['uid'], info['attempt']))
        if os.path.exists(sp):
            continue                                        # never overwritten
        C.dump_json(sp, stamp)
        done.append((u['uid'], stamp['status'], len(dups)))
    return done


def report(root, manifest, tier=None):
    wu, vu, ws, vs = all_states(root, manifest, tier)
    bylang = collections.defaultdict(collections.Counter)
    for u in wu:
        bylang[u['lang']][ws[u['uid']][0]] += 1
    tot = collections.Counter(s for s, _ in ws.values())
    print('WRITER UNITS%s: %d  %s' % (' (%s)' % tier if tier else '', len(wu), dict(tot)))
    for lang in sorted(bylang, key=lambda l: C.LANGS.index(l) if l in C.LANGS else 99):
        c = bylang[lang]
        print('  %-3s accepted %2d  valid %2d  rejected %2d  invalid %2d  pending %2d  (of %d)' % (
            lang, c['accepted'], c['valid'], c['rejected'], c['invalid'], c['pending'], sum(c.values())))
    top = max((u['unit'] for u in wu), default=0)
    for t, n in C.TIERS.items():
        us = [u for u in wu if u['unit'] <= n]
        if us and n <= max(top, C.TIERS['T1']):
            acc = sum(1 for u in us if ws[u['uid']][0] == 'accepted')
            print('  tier %s: accepted %d/%d writer units (%d/%d templates)' % (t, acc, len(us), acc * C.UNIT_TEMPLATES,
                                                                               len(us) * C.UNIT_TEMPLATES))
    vt = collections.Counter(s for s, _ in vs.values())
    print('VERIFIER UNITS: %d  %s' % (len(vu), dict(vt)))
    return ws, vs


# ------------------------------------------------------------------ selftest
def selftest():
    import copy
    import io
    import contextlib
    ok = True

    def chk(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print('  %s  %s' % ('ok  ' if cond else 'FAIL', name))

    # (a) the real manifest is deterministic, complete and balanced (built in memory, not written)
    m = build_manifest()
    m2 = build_manifest()
    chk('real manifest deterministic', json.dumps(m) == json.dumps(m2))
    chk('real manifest: 25 x 32 writer units, 5 x 32 verifier units', len(m['writer_units']) == 800 and len(m['verifier_units']) == 160)
    per = collections.defaultdict(set)
    for u in m['writer_units']:
        per[u['lang']].add((u['slice'], u['half']))
    chk('within every language the 32 units take 32 distinct half-slices', all(len(s) == 32 for s in per.values()))
    uses = collections.Counter((u['slice'], u['half']) for u in m['writer_units'] if u['tier'] == 'T1')
    chk('T1 spreads over the 48 half-slices (min %d, max %d uses)' % (min(uses.values()), max(uses.values())),
        len(uses) == 48 and max(uses.values()) - min(uses.values()) <= 2)
    chk('every verifier unit depends on 5 writer units of its group at the same unit number',
        all(len(v['deps']) == 5 and all(d.endswith('-u%02d' % v['unit']) for d in v['deps']) for v in m['verifier_units']))
    chk('every language has a verified lead_in', all(u['lead_in'] for u in m['writer_units']))
    cellpos = collections.Counter((c, p) for u in m['writer_units'] if u['tier'] == 'T2' or u['tier'] == 'T1'
                                  for c, p in u['t_first_position'].items())
    chk('T2: every (op/shape, position) cell gets %d-%d units' % (min(cellpos.values()), max(cellpos.values())),
        len(cellpos) == 36 and max(cellpos.values()) - min(cellpos.values()) <= 2)
    chk('each unit asks for every position exactly 4 times', all(sorted(collections.Counter(u['t_first_position'].values()).values())
                                                               == [4, 4, 4] for u in m['writer_units']))
    # (b) a fake tree
    root = C.selftest_dir()
    fm = build_manifest(langs=('en',), groups=(('en',),), max_units=4, lead_in={'en': 'The answer is'})
    d1, _ = C.planted_unit(1); d2, _ = C.planted_unit(2)
    for u in fm['writer_units']:
        u['topics'] = list(C.PLANT_TOPICS); u['slice'] = 'SELFTEST'
        u['t_first_position'] = C.fixture_positions(d1 if u['unit'] % 2 else d2)
    fm['verifier_units'] = [dict(fm['verifier_units'][0], deps=['W5-en-u01', 'W5-en-u02'])]
    C.dump_json(os.path.join(root, 'writers/en/W5-en-u01.json'), d1)
    C.dump_json(os.path.join(root, 'writers/en/W5-en-u02.json'), d2)
    d3 = copy.deepcopy(d1); d3['writer_unit'] = 'W5-en-u03'; d3['unit'] = 3
    for j, it in enumerate(d3['items']):
        it['id'] = 'W5-en-u03-%02d' % (j + 1)
    C.dump_json(os.path.join(root, 'writers/en/W5-en-u03.json'), d3)
    _, _, ws, vs = all_states(root, fm)
    chk('states before acceptance: u01..u03 valid, u04 pending', [ws['W5-en-u0%d' % k][0] for k in (1, 2, 3, 4)] ==
        ['valid', 'valid', 'valid', 'pending'])
    chk('verifier unit blocked before acceptance', vs['V5-g1-u01'][0] == 'blocked')
    n1 = next_units(root, fm, 10)
    chk('--next before acceptance = [u04]', [x[0] for x in n1] == ['W5-en-u04'])
    fixed = lambda: '2026-09-29 00:00:00 EDT'
    res = accept(root, fm, clock=fixed)
    chk('accept: u01, u02 accepted; u03 rejected with 12 duplicates %s' % res,
        res == [('W5-en-u01', 'accepted', 0), ('W5-en-u02', 'accepted', 0), ('W5-en-u03', 'rejected', 12)])
    before = sorted(os.listdir(os.path.join(root, 'accept')))
    res2 = accept(root, fm, clock=fixed)
    chk('a second --accept writes nothing and changes no stamp', res2 == [] and sorted(os.listdir(os.path.join(root, 'accept'))) == before)
    n2 = next_units(root, fm, 10)
    chk('--next after acceptance = [u03 (rejected, attempt 1, duplicates listed), u04]',
        [(x[0], x[1]) for x in n2] == [('W5-en-u03', 'rejected'), ('W5-en-u04', 'pending')] and
        n2[0][2]['next_attempt'] == 1 and len(n2[0][2]['duplicates']) == 12 and n2[0][2]['out'].endswith('W5-en-u03.r1.json'))
    sp = n2[0][2]['spec']
    chk('--next carries the writer spec (topics, lead_in, positions, output path, attempt, templates to rewrite)',
        sp['attempt'] == 1 and sp['output_path'].endswith('writers/en/W5-en-u03.r1.json') and len(sp['rewrite_templates']) == 12
        and sp['lead_in'] == 'The answer is' and len(sp['t_first_position']) == 12 and sp['topics'] == list(C.PLANT_TOPICS))
    chk('--next is deterministic', next_units(root, fm, 10) == n2)
    _, _, ws, vs = all_states(root, fm)
    chk('verifier unit ready once its writer units are accepted', vs['V5-g1-u01'][0] == 'ready')
    bad = copy.deepcopy(d2); bad['writer_unit'] = 'W5-en-u04'; bad['unit'] = 4; bad['items'] = bad['items'][:11]
    C.dump_json(os.path.join(root, 'writers/en/W5-en-u04.json'), bad)
    s, info = writer_state(root, fm['writer_units'][3], fm)
    chk('an invalid attempt 0 is re-queued as attempt 1 (%s)' % s, s == 'invalid' and info['next_attempt'] == 1)
    # attempt 1 of u03, still the content of u01 (valid on its own, a duplicate of an accepted unit) -> rejected again
    r1 = copy.deepcopy(d1); r1['writer_unit'] = 'W5-en-u03'; r1['unit'] = 3; r1['attempt'] = 1
    for j, it in enumerate(r1['items']):
        it['id'] = 'W5-en-u03-%02d' % (j + 1)
    C.dump_json(os.path.join(root, 'writers/en/W5-en-u03.r1.json'), r1)
    res3 = accept(root, fm, clock=fixed)
    chk('attempt 1 judged on its own stamp (a1), still a duplicate -> rejected', res3 == [('W5-en-u03', 'rejected', 12)]
        and os.path.exists(os.path.join(root, 'accept/W5-en-u03.a0.json')) and os.path.exists(os.path.join(root, 'accept/W5-en-u03.a1.json')))
    # round robin over languages on pending units
    fm2 = build_manifest(langs=('en', 'de'), groups=(('en', 'de'),), max_units=3, lead_in={'en': 'x', 'de': 'y'})
    root2 = C.selftest_dir()
    chk('--next round-robins languages: en-u01, de-u01, en-u02, de-u02',
        [x[0] for x in next_units(root2, fm2, 4)] == ['W5-en-u01', 'W5-de-u01', 'W5-en-u02', 'W5-de-u02'])
    chk('--tier limits the units', len(next_units(root2, fm2, 99, tier='T1')) == 6)
    with contextlib.redirect_stdout(io.StringIO()):
        report(root, fm)
    shutil.rmtree(root); shutil.rmtree(root2)
    C.selftest_cleanup()
    print('SELFTEST status_v5: %s' % ('0 fail' if ok else 'FAIL'))
    return ok


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--write-manifest', action='store_true')
    ap.add_argument('--next', type=int, default=0)
    ap.add_argument('--kind', default='writer', choices=['writer', 'verifier'])
    ap.add_argument('--tier', default=None, choices=list(C.TIERS))
    ap.add_argument('--accept', action='store_true')
    ap.add_argument('--root', default=HERE)
    a = ap.parse_args(argv[1:])
    if a.selftest:
        return 0 if selftest() else 1
    mp = os.path.join(a.root, 'manifest_v5.json')
    if a.write_manifest:
        return write_manifest(mp)
    if not os.path.exists(mp):
        print('no manifest_v5.json; run --write-manifest first')
        return 1
    m = C.load_json(mp)
    if a.accept:
        for uid, s, nd in accept(a.root, m, a.tier):
            print('%s %s%s' % (uid, s, (' (%d duplicated templates)' % nd) if nd else ''))
        return 0
    if a.next:
        for uid, s, info in next_units(a.root, m, a.next, a.kind, a.tier):
            print('%s  %-8s %s' % (uid, s, json.dumps(info.get('spec', info), ensure_ascii=False)))
        return 0
    report(a.root, m, a.tier)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
