#!/usr/bin/env python3
"""validate_v5.py -- the gate on BANK v5 writer units, on generated v5 rows, and the corpus-level reports (stdlib only).

    python3 validate_v5.py <writers/<lang>/W5-<lang>-uNN[.rK].json>   # WRITER MODE: prints 'VALIDATE ok 12' or FAIL lines
    python3 validate_v5.py --bank <signed_A_int.jsonl>                  # ROW MODE: one-pair-only, pairs, order labels ...
    python3 validate_v5.py --corpus                                     # cross-unit near-duplicates + diversity report
    python3 validate_v5.py --calibrate                                  # the near-duplicate threshold's evidence
    python3 validate_v5.py --selftest

WRITER MODE refuses everything BRIEF_v5_writer.md forbids (tags in brackets):
  [schema] [unit]     file keys, unit id / language / slice / topics / lead_in as in manifest_v5.json; 12 items with
                      exactly the item keys; ids <unit>-01..-12 in order
  [vocab]             op add/sub/mul/div, shape list/other_time/diff_owner, topic one of the unit's three,
                      t_mimics (add/sub: both; mul/div: M or S), signed only on sub, sign_convention iff signed,
                      div_mode iff div, numeral_grammar invariant/number_dependent, notes/agreement_note/gloss present
  [placeholder]       facts: exactly {M} {S} {T} once each; base: exactly {M} {S}; question: none; ex/sem: exactly {D}
  [order]             facts_first and base_first write {M} before {S}; facts_second and base_second write {S} first
  [swap]              the two orders must move the WORDS with the slots (equal skeletons = slots swapped = roles swapped)
  [adjacent]          a word between every two neighbouring slots
  [digit] [symbol] [numberword]   no numeral of any script, no arithmetic symbol, no listed number word, anywhere
                      (validate_single.py lists + English ordinals); [div] English division texts: no leftover /
                      remainder / needed / at least / between / about (the DIVMOD lessons)
  [question] [sentence] [length] [whitespace] [script]
  [base]              each base shares >= 0.25 char-4-gram Jaccard with its facts text (it is the same story minus {T})
  [duplicate]         identical skeletons across items; [neardup] char-4-gram Jaccard >= 0.45 between two items of
                      the unit; [novelty] >= 0.45 against the verified v2-v4 stories (and v4wild for en);
                      [neardup-accepted] >= 0.45 against any ALREADY ACCEPTED unit of the language (accept/ stamps)
  [position]          {T} written first / middle / last in facts_first exactly where the manifest's
                      t_first_position asks for that (op, shape) cell (rotated so the cells fill evenly)
  [quota]             exactly 1 per (op x shape); sub signed >= 2 of 3; div: both div_modes; mul and div: t_mimics M and
                      S each at least once; T written first / middle / last each 4..12 of the 24 facts texts and every
                      position at least once per shape; >= 6 templates with a sentence boundary between {M} and {S} in
                      both bases; >= 8 distinct quantity_kind; a verb at most twice; number_dependent at most 2;
                      each topic 3..6 times
ROW MODE (a generated bank; the one-pair-only rule is re-checked by arithmetic, not by reading):
  numerals = 2 + len(ds), operands once each, |answer| not written, ans = op(a, b), div exact, one-pair-only under
  ANY operator (host_attr_v5.gold_unique_anyop) and under the row's own op, minimal pairs complete and word-identical
  after swapping the operands back, order / size labels true, distractors distinct and substring-free.
"""
import sys
sys.dont_write_bytecode = True   # no __pycache__: write nothing beyond the files the brief names
import argparse
import collections
import glob
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import v5_common as C  # noqa: E402
import host_attr_v5 as H  # noqa: E402
VS = C.VS

MANIFEST = os.path.join(HERE, 'manifest_v5.json')
ACCEPT_DIR = os.path.join(HERE, 'accept')
WRITERS_DIR = os.path.join(HERE, 'writers')


# ------------------------------------------------------------------ manifest / accepted units
def load_manifest(path=MANIFEST):
    return C.load_json(path) if os.path.exists(path) else None


def unit_record(uid, manifest=None):
    m = manifest if manifest is not None else load_manifest()
    if not m:
        return None
    for u in m['writer_units']:
        if u['uid'] == uid:
            return u
    return None


def latest_stamps(accept_dir=ACCEPT_DIR, lang=None):
    """uid -> the acceptance stamp of its LATEST judged attempt (accept/<uid>.a<K>.json; one file per attempt, never
    overwritten)."""
    best = {}
    for p in glob.glob(os.path.join(accept_dir, 'W5-%s-u*.a*.json' % (lang or '*'))):
        b = os.path.basename(p)[:-5]
        uid, _, att = b.rpartition('.a')
        if not att.isdigit():
            continue
        if uid not in best or int(att) > best[uid][0]:
            best[uid] = (int(att), p)
    return {u: C.load_json(p) for u, (k, p) in best.items()}


def accepted_items(lang, exclude_uid=None, accept_dir=ACCEPT_DIR, root=HERE):
    """[(template id, item)] of every ACCEPTED unit of `lang` (latest stamp status 'accepted'), own files only."""
    out = []
    for uid, st in sorted(latest_stamps(accept_dir, lang).items()):
        if st.get('status') != 'accepted' or uid == exclude_uid:
            continue
        wp = os.path.join(root, st['file'])
        if not os.path.exists(wp):
            continue
        for it in C.load_json(wp).get('items', []):
            out.append((it.get('id'), it))
    return out


# ------------------------------------------------------------------ text checks
def text_problems(lang, key, t, item_op):
    """[(tag, msg)] for one text string of a template."""
    p = []
    if not isinstance(t, str) or not t.strip():
        return [('schema', '%s must be a non-empty string' % key)]
    if t != t.strip() or any(c in t for c in '\n\r\t'):
        p.append(('whitespace', '%s: outer whitespace or a newline/tab' % key))
    lo, hi = (20, 500) if key.startswith(('facts', 'base')) else (8, 300)
    if not lo <= len(t) <= hi:
        p.append(('length', '%s: length %d outside %d..%d' % (key, len(t), lo, hi)))
    ph = C.placeholders(t)
    want = {'facts_first': ['M', 'S', 'T'], 'facts_second': ['M', 'S', 'T'], 'base_first': ['M', 'S'],
            'base_second': ['M', 'S'], 'question': [], 'ex_sentence': ['D'], 'sem_sentence': ['D']}[key]
    if sorted(ph) != want:
        p.append(('placeholder', '%s: placeholders %s, need exactly %s once each' % (key, ph, want or 'none')))
    rest = C.PH.sub('', t)
    if any(c in rest for c in '{}｛｝'):
        p.append(('placeholder', '%s: braces other than the placeholders' % key))
    if sorted(ph) == want and key in ('facts_first', 'facts_second', 'base_first', 'base_second'):
        order = C.slot_order(t)
        m_first = order.index('M') < order.index('S')
        if m_first != key.endswith('first'):
            p.append(('order', '%s: {M} must be written %s {S}' % (key, 'before' if key.endswith('first') else 'after')))
        for a_, b_ in zip(order, order[1:]):
            between = t[t.index('{%s}' % a_) + 3:t.index('{%s}' % b_)]
            if not any(VS.unicodedata.category(c)[0] == 'L' for c in between):
                p.append(('adjacent', '%s: no word between {%s} and {%s}' % (key, a_, b_)))
    plain = C.strip_ph(t)
    d = VS.digit_chars(plain)
    if d:
        p.append(('digit', '%s: digit characters %r' % (key, ''.join(sorted(set(d))))))
    sym = sorted(set(c for c in plain if c in C.ARITH))
    if sym:
        p.append(('symbol', '%s: arithmetic symbols %r' % (key, ''.join(sym))))
    if re.search(r'\{[A-Z]\}\s*-\s*\{[A-Z]\}|\s-\s*\{[A-Z]\}|\{[A-Z]\}\s*-\s', t):
        p.append(('symbol', '%s: a minus sign next to a placeholder' % key))
    nw = VS.number_words_in(lang, plain)
    if lang == 'en':
        low = plain.casefold()
        nw += [w for w in C.EN_EXTRA_NUMBER_WORDS if re.search(r"(?<![\w'’])%s(?![\w'’])" % re.escape(w), low)]
        if item_op == 'div' and key != 'ex_sentence' and key != 'sem_sentence':
            bad = [w for w in C.EN_DIV_BANNED if re.search(r"(?<![\w'’])%s" % re.escape(w), low)]
            if bad:
                p.append(('div', '%s: division words that imply a leftover / rounding / an unmarked dividend: %s'
                          % (key, ', '.join(bad))))
    if nw:
        p.append(('numberword', '%s: number words give hidden operands: %s' % (key, ', '.join(sorted(set(nw))))))
    end = t.rstrip().rstrip(C.TRAIL).rstrip()
    if key == 'question' and lang != 'th' and (not end or end[-1] not in C.QMARKS):
        p.append(('question', 'question must end with a question mark'))
    if key in ('ex_sentence', 'sem_sentence', 'facts_first', 'facts_second', 'base_first', 'base_second') and lang != 'th':
        if not end or not (C.SENT_END.match(end[-1]) or end[-1] in C.QMARKS):
            p.append(('sentence', '%s must end with sentence-final punctuation' % key))
    sp = VS.script_problem(lang, plain)
    if sp:
        p.append(('script', '%s: %s' % (key, sp)))
    return p


def t_position(t):
    """Written position of {T} among the three facts slots: 0 first, 1 middle, 2 last (None if malformed)."""
    o = C.slot_order(t)
    return o.index('T') if sorted(o) == ['M', 'S', 'T'] else None


# ------------------------------------------------------------------ writer-unit validation
def validate_unit(doc, unit, accepted=None, prior=None, path=None):
    """FAIL lines for one writer unit. `unit` = its manifest record; `accepted` = [(tid, item)] of accepted units of
    the same language; `prior` = [(source, text)] of the prior corpora."""
    fails = []

    def F(where, tag, msg):
        fails.append('FAIL %s [%s] %s' % (where, tag, msg))

    if not isinstance(doc, dict):
        F('file', 'schema', 'top level must be an object')
        return fails
    if set(doc) != set(C.FILE_KEYS):
        F('file', 'schema', 'top-level keys must be exactly %s; missing %s, unknown %s' % (
            list(C.FILE_KEYS), sorted(set(C.FILE_KEYS) - set(doc)), sorted(set(doc) - set(C.FILE_KEYS))))
    lang = unit['lang']
    for k, want in (('writer_unit', unit['uid']), ('language_code', lang), ('unit', unit['unit']),
                    ('slice', unit['slice']), ('topics', unit['topics']), ('lead_in', unit['lead_in'])):
        if doc.get(k) != want:
            F('file', 'unit', '%s must be %r (manifest), got %r' % (k, want, doc.get(k)))
    if not isinstance(doc.get('attempt'), int) or doc.get('attempt') < 0:
        F('file', 'schema', 'attempt must be a whole number (0 for the first file, K for .rK)')
    if path:
        base = os.path.basename(path)
        want = unit['uid'] + ('.json' if not doc.get('attempt') else '.r%d.json' % doc.get('attempt'))
        if base != want:
            F('file', 'unit', 'file must be named %s (attempt %r)' % (want, doc.get('attempt')))
    items = doc.get('items')
    if not isinstance(items, list):
        F('file', 'schema', 'items must be a list')
        return fails
    if len(items) != C.UNIT_TEMPLATES:
        F('file', 'count', 'need exactly %d items, found %d' % (C.UNIT_TEMPLATES, len(items)))
    cells, pos_all, pos_shape = collections.Counter(), collections.Counter(), collections.defaultdict(collections.Counter)
    sub_signed = 0; div_modes = collections.Counter(); mim = collections.defaultdict(collections.Counter)
    kinds, verbs, topics = set(), collections.Counter(), collections.Counter()
    nsplit = numdep = 0
    alltexts, skel = [], collections.defaultdict(list)
    good = []
    for n, it in enumerate(items):
        w = it.get('id') if isinstance(it, dict) and it.get('id') else 'item#%d' % (n + 1)
        if not isinstance(it, dict):
            F(w, 'schema', 'item is not an object')
            continue
        if set(it) != set(C.ITEM_KEYS):
            F(w, 'schema', 'keys must be exactly the item keys; missing %s, unknown %s' % (
                sorted(set(C.ITEM_KEYS) - set(it)), sorted(set(it) - set(C.ITEM_KEYS))))
        if it.get('id') != '%s-%02d' % (unit['uid'], n + 1):
            F(w, 'schema', 'item %d must have id %s-%02d' % (n + 1, unit['uid'], n + 1))
        op, shape = it.get('op'), it.get('shape')
        if op not in C.OPS:
            F(w, 'vocab', 'op %r not one of %s' % (op, C.OPS)); op = None
        if shape not in C.SHAPES:
            F(w, 'vocab', 'shape %r not one of %s' % (shape, C.SHAPES)); shape = None
        if op and shape:
            cells[(op, shape)] += 1
        if it.get('topic') not in unit['topics']:
            F(w, 'vocab', 'topic %r is not one of the unit topics %s' % (it.get('topic'), unit['topics']))
        else:
            topics[it['topic']] += 1
        for k in ('quantity_kind', 'unit', 'verb', 'agreement_note', 'gloss_en', 'notes', 'sign_convention', 'div_mode'):
            if not isinstance(it.get(k), str):
                F(w, 'schema', '%s must be a string' % k)
        for k in ('quantity_kind', 'verb', 'agreement_note', 'gloss_en'):
            if isinstance(it.get(k), str) and not it[k].strip():
                F(w, 'schema', '%s must not be empty' % k)
        if isinstance(it.get('quantity_kind'), str):
            kinds.add(it['quantity_kind'].strip().casefold())
        if isinstance(it.get('verb'), str) and it['verb'].strip():
            verbs[it['verb'].strip().casefold()] += 1
        if isinstance(it.get('gloss_en'), str):
            if VS.digit_chars(C.strip_ph(it['gloss_en'])):
                F(w, 'digit', 'gloss_en has digit characters')
            if it['gloss_en'].strip() and VS.script_problem('en', C.strip_ph(it['gloss_en'])):
                F(w, 'script', 'gloss_en must be English')
        tm = it.get('t_mimics')
        if tm not in C.MIMICS:
            F(w, 'vocab', 't_mimics %r not one of %s' % (tm, C.MIMICS))
        elif op in ('add', 'sub') and tm != 'both':
            F(w, 'vocab', 'add/sub: {T} is the same kind as both operands, t_mimics must be "both"')
        elif op in ('mul', 'div') and tm == 'both':
            F(w, 'vocab', 'mul/div: t_mimics must say which operand {T} is the same kind as ("M" or "S")')
        elif op in ('mul', 'div'):
            mim[op][tm] += 1
        sg = it.get('signed')
        if not isinstance(sg, bool):
            F(w, 'vocab', 'signed must be true or false')
        elif sg and op != 'sub':
            F(w, 'vocab', 'signed may be true only on sub')
        elif sg:
            sub_signed += 1
        conv = it.get('sign_convention')
        if isinstance(conv, str) and bool(conv.strip()) != bool(sg is True):
            F(w, 'vocab', 'sign_convention must be filled exactly when signed is true')
        dm = it.get('div_mode')
        if op == 'div':
            if dm not in C.DIV_MODES:
                F(w, 'vocab', 'div_mode must be one of %s' % (C.DIV_MODES,))
            else:
                div_modes[dm] += 1
        elif dm not in ('', None):
            F(w, 'vocab', 'div_mode must be "" unless op is div')
        gr = it.get('numeral_grammar')
        if gr not in C.GRAMMAR:
            F(w, 'vocab', 'numeral_grammar must be one of %s' % (C.GRAMMAR,))
        elif gr == 'number_dependent':
            numdep += 1
        tp = collections.Counter()
        for key in C.TEXT_KEYS:
            t = it.get(key)
            for tag, msg in text_problems(lang, key, t, op):
                F(w, tag, msg)
            if isinstance(t, str):
                alltexts.append(t)
                skel[C.skeleton(t)].append((w, key))
        ff, fs, bf, bs = (it.get(k) or '' for k in ('facts_first', 'facts_second', 'base_first', 'base_second'))
        if ff and fs and C.skeleton(ff) == C.skeleton(fs):
            F(w, 'swap', 'facts_first and facts_second have the same words in the same places: the slots were swapped '
                         'instead of the phrases being reordered, which swaps the roles')
        if bf and bs and C.skeleton(bf) == C.skeleton(bs):
            F(w, 'swap', 'base_first and base_second have the same words in the same places (slots swapped)')
        for fk, bk in (('facts_first', 'base_first'), ('facts_second', 'base_second')):
            f_, b_ = it.get(fk), it.get(bk)
            if isinstance(f_, str) and isinstance(b_, str) and f_ and b_:
                s = C.jaccard(C.shingles(f_), C.shingles(b_))
                if s < C.BASE_MIN_SIM:
                    F(w, 'base', '%s shares only %.2f of its char-4-grams with %s (need >= %.2f): the base must be the '
                                 'same story with the {T} quantity left out' % (bk, s, fk, C.BASE_MIN_SIM))
        want_pos = (unit.get('t_first_position') or {}).get('%s/%s' % (op, shape))
        p0 = t_position(ff)
        if want_pos and p0 is not None and C.POSITIONS[p0] != want_pos:
            F(w, 'position', 'this unit asks for {T} written %s in facts_first for (%s, %s); it is written %s'
              % (want_pos, op, shape, C.POSITIONS[p0]))
        for fk in ('facts_first', 'facts_second'):
            p_ = t_position(it.get(fk) or '')
            if p_ is not None:
                pos_all[p_] += 1
                if shape:
                    pos_shape[shape][p_] += 1
        if bf and bs and C.split_points(bf) and C.split_points(bs):
            nsplit += 1
        good.append((w, it))
    # duplicates inside the unit
    for sk, wh in skel.items():
        if len(set(x for x, _ in wh)) > 1:
            F(','.join('%s.%s' % x for x in wh), 'duplicate', 'texts identical up to case, punctuation and slot names')
    sh = [(w, C.shingles(C.dup_text(it))) for w, it in good]
    for i in range(len(sh)):
        for j in range(i + 1, len(sh)):
            s = C.jaccard(sh[i][1], sh[j][1])
            if s >= C.NEAR_DUP:
                F('%s,%s' % (sh[i][0], sh[j][0]), 'neardup', 'char-4-gram Jaccard %.2f >= %.2f: the same frame twice' % (s, C.NEAR_DUP))
    for src, txt in (prior or []):
        ps = C.shingles(txt)
        for w, s_ in sh:
            s = C.jaccard(s_, ps)
            if s >= C.NEAR_DUP:
                F(w, 'novelty', 'char-4-gram Jaccard %.2f with existing template %s' % (s, src))
    for tid, ait in (accepted or []):
        ps = C.shingles(C.dup_text(ait))
        for w, s_ in sh:
            s = C.jaccard(s_, ps)
            if s >= C.NEAR_DUP:
                F(w, 'neardup-accepted', 'char-4-gram Jaccard %.2f with accepted template %s' % (s, tid))
    # quotas
    for op in C.OPS:
        for shape in C.SHAPES:
            if cells[(op, shape)] != C.Q_CELL:
                F('file', 'quota', '(%s, %s): need exactly %d template, found %d' % (op, shape, C.Q_CELL, cells[(op, shape)]))
    if sub_signed < C.Q_SUB_SIGNED_MIN:
        F('file', 'quota', 'sub: at least %d of 3 must be signed (negative answer natural), found %d' % (C.Q_SUB_SIGNED_MIN, sub_signed))
    for m in C.DIV_MODES:
        if div_modes[m] < 1:
            F('file', 'quota', 'div: need at least one div_mode %s' % m)
    for op in ('mul', 'div'):
        for m in ('M', 'S'):
            if mim[op][m] < 1:
                F('file', 'quota', '%s: need at least one template whose {T} mimics %s' % (op, m))
    names = ('first', 'middle', 'last')
    for p_ in range(3):
        if not C.Q_POS_MIN <= pos_all[p_] <= C.Q_POS_MAX:
            F('file', 'quota', '{T} written %s in %d of the 24 facts texts; need %d..%d' % (names[p_], pos_all[p_], C.Q_POS_MIN, C.Q_POS_MAX))
        for shape in C.SHAPES:
            if pos_shape[shape][p_] < 1:
                F('file', 'quota', 'shape %s: {T} is never written %s (each position at least once per shape)' % (shape, names[p_]))
    if nsplit < C.Q_SPLIT_MIN:
        F('file', 'quota', 'only %d templates have a sentence boundary between {M} and {S} in both bases; need %d' % (nsplit, C.Q_SPLIT_MIN))
    if len(kinds) < C.Q_KINDS_MIN:
        F('file', 'quota', 'only %d distinct quantity_kind; need %d' % (len(kinds), C.Q_KINDS_MIN))
    for v, n in verbs.items():
        if n > C.Q_VERB_MAX:
            F('file', 'quota', 'verb %r used %d times; at most %d' % (v, n, C.Q_VERB_MAX))
    if numdep > C.Q_NUMDEP_MAX:
        F('file', 'quota', '%d number_dependent templates; at most %d' % (numdep, C.Q_NUMDEP_MAX))
    for t in unit['topics']:
        if not C.Q_TOPIC_MIN <= topics[t] <= C.Q_TOPIC_MAX:
            F('file', 'quota', 'topic %s used %d times; need %d..%d' % (t, topics[t], C.Q_TOPIC_MIN, C.Q_TOPIC_MAX))
    for msg in VS.file_script_problems(lang, [C.strip_ph(t) for t in alltexts]):
        F('file', 'script', msg)
    return fails


def validate_path(path, manifest=None, root=HERE, accept_dir=ACCEPT_DIR):
    try:
        doc = C.load_json(path)
    except (OSError, ValueError) as e:
        return None, ['FAIL file [json] cannot read %s: %s' % (path, e)]
    uid = doc.get('writer_unit') if isinstance(doc, dict) else None
    unit = unit_record(uid, manifest)
    if unit is None:
        return doc, ['FAIL file [unit] writer_unit %r is not in manifest_v5.json' % (uid,)]
    acc = accepted_items(unit['lang'], exclude_uid=uid, accept_dir=accept_dir, root=root)
    return doc, validate_unit(doc, unit, acc, C.prior_corpus(unit['lang']), path)


# ------------------------------------------------------------------ ROW MODE
def row_violations(rows):
    """Counter of row-level violations of a generated v5 bank (+ examples)."""
    bad, ex = collections.Counter(), []
    bypk = collections.defaultdict(list)
    for r in rows:
        bypk[r['pair_key']].append(r)
    for pk, rs in bypk.items():
        if len(rs) != 2:
            bad['pair_not_2'] += 1
            continue
        canon = lambda r: C.RUNS.sub(lambda m: {r['a']: '<M>', r['b']: '<S>'}.get(int(m.group(0)), '<D>'), r['text'])
        if canon(rs[0]) != canon(rs[1]):
            bad['pair_text_not_identical'] += 1
        if rs[0].get('twin_kind') != 'redraw' and rs[0]['ds'] != rs[1]['ds']:
            bad['distractor_differs_within_pair'] += 1
    for r in rows:
        op = H.ROW_OP[r['op']]
        vals = [int(v) for v in C.RUNS.findall(r['text'])]
        if len(vals) != r['n_numerals_written'] or len(vals) != 2 + len(r['ds']):
            bad['numeral_count'] += 1
            continue
        if vals.count(r['a']) != 1 or vals.count(r['b']) != 1:
            bad['operand_not_unique'] += 1
            continue
        want = H.op_result(op, r['a'], r['b'])
        if want is None or r['ans'] != want:
            bad['ans_wrong'] += 1
        if abs(r['ans']) in vals:
            bad['answer_written_in_prompt'] += 1
        if r['wild_op'] != C.WILD_OP[op] or r['commutative'] != (op in ('add', 'mul')):
            bad['op_fields_wrong'] += 1
        gi, gj = vals.index(r['a']), vals.index(r['b'])
        if r['minuend_written_first'] != (gi < gj):
            bad['written_first_wrong'] += 1
        if r['minuend_is_larger'] != (r['a'] > r['b']):
            bad['minuend_is_larger_wrong'] += 1
        if op == 'sub' and r.get('signed') and (r['kind'] == 'neg') != (r['a'] < r['b']):
            bad['kind_wrong'] += 1
        if len(set(r['ds'])) != len(r['ds']) or any(d in (r['a'], r['b']) for d in r['ds']):
            bad['distractors_not_distinct'] += 1
        strs = (str(r['a']), str(r['b']), str(abs(r['ans'])))
        for d in r['ds']:
            if any(str(d) in s or s in str(d) for s in strs):
                bad['distractor_collides'] += 1
        ok, why = H.gold_unique_anyop(vals, gi, gj, op, r['ans'])
        if not ok:
            bad['more_than_one_pair_gives_the_answer(any_op)'] += 1
            if len(ex) < 5:
                ex.append((r['row_id'], vals, r['ans'], why))
        if not H.gold_unique_ownop(vals, gi, gj, op, r['ans']):
            bad['more_than_one_pair_gives_the_answer(own_op)'] += 1
        if bool(H.collisions(vals, op)) != bool(r.get('attr_collision')):
            bad['attr_collision_field_wrong'] += 1
    return bad, ex


# ------------------------------------------------------------------ corpus reports
def latest_files(wdir=WRITERS_DIR):
    """uid -> path of its highest attempt on disk."""
    best = {}
    for p in glob.glob(os.path.join(wdir, '*', 'W5-*.json')):
        b = os.path.basename(p)[:-5]
        uid, _, att = b.partition('.r')
        k = int(att) if att else 0
        if uid not in best or k > best[uid][0]:
            best[uid] = (k, p)
    return {u: p for u, (k, p) in best.items()}


def diversity(items):
    """Per-language diversity numbers over a list of items."""
    n = len(items)
    if not n:
        return {}
    sh = [C.shingles(C.dup_text(it)) for it in items]
    js = [C.jaccard(sh[i], sh[j]) for i in range(n) for j in range(i + 1, n)] if n <= 1500 else []
    vocab = set().union(*sh) if sh else set()
    return dict(templates=n, quantity_kinds=len(set(it.get('quantity_kind', '').casefold() for it in items)),
                verbs=len(set(it.get('verb', '').casefold() for it in items)),
                topics=len(set(it.get('topic') for it in items)), units=len(set(it.get('unit', '') for it in items)),
                ops=dict(collections.Counter(it.get('op') for it in items)),
                shapes=dict(collections.Counter(it.get('shape') for it in items)),
                char4_types=len(vocab), char4_types_per_template=round(len(vocab) / float(n), 1),
                jaccard_median=(round(sorted(js)[len(js) // 2], 3) if js else None),
                jaccard_max=(round(max(js), 3) if js else None))


def corpus(wdir=WRITERS_DIR, out=None):
    files = latest_files(wdir)
    bylang = collections.defaultdict(list)
    for uid, p in sorted(files.items()):
        try:
            doc = C.load_json(p)
        except ValueError:
            continue
        for it in doc.get('items', []):
            bylang[doc.get('language_code')].append((uid, it))
    pairs = []
    for lang, its in sorted(bylang.items()):
        sh = [C.shingles(C.dup_text(it)) for _, it in its]
        for i in range(len(its)):
            for j in range(i + 1, len(its)):
                if its[i][0] != its[j][0]:
                    s = C.jaccard(sh[i], sh[j])
                    if s >= C.NEAR_DUP:
                        pairs.append(dict(lang=lang, a=its[i][1]['id'], b=its[j][1]['id'], jaccard=round(s, 3)))
        d = diversity([it for _, it in its])
        print('%s: %s' % (lang, json.dumps(d)))
    print('cross-unit near-duplicate pairs (char-4-gram Jaccard >= %.2f): %d' % (C.NEAR_DUP, len(pairs)))
    for x in pairs[:20]:
        print('  %s  %s ~ %s  %.3f' % (x['lang'], x['a'], x['b'], x['jaccard']))
    if out:
        C.dump_json(out, pairs)
    return pairs


def calibrate():
    """Reproduce the evidence for NEAR_DUP: pairwise Jaccard among existing, distinct templates vs planted near-copies."""
    rows = []
    for lang in ('en', 'ru', 'zh', 'ja', 'ar', 'de', 'hi', 'ko', 'th'):
        items = [t for s_, t in C.prior_corpus(lang, include_examples=False) if not s_.startswith('writers_wild')]
        sh = [C.shingles(t) for t in items]
        js = sorted(C.jaccard(sh[i], sh[j]) for i in range(len(sh)) for j in range(i + 1, len(sh)))
        if js:
            rows.append((lang + ' verified', len(items), js[len(js) // 2], js[int(0.95 * len(js))], js[-1]))
    items = [t for s, t in C.prior_corpus('en', include_examples=False) if s.startswith('writers_wild')]
    sh = [C.shingles(t) for t in items]
    js = sorted(C.jaccard(sh[i], sh[j]) for i in range(len(sh)) for j in range(i + 1, len(sh)))
    if js:
        rows.append(('en v4wild', len(items), js[len(js) // 2], js[int(0.95 * len(js))], js[-1]))
    for name, n, med, p95, mx in rows:
        print('  %-14s n=%3d  median %.3f  p95 %.3f  max %.3f' % (name, n, med, p95, mx))
    a = ('The help desk logged {M} tickets in the morning, {T} tickets in the afternoon and {S} tickets in the evening. '
         'How many more tickets did the help desk log in the morning than in the evening?')
    b = ('The front office logged {M} calls in the morning, {T} calls in the afternoon and {S} calls in the evening. '
         'How many more calls did the front office log in the morning than in the evening?')
    c = ('The clinic saw {M} patients in the morning, {T} in the afternoon and {S} in the evening. '
         'How many more patients did it see in the morning than in the evening?')
    print('  planted noun swap %.3f ; planted light rephrase %.3f ; threshold NEAR_DUP = %.2f' % (
        C.jaccard(C.shingles(a), C.shingles(b)), C.jaccard(C.shingles(a), C.shingles(c)), C.NEAR_DUP))
    pl = [it for it in C.planted_unit(1)[0]['items'] + C.planted_unit(2)[0]['items']]
    sims = []
    for it in pl:
        sims += [C.jaccard(C.shingles(it['facts_first']), C.shingles(it['base_first'])),
                 C.jaccard(C.shingles(it['facts_second']), C.shingles(it['base_second']))]
    print('  planted base-vs-facts similarity: min %.3f median %.3f (BASE_MIN_SIM = %.2f)' % (
        min(sims), sorted(sims)[len(sims) // 2], C.BASE_MIN_SIM))


# ------------------------------------------------------------------ selftest
def selftest():
    import copy
    ok = True

    def run(doc, unit, want, name, accepted=None, prior=None):
        nonlocal ok
        f = validate_unit(doc, unit, accepted, prior)
        tags = set(x.split('[')[1].split(']')[0] for x in f)
        good = (not f) if want is None else (want in tags)
        ok &= good
        print('  %s  %s -> %s' % ('ok  ' if good else 'FAIL', name, sorted(tags) or 'clean'))
        if want is None and f:
            for x in f[:8]:
                print('        ' + x)

    d1, u1 = C.planted_unit(1)
    d2, u2 = C.planted_unit(2)
    run(d1, u1, None, 'planted unit 1 is clean')
    run(d2, u2, None, 'planted unit 2 is clean')
    run(d1, u1, None, 'planted unit 1 vs the real prior corpora (verified en + v4wild): clean',
        prior=C.prior_corpus('en', include_examples=False))
    run(d1, u1, 'novelty', 'an English unit that copies the brief examples -> [novelty]', prior=C.prior_corpus('en'))

    def mut(f, tag, name, doc=d1, unit=u1, **kw):
        x = copy.deepcopy(doc)
        f(x)
        run(x, unit, tag, name, **kw)

    mut(lambda x: x['items'][0].update(facts_first=x['items'][0]['facts_first'].replace('{T}', 'many')), 'placeholder', 'facts without {T}')
    mut(lambda x: x['items'][3].update(facts_first=x['items'][3]['facts_second']), 'order', '{S} before {M} in facts_first')
    mut(lambda x: x['items'][1].update(facts_second=x['items'][1]['facts_first'].replace('{M}', '{Q}').replace('{S}', '{M}').replace('{Q}', '{S}')), 'swap', 'slots swapped without moving the words')
    mut(lambda x: x['items'][2].update(question='How many bicycles did Line North assemble on 2 days?'), 'digit', 'a digit in the question')
    mut(lambda x: x['items'][2].update(question='How many bicycles did Line North assemble in two days?'), 'numberword', 'a number word')
    mut(lambda x: x['items'][2].update(question='How many bicycles did Line North assemble in the first week?'), 'numberword', 'an English ordinal')
    mut(lambda x: x['items'][9].update(question='How many crates were needed for all the bottles?'), 'div', 'division rounding-up word')
    mut(lambda x: x['items'][4].update(signed=False, sign_convention='', ), 'quota', 'only 1 signed sub of 3')
    mut(lambda x: x['items'][6].update(signed=True, sign_convention='x'), 'vocab', 'signed on a mul template')
    mut(lambda x: x['items'][11].update(div_mode='group_size'), 'quota', 'div modes not both present')
    mut(lambda x: x['items'][0].update(t_mimics='M'), 'vocab', 'add with t_mimics M')
    mut(lambda x: x['items'][5].update(op='add'), 'quota', 'cell quota broken')
    mut(lambda x: x['items'][7].update(facts_first=x['items'][0]['facts_first'], question=x['items'][0]['question']), 'duplicate', 'a copied template')
    mut(lambda x: x['items'][7].update(
        facts_first='This morning the packing hall sealed {M} boxes of soap, {T} boxes of shampoo and {S} boxes of toothpaste.',
        question='How many boxes of soap and toothpaste did the packing hall seal this morning?'), 'neardup', 'a noun-swapped copy')
    mut(lambda x: x['items'][0].update(base_first='Tomorrow a quite different team will stack {M} barrels while {S} wait outside.'), 'base', 'base unrelated to its facts')
    mut(lambda x: x['items'][0].update(question='How many cartons did the hall seal'), 'question', 'question without a question mark')
    mut(lambda x: x['items'][0].update(ex_sentence='The hall is building {D} and {D}.'), 'placeholder', 'two {D} in the ex sentence')
    mut(lambda x: x['items'][0].update(topic='football'), 'vocab', 'topic outside the unit slice')
    mut(lambda x: x.update(lead_in='Answer:'), 'unit', 'lead_in differs from the manifest')
    mut(lambda x: [it.update(verb='make') for it in x['items'][:3]], 'quota', 'one verb three times')
    mut(lambda x: [it.update(numeral_grammar='number_dependent') for it in x['items'][:3]], 'quota', 'three number_dependent')
    mut(lambda x: [it.update(facts_first=it['facts_first']) for it in x['items']] and x['items'][0].update(
        facts_first='This morning the packing hall sealed {T} cartons of shampoo, {M} cartons of soap and {S} cartons of toothpaste.'),
        'position', 'moving {T} against the manifest position -> [position]')
    mut(lambda x: x['items'][0].update(facts_second='{S} cartons of toothpaste were sealed. {T} {M} cartons of soap.'), 'adjacent', 'two neighbouring slots')
    run(d2, u2, 'neardup-accepted', 'unit 2 vs an accepted copy of itself', accepted=[(it['id'] + 'x', it) for it in d2['items']])
    # ROW MODE on planted rows
    r = dict(row_id='x', pair_key='k', text='A 40 B 17 C 9 ?', a=40, b=17, ans=23, op='subtraction', wild_op='aspread',
             commutative=False, n_numerals_written=3, ds=[9], minuend_written_first=True, minuend_is_larger=True,
             kind='pos', signed=True, attr_collision=False, twin_kind='value_swap')
    r2 = dict(r, row_id='y', text='A 17 B 40 C 9 ?', a=17, b=40, ans=-23, minuend_is_larger=False, minuend_written_first=True, kind='neg')
    bad, _ = row_violations([r, r2])
    chk_ = not bad
    print('  %s  row mode: a clean minimal pair -> %s' % ('ok  ' if chk_ else 'FAIL', dict(bad) or 'clean')); ok &= chk_
    r3 = dict(r, row_id='z', pair_key='k2', text='A 7 B 5 C 9 ?', a=7, b=5, ans=2, ds=[9], attr_collision=True)
    r4 = dict(r3, row_id='w', text='A 5 B 7 C 9 ?', a=5, b=7, ans=-2, kind='neg', minuend_is_larger=False)
    bad, _ = row_violations([r3, r4])
    chk_ = bad['more_than_one_pair_gives_the_answer(any_op)'] == 2
    print('  %s  row mode: 7,5,9 (9-7 also gives 2) caught on both rows -> %s' % ('ok  ' if chk_ else 'FAIL', dict(bad))); ok &= chk_
    r5 = dict(r, row_id='v', pair_key='k3', text='A 3 B 9 C 4 ?', a=3, b=9, ans=12, op='addition', wild_op='asum', commutative=True,
              ds=[4], minuend_is_larger=False, kind='pos', signed=False)
    bad, _ = row_violations([r5, dict(r5, row_id='u', text='A 9 B 3 C 4 ?', a=9, b=3, minuend_is_larger=True)])
    chk_ = bad['more_than_one_pair_gives_the_answer(any_op)'] == 2 and not bad['more_than_one_pair_gives_the_answer(own_op)']
    print('  %s  row mode: add 3+9 vs 3*4 caught by the any-op rule only -> %s' % ('ok  ' if chk_ else 'FAIL', dict(bad))); ok &= chk_
    bad, _ = row_violations([r])
    chk_ = bad['pair_not_2'] == 1
    print('  %s  row mode: a widowed half pair -> %s' % ('ok  ' if chk_ else 'FAIL', dict(bad))); ok &= chk_
    # corpus near-dup across units on a temp tree
    td = C.selftest_dir()
    C.dump_json(os.path.join(td, 'en', 'W5-en-u01.json'), d1)
    x = copy.deepcopy(d1)
    x['writer_unit'] = 'W5-en-u03'
    for j, it in enumerate(x['items']):
        it['id'] = 'W5-en-u03-%02d' % (j + 1)
    C.dump_json(os.path.join(td, 'en', 'W5-en-u03.json'), x)
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        pairs = corpus(td)
    chk_ = len(pairs) == 12
    print('  %s  corpus mode: a copied unit gives 12/12 cross-unit near-duplicate pairs (%d)' % ('ok  ' if chk_ else 'FAIL', len(pairs))); ok &= chk_
    C.selftest_cleanup()
    print('SELFTEST validate_v5: %s' % ('0 fail' if ok else 'FAIL'))
    return ok


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('path', nargs='?')
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--bank', default='')
    ap.add_argument('--corpus', action='store_true')
    ap.add_argument('--corpus-out', default='')
    ap.add_argument('--calibrate', action='store_true')
    a = ap.parse_args(argv[1:])
    if a.selftest:
        return 0 if selftest() else 1
    if a.calibrate:
        calibrate()
        return 0
    if a.corpus:
        corpus(out=a.corpus_out or None)
        return 0
    if a.bank:
        rows = [json.loads(l) for l in open(a.bank, encoding='utf-8')]
        bad, ex = row_violations(rows)
        print('ROWS %d; ROW VIOLATIONS: %s' % (len(rows), dict(bad) or 'NONE'))
        for e in ex:
            print('   %s numerals %s ans %s: %s' % e)
        return 1 if bad else 0
    if not a.path:
        ap.print_help()
        return 2
    doc, fails = validate_path(a.path)
    if fails:
        for f in fails:
            print(f)
        print('VALIDATE FAIL %d problem(s) in %s' % (len(fails), a.path))
        return 1
    print('VALIDATE ok %d' % len(doc['items']))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
