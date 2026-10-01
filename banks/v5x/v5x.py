#!/usr/bin/env python3
"""v5x.py -- BANK v5x: v5 (wild-shaped distractors, add / sub / mul / div) extended to the 36 languages of v3_61 that
v5 lacks, with a QUESTION-FORM axis (F0-F7). Stdlib only. It WRAPS the pinned v5 tools (../v5: v5_common, validate_v5,
host_attr_v5, make_blind_v5, check_v5, gen_v5; md5s in ../v5/V5_CODE.md5) and edits none of them; everything it writes
lives under this folder.

    python3 v5x.py manifest                 # manifest/units/*.json, manifest/groups/*.json, manifest/MANIFEST_INDEX.json
    python3 v5x.py status [--chunk C1]      # every unit and verifier group, from the files alone
    python3 v5x.py next <UNIT>              # WRITERS run this: the unit spec as JSON (cells, forms, notes, output_path)
    python3 v5x.py next --chunk C1          # the chunk's units still to write (pending / invalid / rejected)
    python3 v5x.py validate <path>          # WRITERS run this: 'VALIDATE ok 12' or 'FAIL <where> [<tag>] <message>' lines
    python3 v5x.py close <CHUNK>            # lock; accept the chunk's 24 units; build its 4 blind files (+ keys)
    python3 v5x.py blind <GROUP>            # one blind file (the close does this; kept for by-hand runs)
    python3 v5x.py format <GROUP> [<OUT>]   # VERIFIERS run this: 'FORMAT ok N' or FAIL lines
    python3 v5x.py report                   # -> VERIFY_REPORT_v5x.md + VERIFY_DISAGREE_v5x.jsonl (+ pilot go / no-go)
    python3 v5x.py clean [--chunk C1] [--out F]   # -> clean/clean_v5x_<C1|all>.json (+ _NOTES.md), never overwritten
    python3 v5x.py gen --clean F --out-dir D [--numdep keep|drop]   # rows through gen_v5.build + the form rules below
    python3 v5x.py idscan                   # story_id ranges of every bank row file under _role/ (keys / held-out test sets skipped)
    python3 v5x.py digitscan                # non-ASCII digits per language in v3_61/signed_A_int.jsonl
    python3 v5x.py selftest

UNITS. Writer unit W5X-<lang>-uNNN, NNN = 501 + 4 i + (k - 1) (i = the language's index in the chunk order of
  v5x_lang.CHUNKS, k = 1..4): 144 units, 12 templates each, 1,728 templates. The v5 unit schema byte for byte (no new
  item key): the question form is a per-cell field of the MANIFEST unit record, like v5's t_first_position.
  gen_v5 derives story_id = int(uid after its LAST 'u') * 100 + MM, so v5x story ids are 50101..64412, one number per
  (language, unit): unique across languages too, disjoint from W5 101-3212, R5 5101-9912, X5 10101-17012, A5 20101-
  30412, AB1 40101-43015 and every story id in a bank row file (selftest: the pinned list and a live scan).
TOPICS. Unit k of language i takes half-slice a = (i + 12 (k - 1)) mod 48 of v5_common.SLICES: the 4 units of a
  language fall in 4 different slices, and the 144 units use each of the 48 half-slices exactly 3 times.
{T} POSITION. v5's rule with v5x indices: POSITIONS[(k - 1 + i + op + shape) mod 3] (each unit: 4 first / 4 middle /
  4 last).
FORMS. form(i, k, cell) = F[(3 op + shape + 2 (k - 1) + i) mod 8]: per language each form 6 times of 48, every unit
  all 8 forms (4 of them twice), every (op, shape) cell 4 distinct forms, every shape each form exactly twice, every op
  each form once or twice; pooled over the 36 languages every (op, shape, form) cell holds exactly 18 templates.
CHUNKS. 6 chunks of 6 languages (v5x_lang.CHUNKS). Verifier unit = the chunk's 6 languages x one unit number (288
  texts, V5X-Cn-kK); the flagged chunk C6 is split 3 + 3 (am si yo | bo km my) x 2 unit numbers (V5X-C6a-k12 ...),
  also 288 texts. 4 verifier units per chunk.
VALIDATION = validate_v5.validate_unit (every pinned check: schema, placeholders, order, swap, adjacency, digits,
  symbols, number words, script, base similarity, duplicates, novelty against verified/<lang>.verified.json, accepted
  near-duplicates, position, all 12-template quotas), run with the v5x_lang patch, MINUS its [question] line (replaced
  per form and language), PLUS [form] (the per-form mechanical checks) and [char] (emoji, bidi, private use).
  Form checks: F0 F1 F3 F7 the question ends as a question; F2 ends as a statement (not a question, except in
  my / bo / km where a question also ends in the full stop); F4 F5 either; F6 exactly one blank (3+ underscores) in the
  question (anywhere in it: verb-final languages put a verb or counter after it), and no blank in any other text or form; '=' stays refused (the pinned [symbol] check) unless
  F6_ALLOW_EQUALS; F7 the four facts / base texts open with ONE speaker label ("Label:"), the question with a
  DIFFERENT one, and the two extra sentences with none. F1 cannot be seen in the template: it is enforced by
  construction (every composed text of an F1 template, blind or row, puts the question first) and confirmed blind.
BLIND. The v5 four texts per template (first, second, base_ex, base_sem), slots renamed {A} {B} {C} in order; the
  question goes FIRST in every text of an F1 template and last otherwise; every blind item carries its intended form
  code, and the verifier answers VERIFY_v5.md's fields plus form_ok (ADDON_v5x_verify.md).
CLEANING = check_v5.judge unchanged (D1 op / operand pair / role mismatch drops; D2 a flag other than
  number_dependent_grammar drops; numdep keep + tag; signed read as unnatural demotes) PLUS D5: form_ok false on any
  text drops the template (FORM_FAIL_DROPS; a mislabelled form would poison a form hold-out).
ROWS = gen_v5.build on the kept templates (so every pinned row rule, twin, tier, attribution and audit is unchanged),
  then per row: q_form / q_form_name / chunk fields; an F1 template's question-last rows are recomposed question-first,
  and an F6 / F7 template's question-first rows question-last (the question carries no numeral, so the numerals, their
  order, the operands' positions and every label are unchanged; the selftest checks this); row_id / pair_key prefix
  sg5x:, source signed_bank_v5x, bank_version v5x.
Nothing is ever overwritten: every attempt its own file, every acceptance its own stamp, blind / clean files refused
  if different. Closes serialise on accept.lock.
"""
import sys
sys.dont_write_bytecode = True   # set BEFORE importing anything: never write __pycache__ into v5/ or v5x/
import argparse
import collections
import contextlib
import copy
import fcntl
import glob
import hashlib
import io
import json
import math
import os
import re
import shutil
import tempfile
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
SIGNED = os.path.dirname(HERE)
ROLE = os.path.dirname(SIGNED)
V5 = os.path.join(SIGNED, 'v5')
sys.path.insert(0, HERE)
sys.path.insert(0, V5)
import v5x_lang as XL      # noqa: E402
XL.patch()
import v5_common as C      # noqa: E402
import validate_v5 as V    # noqa: E402
import make_blind_v5 as MB  # noqa: E402
import check_v5 as K       # noqa: E402

PREFIX = 'W5X'
UID_RE = re.compile(r'^W5X-([a-z]{2})-u([0-9]{3})$')
GID_RE = re.compile(r'^V5X-C[1-9][abc]?-k[0-9]+$')
UNITS_PER_LANG = 4
UNIT_BASE = 501
N_TEMPLATES = C.UNIT_TEMPLATES                   # 12
TEXTS_PER_TEMPLATE = 4
BLIND_SEED = 'v5x-blind-1'
FORM_FAIL_DROPS = True
F6_ALLOW_EQUALS = False
FORMS = (
    ('F0', 'plain', 'the facts, then a direct question ("How many ...?")'),
    ('F1', 'question_first', 'the question comes BEFORE the facts (placed first in every text), written to be read first'),
    ('F2', 'imperative', 'an instruction, not a question ("Work out / Find / Calculate how many ...")'),
    ('F3', 'conditional', 'a conditional or hypothetical question ("If ..., how many ...?"); the condition adds no number and no step'),
    ('F4', 'indirect', 'an indirect or embedded question ("I want to know how many ...", "Tell me how many ...")'),
    ('F5', 'casual', 'a casual, chat-style question (informal register; abbreviations natural to the language)'),
    ('F6', 'fill_blank', 'a statement that ends in a blank ___ standing for the answer'),
    ('F7', 'dialogue', 'two speakers: the facts are one speaker\'s turn, the question another speaker\'s turn'),
)
FORM_CODES = tuple(f for f, _, _ in FORMS)
FORM_NAME = {f: n for f, n, _ in FORMS}
FORM_DESC = {f: d for f, _, d in FORMS}
BLANK = re.compile(r'_{3,}')
VARIANTS = MB.VARIANTS
# story ids already taken (DESIGN_v5x.md section 3; each line from the file that assigns it)
OCCUPIED = ((0, 999, 'v2 / v3 / v3_50 / v3_61 / v4 / v4wild / framebank / oosprose / numwords: per-language story ids'),
            (101, 3212, 'W5 (v5 units 1-32: gen_v5 uid*100+MM)'), (5101, 9912, 'R5 (v5/ruuk, reserved 51-99)'),
            (10101, 17012, 'X5 (v5/weird, units 101-170)'), (20101, 20813, 'A5 abstain pilot'),
            (30101, 30412, 'A5 abstain re-pilot'), (40101, 43015, 'AB1 abstainbank (units 401-430)'))
# pilot bars (DESIGN_v5x.md section 8): anchored on v5 round 1 (CTRN/log/2026-09-29.md 16:01), scaled to one chunk
BARS = (('B2 all three (op, operand pair, role) per text', 'all', 0.96, 'v5 round 1: 1181/1200 = 98.4%'),
        ('B3 role (sub / div) per text', 'role', 0.96, 'v5 round 1: 585/600 = 97.5%'),
        ('B4 templates kept', 'kept', 0.85, 'v5 round 1: 275/300 = 91.7%'),
        ('B5 templates kept, EVERY language (of 48)', 'kept_lang', 0.75, 'v5 round 1 worst: fa / ru 8/12 = 66.7%; rounds 1-3 worst outside ru/uk: fr 29/36 = 80.6%'),
        ('B6 texts flagged at most', 'flagged', 0.12, 'v5 round 1: 81/1200 = 6.8%'),
        ('B7 form_ok per text', 'form_ok', 0.90, 'new in v5x (no anchor)'),
        ('B8 templates kept, EVERY form (of 36)', 'kept_form', 0.75, 'new in v5x (no anchor)'))


class Refused(Exception):
    pass


# ------------------------------------------------------------------ small file helpers
def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1) + '\n'


def read(p):
    with open(p, encoding='utf-8') as fh:
        return fh.read()


def write_once(path, txt):
    """Write txt to path unless the path exists: identical -> no-op, different -> Refused."""
    if os.path.exists(path):
        if read(path) != txt:
            raise Refused('%s exists and differs; it is never overwritten' % path)
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(txt)
    return True


def cell_of(op, shape):
    return '%s/%s' % (op, shape)


CELLS = tuple(cell_of(o, s) for o in C.OPS_ORDER for s in C.SHAPES_ORDER)


# ------------------------------------------------------------------ the design, as functions
def unit_number(i, k):
    return UNIT_BASE + UNITS_PER_LANG * i + (k - 1)


def uid_of(lang, k, langs=XL.LANGS):
    return '%s-%s-u%03d' % (PREFIX, lang, unit_number(langs.index(lang), k))


def half_slice(i, k):
    a = (i + 12 * (k - 1)) % C.N_ASSIGN
    sid, title, topics = C.SLICES[a // 2]
    h = a % 2
    return sid, title, h, topics[3 * h:3 * h + 3]


def t_positions(i, k):
    return {cell_of(o, s): C.POSITIONS[(k - 1 + i + a + b) % 3]
            for a, o in enumerate(C.OPS_ORDER) for b, s in enumerate(C.SHAPES_ORDER)}


def forms_for(i, k):
    return {cell_of(o, s): FORM_CODES[(3 * a + b + 2 * (k - 1) + i) % 8]
            for a, o in enumerate(C.OPS_ORDER) for b, s in enumerate(C.SHAPES_ORDER)}


def story_ids(uid):
    n = int(uid.rsplit('u', 1)[1])
    return [n * 100 + j for j in range(1, N_TEMPLATES + 1)]


def unit_record(lang, k, chunk, langs=XL.LANGS, lead_in=None, topics=None, slice_=None, positions=None, forms=None):
    i = langs.index(lang)
    sid, title, h, tp = half_slice(i, k)
    uid = uid_of(lang, k, langs)
    pos = positions or t_positions(i, k)
    fm = forms or forms_for(i, k)
    cells = [dict(cell=c, op=c.split('/')[0], shape=c.split('/')[1], t_first_position=pos[c], form=fm[c],
                  form_name=FORM_NAME[fm[c]]) for c in CELLS]
    return dict(uid=uid, lang=lang, language=XL.LANG_NAMES.get(lang, lang), unit=int(uid.rsplit('u', 1)[1]), k=k,
                chunk=chunk, slice=slice_ or sid, slice_title=title if not slice_ else 'selftest', half=h,
                topics=list(topics or tp), lead_in=lead_in if lead_in is not None else C.verified_lead_in(lang),
                t_first_position=pos, forms=fm, cells=cells, templates=N_TEMPLATES,
                output_file='writers/%s/%s.json' % (lang, uid), story_ids=[story_ids(uid)[0], story_ids(uid)[-1]],
                language_notes=XL.language_notes(lang) if lang in XL.LANGS else {})


def group_records(chunk, langs, uidmap):
    """Verifier units of a chunk: 4 x (6 languages, one unit number). The flagged chunk C6: am si yo x 2 unit-number
    pairs (288 texts each), km my x 2 pairs (192 each), and bo alone x its 4 units (192), so a deferred Tibetan never
    blocks the other five languages."""
    out = []
    if chunk == 'C6':
        for half, grp in (('a', ('am', 'si', 'yo')), ('b', ('km', 'my'))):
            for ks in ((1, 2), (3, 4)):
                out.append((chunk + half, 'k%d%d' % ks, grp, ks))
        out.append((chunk + 'c', 'k1234', ('bo',), (1, 2, 3, 4)))
    else:
        for k in range(1, UNITS_PER_LANG + 1):
            out.append((chunk, 'k%d' % k, langs, (k,)))
    recs = []
    for ch, ktag, ls, ks in out:
        gid = 'V5X-%s-%s' % (ch, ktag)
        deps = [uidmap[(l, k)] for k in ks for l in ls]
        recs.append(dict(uid=gid, chunk=chunk, languages=list(ls), ks=list(ks), deps=deps,
                         blind='blind/%s.blind.json' % gid, key='blind_key/%s.key.json' % gid,
                         out='verify/%s.json' % gid, texts=len(deps) * N_TEMPLATES * TEXTS_PER_TEMPLATE))
    return recs


def build_manifest(chunks=XL.CHUNKS):
    langs = tuple(l for _, _, ls in chunks for l in ls)
    units, groups, uidmap = [], [], {}
    for ch, title, ls in chunks:
        for lang in ls:
            for k in range(1, UNITS_PER_LANG + 1):
                u = unit_record(lang, k, ch, langs)
                units.append(u)
                uidmap[(lang, k)] = u['uid']
        groups += group_records(ch, ls, uidmap)
    return units, groups


# ------------------------------------------------------------------ context (the real tree or a selftest tree)
class Ctx:
    def __init__(self, root=HERE, units=None, groups=None, clock=None):
        self.root = root
        self._units, self._groups = units, groups
        self.clock = clock or (lambda: time.strftime('%Y-%m-%d %H:%M:%S %Z'))

    def p(self, *a):
        return os.path.join(self.root, *a)

    def units(self):
        if self._units is None:
            self._units = [C.load_json(q) for q in sorted(glob.glob(self.p('manifest', 'units', '*.json')))]
            self._units.sort(key=lambda u: (u['chunk'], u['k'], XL.LANGS.index(u['lang']) if u['lang'] in XL.LANGS else 0))
        return self._units

    def groups(self):
        if self._groups is None:
            self._groups = [C.load_json(q) for q in sorted(glob.glob(self.p('manifest', 'groups', '*.json')))]
        return self._groups

    def unit(self, uid):
        for u in self.units():
            if u['uid'] == uid:
                return u
        return None

    def group(self, gid):
        for g in self.groups():
            if g['uid'] == gid:
                return g
        return None

    def chunk_ids(self):
        return sorted(set(u['chunk'] for u in self.units()))


def cmd_manifest(ctx):
    units, groups = build_manifest()
    wrote = 0
    for u in units:
        wrote += write_once(ctx.p('manifest', 'units', u['uid'] + '.json'), dumps(u))
    for g in groups:
        wrote += write_once(ctx.p('manifest', 'groups', g['uid'] + '.json'), dumps(g))
    idx = dict(bank='v5x', note='BANK v5x work units (v5x.py manifest). Launch order = chunk order; resume from the files.',
               languages=list(XL.LANGS), flagged=list(XL.FLAGGED),
               chunks=[dict(chunk=ch, title=t, languages=list(ls),
                            units=[u['uid'] for u in units if u['chunk'] == ch],
                            groups=[g['uid'] for g in groups if g['chunk'] == ch]) for ch, t, ls in XL.CHUNKS],
               forms=[dict(code=f, name=n, desc=d) for f, n, d in FORMS],
               story_ids=[min(s for u in units for s in u['story_ids']), max(s for u in units for s in u['story_ids'])],
               totals=dict(writer_units=len(units), templates=len(units) * N_TEMPLATES, verifier_units=len(groups),
                           blind_texts=sum(g['texts'] for g in groups)),
               md5={os.path.relpath(q, ctx.root): C.md5_file(q) for q in
                    sorted(glob.glob(ctx.p('manifest', 'units', '*.json')) + glob.glob(ctx.p('manifest', 'groups', '*.json')))})
    wrote += write_once(ctx.p('manifest', 'MANIFEST_INDEX.json'), dumps(idx))
    print('MANIFEST %d writer units, %d verifier units, %d files written (0 = unchanged); index md5 %s' % (
        len(units), len(groups), wrote, C.md5_file(ctx.p('manifest', 'MANIFEST_INDEX.json'))))
    return 0


# ------------------------------------------------------------------ the form checks (per template)
LABEL_INNER = " .'’-\u200c\u200d\u0f0b\u1361"     # + Tibetan tsheg and Ethiopic wordspace (inside names / roles)


def speaker_label(t):
    """The speaker label a text opens with ('Label:' / 'Label：' / 'Label፦'), casefolded, or None."""
    t = (t or '').lstrip()
    m = re.match(r'([^:：፦{}\n]{1,32}?)\s*[:：፦]', t)
    if not m:
        return None
    lab = m.group(1).strip()
    if not lab or len(lab.split()) > 4:
        return None
    if any(not (unicodedata.category(c)[0] in 'LM' or c in LABEL_INNER) for c in lab):
        return None
    return unicodedata.normalize('NFC', lab).casefold()


def form_problems(lang, it, form):
    """[(tag, msg)] for one template against its manifest form."""
    p = []
    q = it.get('question') if isinstance(it.get('question'), str) else ''
    for key in C.TEXT_KEYS:
        t = it.get(key)
        if isinstance(t, str) and BLANK.search(t) and not (form == 'F6' and key == 'question'):
            p.append(('form', '%s: a blank (___) belongs only in the question of an F6 template' % key))
        if isinstance(t, str):
            for msg in XL.char_problems(t, lang):
                p.append(('char', '%s: %s' % (key, msg)))
    qe, se = XL.question_end_ok(lang, q), XL.statement_end_ok(lang, q)
    if form in ('F0', 'F1', 'F3', 'F7') and not qe:
        p.append(('form', '%s (%s): the question must end as a question (%s)' % (
            form, FORM_NAME[form], ' '.join(XL.QEND.get(lang, XL.QEND_DEFAULT)))))
    if form == 'F2':
        if not se:
            p.append(('form', 'F2 (imperative): the instruction must end with sentence-final punctuation (. ! or the '
                              'language\'s full stop)'))
        elif qe and lang not in XL.QUESTION_BY_FULL_STOP:
            p.append(('form', 'F2 (imperative): an instruction, not a question: do not end it with a question mark'))
    if form in ('F4', 'F5') and not (qe or se):
        p.append(('form', '%s (%s): the question must end with sentence-final punctuation or a question mark' % (form, FORM_NAME[form])))
    if form == 'F6':
        runs = BLANK.findall(q)
        if len(runs) != 1:
            p.append(('form', 'F6 (fill_blank): the question needs exactly one blank of three or more underscores (___), found %d' % len(runs)))
    if form == 'F7':
        labs = [speaker_label(it.get(k)) for k in ('facts_first', 'facts_second', 'base_first', 'base_second')]
        lq = speaker_label(q)
        if any(x is None for x in labs):
            p.append(('form', 'F7 (dialogue): each of facts_first, facts_second, base_first, base_second must open with the '
                              'first speaker\'s label ("Label: ...")'))
        elif len(set(labs)) != 1:
            p.append(('form', 'F7 (dialogue): the four facts / base texts must open with the SAME speaker label, got %s' % sorted(set(labs))))
        if lq is None:
            p.append(('form', 'F7 (dialogue): the question must open with the second speaker\'s label ("Label: ...")'))
        elif labs and labs[0] is not None and lq == labs[0]:
            p.append(('form', 'F7 (dialogue): the question must be a DIFFERENT speaker\'s turn (same label %r)' % lq))
        for k in ('ex_sentence', 'sem_sentence'):
            if speaker_label(it.get(k)) is not None:
                p.append(('form', 'F7 (dialogue): %s must not open with a speaker label (it is inserted before, between or '
                                  'after the facts)' % k))
    return p


def fail_tag(line):
    m = re.match(r'FAIL \S+ \[([a-z-]+)\]', line)
    return m.group(1) if m else ''


def validate_unit(doc, unit, accepted=(), prior=(), path=None):
    """FAIL lines for one writer unit: the pinned validate_v5.validate_unit (patched languages) minus [question], plus
    [form] / [char]."""
    fails = V.validate_unit(doc, unit, list(accepted), list(prior), path)
    ids = {}
    if isinstance(doc, dict) and isinstance(doc.get('items'), list):
        for n, it in enumerate(doc['items']):
            if isinstance(it, dict):
                ids[it.get('id') or 'item#%d' % (n + 1)] = it
    keep = []
    for f in fails:
        tag = fail_tag(f)
        if tag == 'question':
            continue                                      # replaced by the per-form, per-language question check
        if F6_ALLOW_EQUALS and tag == 'symbol':
            w = f.split(' ')[1]
            it = ids.get(w)
            if it and unit['forms'].get(cell_of(it.get('op'), it.get('shape'))) == 'F6' and \
                    f.endswith("question: arithmetic symbols '='"):
                continue
        keep.append(f)
    for w, it in ids.items():
        c = cell_of(it.get('op'), it.get('shape'))
        form = unit.get('forms', {}).get(c)
        if form is None:
            continue                                      # an unknown cell is already a [vocab] / [quota] FAIL
        for tag, msg in form_problems(unit['lang'], it, form):
            keep.append('FAIL %s [%s] %s' % (w, tag, msg))
    return keep


# ------------------------------------------------------------------ writer state, acceptance
def attempts(ctx, u):
    out = {}
    for q in glob.glob(ctx.p('writers', u['lang'], u['uid'] + '*.json')):
        b = os.path.basename(q)[:-5]
        if b == u['uid']:
            out[0] = q
        elif b.startswith(u['uid'] + '.r') and b[len(u['uid']) + 2:].isdigit():
            out[int(b[len(u['uid']) + 2:])] = q
    return out


def stamps(ctx):
    best = {}
    for q in glob.glob(ctx.p('accept', PREFIX + '-*.a*.json')):
        b = os.path.basename(q)[:-5]
        uid, _, att = b.rpartition('.a')
        if att.isdigit() and (uid not in best or int(att) > best[uid][0]):
            best[uid] = (int(att), q)
    return {u: C.load_json(q) for u, (k, q) in best.items()}


def accepted_items(ctx, lang, exclude_uid=None):
    out = []
    for uid, st in sorted(stamps(ctx).items()):
        if st.get('status') != 'accepted' or uid == exclude_uid or st.get('lang') != lang:
            continue
        for it in C.load_json(ctx.p(st['file'])).get('items', []):
            out.append((it.get('id'), it))
    return out


def prior_for(lang):
    return C.prior_corpus(lang, include_examples=False) if lang in XL.LANGS else []


def validate_path(ctx, path):
    try:
        doc = C.load_json(path)
    except (OSError, ValueError) as e:
        return None, ['FAIL file [json] cannot read %s: %s' % (path, e)]
    uid = doc.get('writer_unit') if isinstance(doc, dict) else None
    u = ctx.unit(uid) if isinstance(uid, str) and UID_RE.match(uid) else None
    if u is None:
        return doc, ['FAIL file [unit] writer_unit %r is not a unit of manifest/units/' % (uid,)]
    if os.path.dirname(os.path.abspath(path)) != ctx.p('writers', u['lang']):
        return doc, ['FAIL file [path] %s is not under %s' % (path, ctx.p('writers', u['lang']))]
    return doc, validate_unit(doc, u, accepted_items(ctx, u['lang'], exclude_uid=uid), prior_for(u['lang']), path)


def writer_state(ctx, u):
    att = attempts(ctx, u)
    if not att:
        return 'pending', dict(next_attempt=0, out=u['output_file'])
    k = max(att)
    rel = os.path.relpath(att[k], ctx.root)
    nxt = 'writers/%s/%s.r%d.json' % (u['lang'], u['uid'], k + 1)
    sp = ctx.p('accept', '%s.a%d.json' % (u['uid'], k))
    if os.path.exists(sp):
        st = C.load_json(sp)
        if st['status'] == 'accepted':
            return 'accepted', dict(attempt=k, file=rel)
        return 'rejected', dict(attempt=k, file=rel, next_attempt=k + 1, out=nxt, duplicates=st.get('duplicates', []))
    _, fails = validate_path(ctx, att[k])
    if fails:
        return 'invalid', dict(attempt=k, file=rel, next_attempt=k + 1, out=nxt, fails=len(fails), first_fail=fails[0])
    return 'valid', dict(attempt=k, file=rel)


def writer_spec(ctx, u, info):
    spec = dict(unit_id=u['uid'], language=u['language'], language_code=u['lang'], unit=u['unit'], chunk=u['chunk'],
                slice=u['slice'], slice_title=u['slice_title'], topics=u['topics'], lead_in=u['lead_in'],
                cells=u['cells'], t_first_position=u['t_first_position'],
                language_notes=u.get('language_notes', {}),
                output_path=ctx.p(info.get('out', u['output_file'])), attempt=info.get('next_attempt', 0))
    if info.get('next_attempt'):
        spec['previous_attempt'] = ctx.p(info['file'])
        spec['rewrite_templates'] = sorted(set(d['template'] for d in info.get('duplicates', []))) or \
            'all flagged by the validator'
        if info.get('duplicates'):
            spec['duplicates_of_accepted'] = info['duplicates']
    return spec


@contextlib.contextmanager
def locked(ctx):
    os.makedirs(ctx.root, exist_ok=True)
    fh = open(ctx.p('accept.lock'), 'w')
    fcntl.flock(fh, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def accept_units(ctx, only=None):
    """Judge every 'valid' unit (in manifest order) against every ACCEPTED template of its language, including units
    accepted earlier in this pass; one stamp per judged attempt, never overwritten."""
    done = []
    for u in ctx.units():
        if only is not None and u['uid'] not in only:
            continue
        s, info = writer_state(ctx, u)
        if s != 'valid':
            continue
        path = ctx.p(info['file'])
        doc = C.load_json(path)
        acc = accepted_items(ctx, u['lang'], exclude_uid=u['uid'])
        dups = []
        for it in doc['items']:
            sh = C.shingles(C.dup_text(it))
            for tid, ait in acc:
                j = C.jaccard(sh, C.shingles(C.dup_text(ait)))
                if j >= C.NEAR_DUP:
                    dups.append(dict(template=it['id'], accepted_template=tid, jaccard=round(j, 3)))
        stamp = dict(uid=u['uid'], lang=u['lang'], attempt=info['attempt'], file=info['file'], md5=C.md5_file(path),
                     status='rejected' if dups else 'accepted', duplicates=dups,
                     checked_against=sorted(set(t.rsplit('-', 1)[0] for t, _ in acc)), stamped_at=ctx.clock())
        sp = ctx.p('accept', '%s.a%d.json' % (u['uid'], info['attempt']))
        if os.path.exists(sp):
            continue
        C.dump_json(sp, stamp)
        done.append((u['uid'], stamp['status'], len(dups)))
    return done


def chunk_units(ctx, ch):
    return [u for u in ctx.units() if u['chunk'] == ch]


def chunk_groups(ctx, ch):
    return [g for g in ctx.groups() if g['chunk'] == ch]


def close_plan(ctx, ch, defer=()):
    """(units the close needs, groups it builds, groups it skips) when the languages in `defer` are deferred."""
    langs = set(u['lang'] for u in chunk_units(ctx, ch))
    bad = [l for l in defer if l not in langs]
    if bad:
        raise Refused('--defer %s: not a language of %s (%s)' % (','.join(bad), ch, ' '.join(sorted(langs))))
    us = [u for u in chunk_units(ctx, ch) if u['lang'] not in defer]
    gs = [g for g in chunk_groups(ctx, ch) if not set(g['languages']) & set(defer)]
    skip = [g for g in chunk_groups(ctx, ch) if set(g['languages']) & set(defer)]
    return us, gs, skip


def close_chunk(ctx, ch, defer=()):
    """-> (rc, lines). Lock; every unit of the chunk (minus deferred languages) must be valid or accepted; accept;
    build the blind files of every verifier unit that holds no deferred language."""
    if ch not in ctx.chunk_ids():
        raise Refused('chunk must be one of %s' % ' '.join(ctx.chunk_ids()))
    us, gs, skip = close_plan(ctx, ch, defer)
    out = ['DEFERRED %s: verifier units %s not built' % (','.join(defer), ' '.join(g['uid'] for g in skip))] if defer else []
    with locked(ctx):
        ws = {u['uid']: writer_state(ctx, u)[0] for u in us}
        bad = {k: v for k, v in sorted(ws.items()) if v not in ('valid', 'accepted')}
        if bad:
            out.append('CLOSE BLOCKED %s: %d/%d units not valid: %s' % (ch, len(bad), len(us), bad))
            return 1, out
        done = accept_units(ctx, only=set(ws))
        states = {u['uid']: writer_state(ctx, u)[0] for u in us}
        n_acc = sum(1 for s in states.values() if s == 'accepted')
        out.append('ACCEPT %s: judged %d this run (%d rejected); %d/%d accepted' % (
            ch, len(done), sum(1 for _, s, _ in done if s == 'rejected'), n_acc, len(us)))
        rej = {k: v for k, v in sorted(states.items()) if v != 'accepted'}
        if rej:
            out.append('CLOSE REJECTED %s: %s (python3 v5x.py next <UNIT> prints the rewrite spec)' % (ch, rej))
            return 1, out
        for g in gs:
            n, bp = write_blind(ctx, g['uid'])
            out.append('BLIND ok %d texts -> %s' % (n, bp))
    return 0, out


# ------------------------------------------------------------------ blind files
def compose(it, variant, sep, form):
    body = {'first': it['facts_first'].strip(), 'second': it['facts_second'].strip(),
            'base_ex': it['ex_sentence'].strip() + sep + it['base_first'].strip(),
            'base_sem': it['base_second'].strip() + sep + it['sem_sentence'].strip()}[variant]
    q = it['question'].strip()
    return (q + sep + body) if form == 'F1' else (body + sep + q)


def build_blind(ctx, g):
    st = stamps(ctx)
    texts, langs = [], {}
    for d in g['deps']:
        s = st.get(d)
        if not s or s.get('status') != 'accepted':
            raise Refused('writer unit %s of %s is not accepted' % (d, g['uid']))
        u = ctx.unit(d)
        doc = C.load_json(ctx.p(s['file']))
        lang = doc['language_code']
        sep = '' if lang in C.NOSPACE else ' '
        langs[lang] = dict(language=u['language'], cue=doc['lead_in'])
        for it in doc['items']:
            form = u['forms'][cell_of(it['op'], it['shape'])]
            for var in VARIANTS:
                txt, mp = MB.rename(compose(it, var, sep, form), var)
                k = dict(template=it['id'], writer_unit=d, lang=lang, chunk=u['chunk'], variant=var, op=it['op'],
                         shape=it['shape'], signed=bool(it['signed']), div_mode=it['div_mode'], form=form, slots=mp)
                texts.append((hashlib.md5(('%s|%s|%s|%s' % (BLIND_SEED, g['uid'], it['id'], var)).encode()).hexdigest(),
                              lang, form, txt, k))
    texts.sort()
    items, key = [], {}
    for n, (_, lang, form, txt, k) in enumerate(texts):
        bid = '%s-t%03d' % (g['uid'], n + 1)
        items.append(dict(id=bid, lang=lang, form=form, text=txt))
        key[bid] = k
    return dict(verifier_unit=g['uid'], languages=langs, forms={f: '%s: %s' % (FORM_NAME[f], FORM_DESC[f]) for f in FORM_CODES},
                items=items), key


def write_blind(ctx, gid):
    g = ctx.group(gid)
    if g is None:
        raise Refused('no verifier unit %s' % gid)
    b, k = build_blind(ctx, g)
    nb, nk = dumps(b), dumps(k)
    for q, txt in ((ctx.p(g['blind']), nb), (ctx.p(g['key']), nk)):
        if os.path.exists(q) and read(q) != txt:
            raise Refused('%s exists and differs; never overwritten' % q)
    write_once(ctx.p(g['blind']), nb)
    write_once(ctx.p(g['key']), nk)
    return len(b['items']), g['blind']


# ------------------------------------------------------------------ verification: format gate, judgement
ITEM_KEYS = set(K.ITEM_KEYS) | {'form_ok'}


def fmt_fails(blind, ver):
    """check_v5.fmt_fails (md5 in V5X_CODE.md5) with the one v5x field form_ok (true / false; a note when false)."""
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
        if it['op'] not in K.OPS_V:
            f.append('%s: op %r not one of %s' % (i, it['op'], ' '.join(K.OPS_V)))
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
        if not isinstance(it['form_ok'], bool):
            f.append('%s: form_ok must be true or false' % i)
        if not isinstance(it['flags'], list) or any(x not in K.FLAGS for x in it['flags']):
            f.append('%s: flags must be a list drawn from %s' % (i, ' '.join(K.FLAGS)))
        if not isinstance(it['note'], str):
            f.append('%s: note must be a string' % i)
        elif (it['flags'] or it['op'] == 'other' or it['form_ok'] is False) and not it['note'].strip():
            f.append('%s: a flag, op "other" or form_ok false needs a note' % i)
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


def verify_attempts(ctx, gid):
    out = {}
    for q in glob.glob(ctx.p('verify', gid + '*.json')):
        b = os.path.basename(q)[:-5]
        if b == gid:
            out[0] = q
        elif b.startswith(gid + '.r') and b[len(gid) + 2:].isdigit():
            out[int(b[len(gid) + 2:])] = q
    return out


def format_lines(ctx, gid, path=None):
    g = ctx.group(gid)
    if g is None:
        return ['FORMAT FAIL no verifier unit %s' % gid]
    try:
        bl = C.load_json(ctx.p(g['blind']))
        if path is None:
            att = verify_attempts(ctx, gid)
            if not att:
                return ['FORMAT FAIL no verify file for %s' % gid]
            path = att[max(att)]
        ve = C.load_json(path)
    except (OSError, ValueError) as e:
        return ['FORMAT FAIL cannot read: %s' % e]
    f = fmt_fails(bl, ve)
    return ['FAIL ' + x for x in f] + ['FORMAT ok %d' % len(bl['items']) if not f else 'FORMAT FAIL %d problem(s)' % len(f)]


def group_state(ctx, g, ws):
    waiting = [d for d in g['deps'] if ws.get(d, ('pending',))[0] != 'accepted']
    if waiting:
        return 'blocked', dict(waiting=len(waiting))
    if not os.path.exists(ctx.p(g['blind'])):
        return 'ready', {}
    att = verify_attempts(ctx, g['uid'])
    if not att:
        return 'blinded', dict(out=g['out'])
    k = max(att)
    try:
        fails = fmt_fails(C.load_json(ctx.p(g['blind'])), C.load_json(att[k]))
    except ValueError as e:
        fails = [str(e)]
    if fails:
        return 'invalid', dict(attempt=k, next_out='verify/%s.r%d.json' % (g['uid'], k + 1), fails=len(fails))
    return 'done', dict(attempt=k, file=os.path.relpath(att[k], ctx.root))


def judge(k, v):
    """check_v5.judge + D5 (form_ok false)."""
    ok_op, ok_opr, ok_role, sg, why, tags = K.judge(k, v)
    if v.get('form_ok') is False:
        (why if FORM_FAIL_DROPS else tags).append('D5 form %s not realised' % k['form'] if FORM_FAIL_DROPS else 'form_unconfirmed')
    return ok_op, ok_opr, ok_role, sg, why, tags


def done_groups(ctx):
    out = []
    for g in ctx.groups():
        att = verify_attempts(ctx, g['uid'])
        if not os.path.exists(ctx.p(g['blind'])) or not att:
            continue
        bl, ve = C.load_json(ctx.p(g['blind'])), C.load_json(att[max(att)])
        if fmt_fails(bl, ve):
            continue
        out.append((g, bl, C.load_json(ctx.p(g['key'])), ve))
    return out


def verdicts(ctx, chunk=None):
    """{template id: dict(why, tags, n, variants, lang, form, chunk)} over every done verifier unit."""
    vd = collections.defaultdict(lambda: dict(why=[], tags=set(), n=0, variants=set()))
    covered = set()
    for g, bl, key, ve in done_groups(ctx):
        if chunk and g['chunk'] != chunk:
            continue
        covered.update(g['deps'])
        for it in ve['items']:
            k = key[it['id']]
            _, _, _, _, why, tags = judge(k, it)
            d = vd[k['template']]
            d['n'] += 1; d['why'] += ['%s: %s' % (k['variant'], w) for w in why]; d['tags'].update(tags)
            d['variants'].add(k['variant']); d['lang'] = k['lang']; d['form'] = k['form']; d['chunk'] = k['chunk']
    return vd, covered


# ------------------------------------------------------------------ report (+ pilot go / no-go per chunk)
def bar_need(frac, n, at_most=False):
    return int(math.floor(frac * n)) if at_most else int(math.ceil(frac * n - 1e-9))


def report(ctx, write=True):
    per = collections.defaultdict(collections.Counter)
    perf = collections.defaultdict(collections.Counter)
    perc = collections.defaultdict(collections.Counter)
    conf, fl, rows = collections.Counter(), collections.Counter(), []
    for g, bl, key, ve in done_groups(ctx):
        text = {i['id']: i['text'] for i in bl['items']}
        for it in ve['items']:
            k = key[it['id']]
            ok_op, ok_opr, ok_role, sg, why, tags = judge(k, it)
            for c in (per[k['lang']], perf[k['form']], perc[k['chunk']]):
                c['n'] += 1; c['op'] += ok_op; c['operands'] += ok_opr
                if ok_role is not None:
                    c['n_role'] += 1; c['role'] += ok_role
                if sg is not None:
                    c['n_signed'] += 1; c['signed'] += sg
                c['all'] += ok_op and ok_opr and ok_role is not False
                c['flagged'] += bool(it['flags'])
                c['form_ok'] += it['form_ok'] is True
            conf[(k['op'], it['op'])] += 1
            for x in it['flags']:
                fl[x] += 1
            if why or it['flags'] or sg is False or it['form_ok'] is False:
                rows.append(dict(blind_id=it['id'], lang=k['lang'], form=k['form'], template=k['template'], variant=k['variant'],
                                 text=text[it['id']], want=K.expected(k),
                                 got={x: it[x] for x in ('op', 'operands', 'role', 'signed_natural', 'form_ok')},
                                 flags=it['flags'], note=it['note'], reasons=why))
    vd, covered = verdicts(ctx)
    kept_l, kept_f, kept_c, tot_l, tot_f, tot_c = (collections.Counter() for _ in range(6))
    for tid, d in vd.items():
        good = not d['why']
        for kc, tc, key_ in ((kept_l, tot_l, d['lang']), (kept_f, tot_f, d['form']), (kept_c, tot_c, d['chunk'])):
            tc[key_] += 1; kc[key_] += good
    head = '| %s | texts | op | operands | role (sub/div) | signed (sub) | all three | form_ok | flagged | templates kept |'
    out = ['# BANK v5x -- blind verification report (v5x.py report)', '',
           '## per language', '', head % 'lang', '|---|---|---|---|---|---|---|---|---|---|']

    def line(name, c, kept, tot):
        return '| %s | %d | %d/%d | %d/%d | %d/%d | %d/%d | %d/%d | %d/%d | %d/%d | %d/%d |' % (
            name, c['n'], c['op'], c['n'], c['operands'], c['n'], c['role'], c['n_role'], c['signed'], c['n_signed'],
            c['all'], c['n'], c['form_ok'], c['n'], c['flagged'], c['n'], kept, tot)
    for lang in sorted(per, key=lambda l: XL.LANGS.index(l) if l in XL.LANGS else 99):
        out.append(line(lang, per[lang], kept_l[lang], tot_l[lang]))
    out += ['', '## per question form', '', head % 'form', '|---|---|---|---|---|---|---|---|---|---|']
    for f in FORM_CODES:
        if f in perf:
            out.append(line('%s %s' % (f, FORM_NAME[f]), perf[f], kept_f[f], tot_f[f]))
    out += ['', '## op: writer (rows) x verifier (columns)', '', '| writer | ' + ' | '.join(K.OPS_V) + ' |', '|---|' + '---|' * len(K.OPS_V)]
    for o in C.OPS:
        out.append('| %s | ' % o + ' | '.join(str(conf[(o, x)]) for x in K.OPS_V) + ' |')
    out += ['', '## flags (texts carrying each flag)', ''] + (['- %s: %d' % kv for kv in fl.most_common()] or ['- none'])
    # pilot go / no-go, per chunk whose 4 verifier units are all done
    out += ['', '## go / no-go per chunk (bars: DESIGN_v5x.md section 8; a chunk is scored once all its verifier units are done)', '']
    done_by_chunk = collections.Counter(g['chunk'] for g, _, _, _ in done_groups(ctx))
    for ch in ctx.chunk_ids():
        ng = len(chunk_groups(ctx, ch))
        nb = sum(1 for g in chunk_groups(ctx, ch) if os.path.exists(ctx.p(g['blind'])))
        if not nb or done_by_chunk[ch] < nb:
            out.append('- %s: %d/%d verifier units done (%d blind files built), not scored' % (ch, done_by_chunk[ch], ng, nb))
            continue
        if nb < ng:
            out.append('- %s: scored on %d of %d verifier units (the others not built: a deferred language)' % (ch, nb, ng))
        c = perc[ch]
        langs = sorted(set(d['lang'] for d in vd.values() if d['chunk'] == ch))
        forms_ch = collections.Counter(u['forms'][x] for u in chunk_units(ctx, ch) if u['lang'] in langs for x in CELLS)
        kf = collections.Counter(); tf = collections.Counter()
        for tid, d in vd.items():
            if d['chunk'] == ch:
                tf[d['form']] += 1; kf[d['form']] += not d['why']
        rows_b = []
        st_all = stamps(ctx)
        cu = [u for u in chunk_units(ctx, ch) if u['lang'] in langs]
        first = sum(1 for u in cu if st_all.get(u['uid'], {}).get('status') == 'accepted' and st_all[u['uid']].get('attempt') == 0)
        nu = len(cu)
        rows_b.append('| B1 writer units accepted at attempt 0 | %d/%d | >= %d/%d | %s | v5 round 1: 25/25 (0 errors, 0 send-backs) |' % (
            first, nu, bar_need(0.83, nu), nu, 'PASS' if first >= bar_need(0.83, nu) else 'FAIL'))
        for name, what, frac, anchor in BARS:
            if what == 'all':
                got, n = c['all'], c['n']; ok = got >= bar_need(frac, n)
            elif what == 'role':
                got, n = c['role'], c['n_role']; ok = got >= bar_need(frac, n)
            elif what == 'kept':
                got, n = kept_c[ch], tot_c[ch]; ok = got >= bar_need(frac, n)
            elif what == 'flagged':
                got, n = c['flagged'], c['n']; ok = got <= bar_need(frac, n, at_most=True)
            elif what == 'form_ok':
                got, n = c['form_ok'], c['n']; ok = got >= bar_need(frac, n)
            elif what == 'kept_lang':
                worst = min(langs, key=lambda l: (kept_l[l] / float(tot_l[l] or 1)))
                got, n = kept_l[worst], tot_l[worst]; ok = all(kept_l[l] >= bar_need(frac, tot_l[l]) for l in langs)
                name = name + ' (worst: %s)' % worst
            else:
                worst = min(forms_ch, key=lambda f: (kf[f] / float(tf[f] or 1)))
                got, n = kf[worst], tf[worst]; ok = all(kf[f] >= bar_need(frac, tf[f]) for f in forms_ch)
                name = name + ' (worst: %s)' % worst
            need = bar_need(frac, n, at_most=(what == 'flagged'))
            rows_b.append('| %s | %d/%d | %s %d/%d | %s | %s |' % (name, got, n, '<=' if what == 'flagged' else '>=', need, n,
                                                                  'PASS' if ok else 'FAIL', anchor))
        out += ['### %s' % ch, '', '| bar | got | need | | anchor |', '|---|---|---|---|---|'] + rows_b + ['']
    if write:
        write_plain(ctx.p('VERIFY_REPORT_v5x.md'), '\n'.join(out) + '\n')
        write_plain(ctx.p('VERIFY_DISAGREE_v5x.jsonl'), ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    return out, rows


def write_plain(path, txt):
    """The two report files are REWRITTEN from every verified group each time (as check_v5 --report does)."""
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(txt)


# ------------------------------------------------------------------ cleaning
def clean(ctx, chunk=None):
    st = stamps(ctx)
    vd, covered = verdicts(ctx, chunk)
    kept, dropped, pending = [], [], []
    for u in ctx.units():
        if chunk and u['chunk'] != chunk:
            continue
        s = st.get(u['uid'])
        if not s or s.get('status') != 'accepted':
            pending.append(u['uid'])
            continue
        if u['uid'] not in covered:
            pending.append(u['uid'])
            continue
        doc = C.load_json(ctx.p(s['file']))
        for it in doc['items']:
            d = vd.get(it['id'])
            if d is None or d['n'] == 0:
                pending.append(it['id'])
                continue
            form = u['forms'][cell_of(it['op'], it['shape'])]
            tags = sorted(d['tags'])
            if 'demoted' in tags and not it.get('signed'):
                tags.remove('demoted')
            if d['why']:
                dropped.append(dict(template=it['id'], lang=doc['language_code'], form=form, reasons=d['why']))
            else:
                kept.append(dict(lang=doc['language_code'], lead_in=doc['lead_in'], uid=doc['writer_unit'],
                                 slice=doc['slice'], template=it, tags=tags, q_form=form, chunk=u['chunk'],
                                 verifier=dict(tag='V5X', texts_read=d['n'], tags=tags)))
    return dict(bank='v5x', chunk=chunk or 'all', kept=kept, dropped=dropped, pending_units=pending)


def cmd_clean(ctx, chunk=None, out=None):
    res = clean(ctx, chunk)
    out = out or ctx.p('clean', 'clean_v5x_%s.json' % (chunk or 'all'))
    txt = dumps(res)
    write_once(out, txt)
    by = collections.defaultdict(collections.Counter)
    for e in res['kept']:
        by[e['lang']]['kept'] += 1
        by[e['lang']]['numdep'] += 'numdep' in e['tags']; by[e['lang']]['demoted'] += 'demoted' in e['tags']
    for e in res['dropped']:
        by[e['lang']]['dropped'] += 1
        by[e['lang']]['dropped_form'] += any('D5' in r for r in e['reasons'])
    lines = ['# BANK v5x cleaning (v5x.py clean%s)' % (' --chunk ' + chunk if chunk else ''), '',
             '| lang | kept | dropped | of which D5 form | numdep-tagged | demoted |', '|---|---|---|---|---|---|']
    for lang in sorted(by, key=lambda l: XL.LANGS.index(l) if l in XL.LANGS else 99):
        c = by[lang]
        lines.append('| %s | %d | %d | %d | %d | %d |' % (lang, c['kept'], c['dropped'], c['dropped_form'], c['numdep'], c['demoted']))
    lines += ['', 'kept %d, dropped %d, pending %d; md5 of %s: %s' % (len(res['kept']), len(res['dropped']),
                                                                      len(res['pending_units']), os.path.basename(out), C.md5_file(out))]
    write_once(os.path.splitext(out)[0] + '_NOTES.md', '\n'.join(lines) + '\n')
    print('\n'.join(lines))
    return 0


# ------------------------------------------------------------------ rows: gen_v5.build + the form rules
def _g():
    import gen_v5 as G   # imported late: it builds its value pools at import
    return G


def recompose(row, want, sep):
    """Move the question of one generated row to the front (want 'qfirst') or the back ('qlast'); numerals untouched."""
    q, lead, t = row['question'], row['answer_cue'], row['text']
    if row['qorder'] == want:
        return row
    if want == 'qfirst':
        tail = sep + q + sep + lead
        if not t.endswith(tail):
            raise Refused('%s: text does not end with its question + cue' % row['row_id'])
        new = q + sep + t[:-len(tail)] + sep + lead
    else:
        head, tail = q + sep, sep + lead
        if not (t.startswith(head) and t.endswith(tail)):
            raise Refused('%s: text does not start with its question' % row['row_id'])
        new = t[len(head):-len(tail)] + sep + q + sep + lead
    if C.RUNS.findall(new) != C.RUNS.findall(t):
        raise Refused('%s: recomposing moved a numeral' % row['row_id'])
    r = dict(row, text=new.rstrip(), qorder=want)
    for fld in ('row_id', 'pair_key'):
        parts = r[fld].split(':')
        if parts[5] != row['qorder']:
            raise Refused('%s: %s has no qorder field where expected' % (row['row_id'], fld))
        parts[5] = want
        r[fld] = ':'.join(parts)
    return r


def form_rows(rows, entries):
    fmap = {e['template']['id']: e for e in entries}
    out = []
    for r in rows:
        e = fmap[r['template_id']]
        form = e.get('q_form', 'F0')
        sep = '' if r['lang'] in C.NOSPACE else ' '
        want = 'qfirst' if form == 'F1' else ('qlast' if form in ('F6', 'F7') else r['qorder'])
        forced = want != r['qorder']
        r2 = recompose(r, want, sep)
        for fld in ('row_id', 'pair_key'):
            if not r2[fld].startswith('sg5:'):
                raise Refused('%s: unexpected id prefix' % r2[fld])
            r2[fld] = 'sg5x:' + r2[fld][4:]
        r2.update(source='signed_bank_v5x', bank_version='v5x', q_form=form, q_form_name=FORM_NAME[form],
                  qorder_forced=forced, chunk=e.get('chunk'))
        out.append(r2)
    ids = collections.Counter(r['row_id'] for r in out)
    if any(n > 1 for n in ids.values()):
        raise Refused('duplicate row ids after the form rules')
    return out


def build_rows(entries, numdep='keep'):
    G = _g()
    rows, tab, st = G.build(entries, numdep)
    return form_rows(rows, entries), tab, st


def cmd_gen(clean_path, out_dir, numdep='keep'):
    G = _g()
    ents = [dict(e, verified=True) for e in C.load_json(clean_path)['kept']]
    if not ents:
        print('no kept templates in %s' % clean_path)
        return 1
    rows, tab, st = build_rows(ents, numdep)
    rep, bad, low = G.audit(rows, st, 0)
    fc = collections.Counter((r['q_form'], r['qorder']) for r in rows)
    rep += ['FORMS (form, qorder) rows: %s' % dict(sorted(fc.items())),
            'FORMS templates: %s' % dict(sorted(collections.Counter(e['q_form'] for e in ents).items())),
            'STORY IDS %d..%d' % (min(r['story_id'] for r in rows), max(r['story_id'] for r in rows))]
    if os.path.exists(os.path.join(out_dir, 'signed_A_int.jsonl')):
        raise Refused('%s already holds a bank; name a new --out-dir' % out_dir)
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, 'signed_A_int.jsonl')
    with open(p, 'w', encoding='utf-8') as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    for n in ('signed_B_int.jsonl', 'signed_A_dec.jsonl', 'signed_B_dec.jsonl'):
        open(os.path.join(out_dir, n), 'w').close()
    with open(os.path.join(out_dir, 'pairs.json'), 'w', encoding='utf-8') as fh:
        json.dump(tab, fh, indent=0, sort_keys=True)
    with open(os.path.join(out_dir, 'AUDIT_v5x.txt'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(rep) + '\n')
    lines = ['%s  %s' % (C.md5_file(os.path.join(out_dir, n)), n) for n in ('signed_A_int.jsonl', 'pairs.json')]
    with open(os.path.join(out_dir, 'SHIP_V5X.raw.md5'), 'w') as fh:
        fh.write('\n'.join(lines) + '\n')
    print('\n'.join(rep)); print('\n'.join(lines))
    return 1 if bad else 0


# ------------------------------------------------------------------ scans
SKIP_PATH = re.compile(r'e2|gsm8k|key|redteam|withheld|blind|answers', re.I)
SID_RE = re.compile(rb'"story_id": ?(-?\d+)')


def idscan(root=ROLE):
    """{path: (n distinct, min, max)} of the numeric story ids in every *.jsonl under root (forbidden paths skipped)."""
    out = {}
    for dp, dn, fn in os.walk(root):
        if SKIP_PATH.search(dp):
            continue
        for f in fn:
            q = os.path.join(dp, f)
            if not f.endswith('.jsonl') or SKIP_PATH.search(q) or q.startswith(HERE):
                continue
            vals = set()
            with open(q, 'rb') as fh:
                for line in fh:
                    for m in SID_RE.findall(line):
                        vals.add(int(m))
            if vals:
                out[os.path.relpath(q, root)] = (len(vals), min(vals), max(vals), vals)
    return out


def digitscan():
    p = os.path.join(SIGNED, 'v3_61', 'signed_A_int.jsonl')
    n, bad = collections.Counter(), collections.Counter()
    with open(p, encoding='utf-8') as fh:
        for line in fh:
            r = json.loads(line)
            if r.get('lang') in XL.LANGS:
                n[r['lang']] += 1
                bad[r['lang']] += any(c.isdigit() and not c.isascii() for c in r['text'])
    for l in XL.LANGS:
        print('%s: %d/%d rows with a non-ASCII digit' % (l, bad[l], n[l]))
    return n, bad


# ------------------------------------------------------------------ status / next
def cmd_status(ctx, chunk=None):
    ws = {u['uid']: writer_state(ctx, u) for u in ctx.units() if not chunk or u['chunk'] == chunk}
    for ch in ctx.chunk_ids():
        if chunk and ch != chunk:
            continue
        us = chunk_units(ctx, ch)
        c = collections.Counter(ws[u['uid']][0] for u in us)
        print('%s  writer units %d: %s' % (ch, len(us), dict(sorted(c.items()))))
        for u in us:
            s, info = ws[u['uid']]
            if s != 'accepted':
                print('   %-16s %-8s %s' % (u['uid'], s, info.get('first_fail', '') or info.get('out', '')))
        for g in chunk_groups(ctx, ch):
            s, info = group_state(ctx, g, ws)
            print('   %-16s %-8s %d texts %s' % (g['uid'], s, g['texts'], json.dumps(info)))
    return 0


def cmd_next(ctx, uid=None, chunk=None):
    if uid:
        u = ctx.unit(uid)
        if u is None:
            print('NEXT REFUSED: no unit %s' % uid)
            return 1
        s, info = writer_state(ctx, u)
        if s in ('accepted', 'valid'):
            print('NEXT %s is %s: nothing to write' % (uid, s))
            return 1
        print(json.dumps(writer_spec(ctx, u, info), ensure_ascii=False, indent=1))
        return 0
    todo = [u['uid'] for u in ctx.units() if (not chunk or u['chunk'] == chunk)
            and writer_state(ctx, u)[0] in ('pending', 'invalid', 'rejected')]
    print('NEXT %s' % ' '.join(todo) if todo else 'NEXT none')
    return 0


# ------------------------------------------------------------------ selftest
def _en_forms(it, form):
    """A mechanical English rendering of a planted template in `form` (validator-level fixtures, not bank text)."""
    x = copy.deepcopy(it)
    q = x['question'].strip()
    body = q[:-1].rstrip() if q.endswith('?') else q
    low = body[0].lower() + body[1:]
    if form == 'F2':
        x['question'] = 'Work out the answer: %s.' % low
    elif form == 'F3':
        x['question'] = 'If nothing else was counted, %s?' % low
    elif form == 'F4':
        x['question'] = 'I would like to know the answer to this: %s.' % low
    elif form == 'F5':
        x['question'] = 'ok so quick one, %s?' % low
    elif form == 'F6':
        x['question'] = '%s: ___' % body
    elif form == 'F7':
        for k in ('facts_first', 'facts_second', 'base_first', 'base_second'):
            x[k] = 'Supervisor: ' + x[k]
        x['question'] = 'Visitor: ' + q
    return x


def fixture_units(forms_of, root):
    """Two planted English units (C.planted_unit 1, 2) as a one-chunk fixture manifest; forms_of(k) -> {cell: form}."""
    units, docs = [], {}
    for k in (1, 2):
        d, _ = C.planted_unit(k)
        fm = forms_of(k)
        u = unit_record('en', k, 'CX', langs=('en',), lead_in='The answer is', topics=list(C.PLANT_TOPICS),
                        slice_='SELFTEST', positions=C.fixture_positions(d), forms=fm)
        d['writer_unit'] = u['uid']; d['unit'] = u['unit']; d['slice'] = 'SELFTEST'
        d['items'] = [_en_forms(it, fm[cell_of(it['op'], it['shape'])]) for it in d['items']]
        for j, it in enumerate(d['items']):
            it['id'] = '%s-%02d' % (u['uid'], j + 1)
        units.append(u); docs[u['uid']] = d
    uidmap = {('en', u['k']): u['uid'] for u in units}
    groups = [dict(uid='V5X-C9-k12', chunk='CX', languages=['en'], ks=[1, 2], deps=[uidmap[('en', 1)], uidmap[('en', 2)]],
                   blind='blind/V5X-C9-k12.blind.json', key='blind_key/V5X-C9-k12.key.json', out='verify/V5X-C9-k12.json',
                   texts=2 * N_TEMPLATES * TEXTS_PER_TEMPLATE)]
    return Ctx(root, units, groups, clock=lambda: 'selftest'), docs


def selftest():
    ok = True
    n_chk, n_bad = [0], [0]

    def chk(name, cond):
        nonlocal ok
        n_chk[0] += 1
        n_bad[0] += not cond
        ok &= bool(cond)
        print('  %s  %s' % ('ok  ' if cond else 'FAIL', name))

    tmp_parent = os.path.join(HERE, '_selftest_tmp')
    os.makedirs(tmp_parent, exist_ok=True)
    before_pyc = set(glob.glob(os.path.join(V5, '__pycache__', '*'))) | set(glob.glob(os.path.join(HERE, '__pycache__', '*')))
    try:
        # (0) the language layer
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            lang_ok = XL.selftest()
        chk('v5x_lang selftest (%s)' % buf.getvalue().strip().splitlines()[-1], lang_ok)
        # (a) the real manifest, in memory
        units, groups = build_manifest()
        chk('144 writer units (36 x 4), 24 per chunk; 25 verifier units, 4 per chunk and 5 in C6',
            len(units) == 144 and all(sum(1 for u in units if u['chunk'] == c) == 24 for c, _, _ in XL.CHUNKS)
            and len(groups) == 25 and all(sum(1 for g in groups if g['chunk'] == c) == (5 if c == 'C6' else 4) for c, _, _ in XL.CHUNKS))
        chk('verifier units: C1-C5 6 languages x 1 unit number = 288 texts; C6 am si yo 288 x 2, km my 192 x 2, bo alone 192; 1,152 texts per chunk',
            all(g['texts'] == 288 and len(g['languages']) == 6 for g in groups if g['chunk'] != 'C6') and
            sorted((tuple(g['languages']), g['texts']) for g in groups if g['chunk'] == 'C6') ==
            [(('am', 'si', 'yo'), 288)] * 2 + [(('bo',), 192)] + [(('km', 'my'), 192)] * 2 and
            all(sum(g['texts'] for g in groups if g['chunk'] == c) == 1152 for c, _, _ in XL.CHUNKS))
        ctx_p = Ctx(HERE, units, groups)
        need, build_, skip = close_plan(ctx_p, 'C6', ('bo',))
        chk('close --defer bo on C6: needs the 20 other units, builds the 4 am/si/yo and km/my blind files, skips only V5X-C6c-k1234',
            len(need) == 20 and not any(u['lang'] == 'bo' for u in need) and len(build_) == 4 and [g['uid'] for g in skip] == ['V5X-C6c-k1234'])
        try:
            close_plan(ctx_p, 'C1', ('bo',)); refused = False
        except Refused:
            refused = True
        chk('close --defer refuses a language that is not in the chunk', refused)
        cover = collections.Counter(d for g in groups for d in g['deps'])
        chk('every writer unit sits in exactly one verifier unit, of its own chunk',
            set(cover) == set(u['uid'] for u in units) and set(cover.values()) == {1} and
            all(next(u for u in units if u['uid'] == d)['chunk'] == g['chunk'] for g in groups for d in g['deps']))
        chk('manifest deterministic', json.dumps(build_manifest()) == json.dumps((units, groups)))
        chk('every unit has a verified lead_in and language notes', all(u['lead_in'] and u['language_notes'] for u in units))
        per = collections.defaultdict(set)
        for u in units:
            per[u['lang']].add(u['slice'])
        chk('topics: the 4 units of a language take 4 different slices', all(len(s) == 4 for s in per.values()))
        hs = collections.Counter((u['slice'], u['half']) for u in units)
        chk('topics: all 48 half-slices used exactly 3 times', len(hs) == 48 and set(hs.values()) == {3})
        chk('{T} position: each unit 4 first / 4 middle / 4 last',
            all(sorted(collections.Counter(u['t_first_position'].values()).values()) == [4, 4, 4] for u in units))
        cp = collections.Counter((c, p) for u in units for c, p in u['t_first_position'].items())
        chk('{T} position: pooled (cell, position) %d..%d units' % (min(cp.values()), max(cp.values())),
            len(cp) == 36 and max(cp.values()) - min(cp.values()) <= 2)
        fl = collections.defaultdict(collections.Counter)
        for u in units:
            for c, f in u['forms'].items():
                fl[u['lang']][f] += 1
        chk('forms: every language uses each of the 8 forms exactly 6 times', all(set(c.values()) == {6} and len(c) == 8 for c in fl.values()))
        chk('forms: every unit uses all 8 forms', all(len(set(u['forms'].values())) == 8 for u in units))
        lc = collections.defaultdict(set)
        for u in units:
            for c, f in u['forms'].items():
                lc[(u['lang'], c)].add(f)
        chk('forms: every (language, op/shape cell) gets 4 distinct forms', all(len(s) == 4 for s in lc.values()))
        sh = collections.defaultdict(collections.Counter)
        opc = collections.defaultdict(collections.Counter)
        for u in units:
            for c, f in u['forms'].items():
                sh[(u['lang'], c.split('/')[1])][f] += 1; opc[(u['lang'], c.split('/')[0])][f] += 1
        chk('forms: per language, every shape holds each form exactly twice', all(set(c.values()) == {2} and len(c) == 8 for c in sh.values()))
        chk('forms: per language, every op holds each form once or twice', all(set(c.values()) <= {1, 2} and len(c) == 8 for c in opc.values()))
        pc = collections.Counter((c, f) for u in units for c, f in u['forms'].items())
        chk('forms: pooled, every (op/shape, form) cell holds exactly 18 templates', len(pc) == 96 and set(pc.values()) == {18})
        sids = [s for u in units for s in range(u['story_ids'][0], u['story_ids'][1] + 1)]
        chk('story ids: 1,728 distinct (%d..%d), as gen_v5 derives them from the uid' % (min(sids), max(sids)),
            len(set(sids)) == 1728 and all(story_ids(u['uid'])[0] == u['story_ids'][0] for u in units)
            and all(int(u['uid'].rsplit('u', 1)[1]) == u['unit'] for u in units))
        chk('story ids: disjoint from every pinned occupied range', not any(lo <= s <= hi for s in sids for lo, hi, _ in OCCUPIED))
        t0 = time.time()
        scan = idscan()
        live = set().union(*[v[3] for v in scan.values()]) if scan else set()
        chk('story ids: disjoint from the %d story ids in %d bank row files under _role/ (live scan, %.1f s; max %d)' % (
            len(live), len(scan), time.time() - t0, max(live) if live else 0), scan and not (set(sids) & live))
        chk('every live story id lies inside a pinned occupied range (the list is complete)',
            all(any(lo <= s <= hi for lo, hi, _ in OCCUPIED) for s in live))
        chk('unit ids never match the pinned W5 stamp glob (W5-<lang>-u*)', not any(re.match(r'^W5-', u['uid']) for u in units))
        # (b) validator: PASS fixtures for every (op, shape) cell in every form
        root = tempfile.mkdtemp(dir=tmp_parent)
        for f in FORM_CODES:
            ctx_f, docs = fixture_units(lambda k, f=f: {c: f for c in CELLS}, root)
            res = [(uid, validate_unit(d, ctx_f.unit(uid))) for uid, d in docs.items()]
            bad = [x for _, fs in res for x in fs]
            chk('PASS: form %s (%s) on all 12 (op, shape) cells x 2 planted units%s' % (f, FORM_NAME[f], (': ' + bad[0]) if bad else ''), not bad)
        mixed = lambda k: forms_for(0, k)
        ctx_m, docs_m = fixture_units(mixed, root)
        bad = [x for uid, d in docs_m.items() for x in validate_unit(d, ctx_m.unit(uid))]
        chk('PASS: the manifest form pattern (8 forms mixed in one unit) %s' % (bad[:1] or ''), not bad)
        bad = [x for uid, d in docs_m.items() for x in validate_unit(d, ctx_m.unit(uid), prior=C.prior_corpus('en', include_examples=False))]
        chk('PASS: mixed fixture against the real English prior corpora (verified en + v4wild)', not bad)
        # AB1 lesson: an F0 template written with 'Label: {M}' constructions is NOT an F7 violation
        d0 = copy.deepcopy(docs_m[ctx_m.units()[0]['uid']]); u0 = ctx_m.units()[0]
        j0 = next(j for j, it in enumerate(d0['items']) if u0['forms'][cell_of(it['op'], it['shape'])] == 'F0')
        d0['items'][j0]['facts_first'] = 'Report: ' + d0['items'][j0]['facts_first']
        chk('PASS: an F0 template opening with "Report:" (a label construction) is not judged as a dialogue',
            not validate_unit(d0, u0))
        ctx6, d6 = fixture_units(lambda k: {c: 'F6' for c in CELLS}, root)
        u6 = ctx6.units()[0]; x6 = copy.deepcopy(d6[u6['uid']])
        x6['items'][0]['question'] = 'This morning the packing hall sealed ___ cartons of soap and toothpaste in all.'
        chk('PASS: an F6 blank inside the sentence (verb-final languages put the verb or counter after it)', not validate_unit(x6, u6))
        chk('speaker labels: Tibetan (tsheg inside) and Amharic (wordspace inside) labels are read; a slash, slot or digit never is',
            speaker_label('བཀྲ་ཤིས: ཚོང་ཁང་') == 'བཀྲ་ཤིས' and speaker_label('ወ/ሮ ሰላም፦ ዛሬ') is None and
            speaker_label('አበበ፡ከበደ፦ ዛሬ') == 'አበበ፡ከበደ' and speaker_label('{M} boxes: many') is None and speaker_label('Clerk 2: x') is None)

        def mut(form, fn, want, name):
            ctx_x, dx = fixture_units(lambda k: {c: form for c in CELLS}, root)
            u = ctx_x.units()[0]
            d = copy.deepcopy(dx[u['uid']])
            fn(d['items'])
            f_ = validate_unit(d, u)
            tags = set(fail_tag(x) for x in f_)
            good = want in tags
            chk('FAIL as wanted [%s]: %s -> %s' % (want, name, sorted(tags) or 'clean'), good)

        mut('F0', lambda its: its[0].update(question=its[0]['question'][:-1] + '.'), 'form', 'F0 question ending in "."')
        mut('F2', lambda its: its[0].update(question='Work out how many cartons of soap and toothpaste the hall sealed?'), 'form', 'F2 instruction ending in "?"')
        mut('F6', lambda its: its[0].update(question='How many cartons of soap and toothpaste did it seal?'), 'form', 'F6 without a blank')
        mut('F6', lambda its: its[0].update(question='___ cartons were sealed: ___'), 'form', 'F6 with two blanks')
        mut('F0', lambda its: its[0].update(sem_sentence='A rival plant sealed ___ or {D} cartons of soap.'), 'form', 'a blank outside an F6 question')
        mut('F6', lambda its: its[0].update(question='Cartons of soap and toothpaste sealed this morning = ___'), 'symbol', 'F6 "= ___" (\'=\' stays refused)')
        mut('F7', lambda its: its[0].update(question='Supervisor: ' + its[0]['question'].split(': ', 1)[1]), 'form', 'F7 question by the same speaker')
        mut('F7', lambda its: its[0].update(question=its[0]['question'].split(': ', 1)[1]), 'form', 'F7 question without a label')
        mut('F7', lambda its: its[0].update(base_first=its[0]['base_first'].split(': ', 1)[1]), 'form', 'F7 base text without the label')
        mut('F7', lambda its: its[0].update(ex_sentence='Visitor: The packing hall is building {D}.'), 'form', 'F7 extra sentence with a label')
        mut('F1', lambda its: its[0].update(question='Tell me the total.'), 'form', 'F1 question that is not a question')
        mut('F5', lambda its: its[0].update(question=its[0]['question'] + ' \U0001F600'), 'char', 'an emoji in an F5 question')
        mut('F0', lambda its: its[0].update(facts_first=its[0]['facts_first'].replace('sealed', 'se\u202ealed', 1)), 'char', 'a bidi override')
        mut('F0', lambda its: its[2].update(question='How many bicycles did Line North assemble in two days?'), 'numberword', 'a pinned check still runs (number word)')
        mut('F0', lambda its: its[5].update(op='add'), 'quota', 'a pinned quota still runs')
        # the patched pinned modules see native full stops: an English unit written with Armenian full stops still
        # meets the split quota and the sentence-final check
        ctx_h, dh = fixture_units(lambda k: {c: 'F0' for c in CELLS}, root)
        u = ctx_h.units()[0]
        d = copy.deepcopy(dh[u['uid']])
        for it in d['items']:
            for key in ('facts_first', 'facts_second', 'base_first', 'base_second', 'ex_sentence', 'sem_sentence'):
                it[key] = it[key].replace('. ', '։ ').rstrip('.') + '։'
        chk('patched SENT_END inside the pinned validator: "։" counts as a sentence end and a split point',
            not validate_unit(d, u))
        shutil.rmtree(root)
        # (c) the pipeline on a fixture tree: write -> state -> close -> blind -> format -> report -> clean -> gen
        root = tempfile.mkdtemp(dir=tmp_parent)
        ctx, docs = fixture_units(mixed, root)
        for uid, d in docs.items():
            C.dump_json(ctx.p('writers', 'en', uid + '.json'), d)
        chk('states before close: valid, valid', [writer_state(ctx, u)[0] for u in ctx.units()] == ['valid', 'valid'])
        rc, lines = close_chunk(ctx, 'CX')
        chk('close: accepts both units and builds the blind file (%s)' % ' | '.join(lines), rc == 0 and
            any(l.startswith('BLIND ok 96 texts') for l in lines))
        rc2, lines2 = close_chunk(ctx, 'CX')
        chk('a second close is a no-op (same blind file, no new stamp)', rc2 == 0 and len(glob.glob(ctx.p('accept', '*'))) == 2)
        g = ctx.groups()[0]
        bl, key = C.load_json(ctx.p(g['blind'])), C.load_json(ctx.p(g['key']))
        chk('blind: 96 items with keys id / lang / form / text only; slots renamed {A} {B} {C}',
            len(bl['items']) == 96 and all(set(i) == {'id', 'lang', 'form', 'text'} for i in bl['items']) and
            all(sorted(C.placeholders(i['text'])) == ['A', 'B', 'C'] for i in bl['items']))
        f1 = [i for i in bl['items'] if i['form'] == 'F1']
        tq = {it['id']: it['question'] for d in docs.values() for it in d['items']}
        chk('blind: every F1 text starts with its question (%d), every other text ends with it' % len(f1),
            f1 and all(i['text'].startswith(tq[key[i['id']]['template']]) for i in f1) and
            all(i['text'].endswith(tq[key[i['id']]['template']]) for i in bl['items'] if i['form'] != 'F1'))
        chk('blind: the form label equals the manifest form of the template',
            all(key[i['id']]['form'] == ctx.unit(key[i['id']]['writer_unit'])['forms'][cell_of(key[i['id']]['op'], key[i['id']]['shape'])]
                for i in bl['items']))

        def perfect():
            items = []
            for i in bl['items']:
                e = K.expected(key[i['id']])
                items.append(dict(id=i['id'], op=e['op'], operands=list(e['operands']), role=e['role'],
                                  signed_natural=e['signed'], form_ok=True, flags=[], note=''))
            return dict(verifier_unit=g['uid'], items=items)
        p = perfect()
        chk('format: a perfect verify file passes', not fmt_fails(bl, p))
        bad_f = copy.deepcopy(p)
        bad_f['items'][0]['form_ok'] = None
        bad_f['items'][1]['form_ok'] = False
        del bad_f['items'][2]['form_ok']
        chk('format: form_ok null, false without a note, and missing are refused (%d)' % len(fmt_fails(bl, bad_f)), len(fmt_fails(bl, bad_f)) >= 3)
        C.dump_json(ctx.p(g['out']), p)
        chk('format_lines prints FORMAT ok 96', format_lines(ctx, g['uid'])[-1] == 'FORMAT ok 96')
        out, rows = report(ctx, write=False)
        chk('report: perfect -> 0 disagreement rows, all-three 96/96 in the language table',
            not rows and any(l.startswith('| en | 96 | 96/96 | 96/96 |') for l in out))
        res = clean(ctx)
        chk('clean: perfect keeps 24/24 with their forms', len(res['kept']) == 24 and not res['dropped'] and
            all(e['q_form'] == ctx.unit(e['uid'])['forms'][cell_of(e['template']['op'], e['template']['shape'])] for e in res['kept']))
        q = copy.deepcopy(p)
        i_form = 0
        tid_form = key[q['items'][i_form]['id']]['template']
        q['items'][i_form]['form_ok'] = False; q['items'][i_form]['note'] = 'reads as a plain question'
        i_nd = next(j for j, it in enumerate(q['items']) if key[it['id']]['template'] != tid_form)
        tid_nd = key[q['items'][i_nd]['id']]['template']
        q['items'][i_nd]['flags'] = ['number_dependent_grammar']; q['items'][i_nd]['note'] = 'case ending'
        i_role = next(j for j, it in enumerate(q['items']) if it['op'] in ('sub', 'div') and key[it['id']]['template'] not in (tid_form, tid_nd))
        tid_role = key[q['items'][i_role]['id']]['template']
        q['items'][i_role]['role'] = [x for x in q['items'][i_role]['operands'] if x != q['items'][i_role]['role']][0]
        C.dump_json(ctx.p('verify', g['uid'] + '.r1.json'), q)
        res = clean(ctx)
        kept = {e['template']['id']: e for e in res['kept']}
        chk('clean: form_ok false drops its template (D5)', tid_form not in kept and
            any(d['template'] == tid_form and any('D5' in r for r in d['reasons']) for d in res['dropped']))
        chk('clean: role miss drops (D1); numdep keeps + tags', tid_role not in kept and tid_nd in kept and 'numdep' in kept[tid_nd]['tags'])
        out, rows = report(ctx, write=False)
        chk('report: per-form table and form_ok 95/96 present', any('F0 plain' in l for l in out) and
            any(l.startswith('| en | 96 |') and '| 95/96 |' in l for l in out))
        # gen: the pinned build + the form rules
        G = _g()
        ents = [dict(e, verified=True) for e in clean(ctx)['kept']]
        raw, _, _ = G.build(ents)
        rows_x, tab, st = build_rows(ents)
        chk('gen: same number of rows as gen_v5.build (%d)' % len(raw), len(rows_x) == len(raw) > 0)
        same = all(set(r) - {'q_form', 'q_form_name', 'qorder_forced', 'chunk'} == set(o) and
                   all(r[k] == o[k] for k in o if k not in ('text', 'qorder', 'row_id', 'pair_key', 'source', 'bank_version'))
                   for r, o in zip(rows_x, raw))
        chk('gen: every other field of every row equals gen_v5.build\'s', same)
        unforced = [(r, o) for r, o in zip(rows_x, raw) if not r['qorder_forced']]
        chk('gen: rows the form rules leave alone are gen_v5.build\'s text byte for byte (%d rows)' % len(unforced),
            unforced and all(r['text'] == o['text'] and r['row_id'] == 'sg5x:' + o['row_id'][4:] for r, o in unforced))
        chk('gen: F1 rows all question-first, F6 / F7 rows all question-last',
            all(r['qorder'] == 'qfirst' and r['text'].startswith(r['question']) for r in rows_x if r['q_form'] == 'F1') and
            all(r['qorder'] == 'qlast' for r in rows_x if r['q_form'] in ('F6', 'F7')) and
            any(r['qorder_forced'] for r in rows_x if r['q_form'] == 'F1'))
        chk('gen: numerals, their order and the operand positions unchanged on every row',
            all(C.RUNS.findall(r['text']) == C.RUNS.findall(o['text']) and r['minuend_written_first'] == o['minuend_written_first']
                for r, o in zip(rows_x, raw)))
        bad_rows, _ = V.row_violations(rows_x)
        chk('gen: pinned row audit NONE on the v5x rows %s' % (dict(bad_rows) or ''), not bad_rows)
        chk('gen: every row records its form; ids sg5x:, source / version v5x',
            all(r['q_form'] in FORM_CODES and r['row_id'].startswith('sg5x:') and r['pair_key'].startswith('sg5x:') and
                r['bank_version'] == 'v5x' for r in rows_x))
        chk('gen: story ids are the manifest\'s', set(r['story_id'] for r in rows_x) <=
            set(s for u in ctx.units() for s in story_ids(u['uid'])))
        shutil.rmtree(root)
        # (d) a real-tree smoke: every manifest unit spec is printable and validation of a missing file fails cleanly
        ctx_r = Ctx(HERE, units, groups)
        sp = writer_spec(ctx_r, units[0], writer_state(ctx_r, units[0])[1]) if not os.path.exists(ctx_r.p(units[0]['output_file'])) else None
        chk('writer spec of %s carries 12 cells with forms, positions, notes and the output path' % units[0]['uid'],
            sp is None or (len(sp['cells']) == 12 and all('form' in c and 't_first_position' in c for c in sp['cells'])
                           and sp['output_path'].endswith('writers/%s/%s.json' % (units[0]['lang'], units[0]['uid']))))
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)      # only v5x/_selftest_tmp; nothing under v5/ is touched
    after_pyc = set(glob.glob(os.path.join(V5, '__pycache__', '*'))) | set(glob.glob(os.path.join(HERE, '__pycache__', '*')))
    chk('no __pycache__ written into v5/ or v5x/', after_pyc <= before_pyc)
    print('SELFTEST %s %d/%d' % ('PASS' if ok else 'FAIL', n_chk[0] - n_bad[0], n_chk[0]))
    return ok


# ------------------------------------------------------------------ CLI
def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['manifest', 'status', 'next', 'validate', 'close', 'blind', 'format', 'report',
                                    'clean', 'gen', 'idscan', 'digitscan', 'selftest'])
    ap.add_argument('args', nargs='*')
    ap.add_argument('--chunk', default=None)
    ap.add_argument('--out', default=None)
    ap.add_argument('--clean', default=None)
    ap.add_argument('--out-dir', default=None)
    ap.add_argument('--numdep', default='keep', choices=['keep', 'drop'])
    ap.add_argument('--defer', default='', help='close only: comma-separated language codes of the chunk to defer')
    a = ap.parse_args(argv[1:])
    ctx = Ctx()
    try:
        if a.cmd == 'selftest':
            return 0 if selftest() else 1
        if a.cmd == 'manifest':
            return cmd_manifest(ctx)
        if a.cmd == 'idscan':
            for q, (n, lo, hi, _) in sorted(idscan().items()):
                print('%-70s %5d ids %6d..%d' % (q, n, lo, hi))
            return 0
        if a.cmd == 'digitscan':
            digitscan()
            return 0
        if not ctx.units():
            print('no manifest: run python3 v5x.py manifest first')
            return 1
        if a.cmd == 'status':
            return cmd_status(ctx, a.chunk)
        if a.cmd == 'next':
            return cmd_next(ctx, a.args[0] if a.args else None, a.chunk)
        if a.cmd == 'validate':
            if len(a.args) != 1:
                print('usage: v5x.py validate <writer file>')
                return 2
            doc, fails = validate_path(ctx, os.path.abspath(a.args[0]))
            if fails:
                for f in fails:
                    print(f)
                print('VALIDATE FAIL %d problem(s) in %s' % (len(fails), a.args[0]))
                return 1
            print('VALIDATE ok %d' % len(doc['items']))
            return 0
        if a.cmd == 'close':
            rc, lines = close_chunk(ctx, a.args[0] if a.args else '', tuple(x for x in a.defer.split(',') if x))
            print('\n'.join(lines))
            return rc
        if a.cmd == 'blind':
            n, bp = write_blind(ctx, a.args[0])
            print('BLIND ok %d texts -> %s' % (n, bp))
            return 0
        if a.cmd == 'format':
            lines = format_lines(ctx, a.args[0], a.args[1] if len(a.args) > 1 else None)
            print('\n'.join(lines))
            return 0 if lines[-1].startswith('FORMAT ok') else 1
        if a.cmd == 'report':
            out, rows = report(ctx)
            print('\n'.join(out))
            print('disagreeing, flagged or form-failed texts: %d -> VERIFY_DISAGREE_v5x.jsonl' % len(rows))
            return 0
        if a.cmd == 'clean':
            return cmd_clean(ctx, a.chunk, a.out)
        if a.cmd == 'gen':
            if not a.clean or not a.out_dir:
                print('usage: v5x.py gen --clean <clean file> --out-dir <new directory>')
                return 2
            return cmd_gen(a.clean, a.out_dir, a.numdep)
    except Refused as e:
        print('REFUSED %s' % e)
        return 1
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
