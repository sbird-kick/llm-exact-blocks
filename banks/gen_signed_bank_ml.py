"""gen_signed_bank_ml.py [--src signed/verified] [--out-dir signed] [--seed 20260920] [--bank-version v3] [--langs ar,bn,...]
THE SIGNED-DOMAIN ROLE BANK generator. Reads the blind-verified templates (verified/<code>.verified.json; pass --src
writers to preview on unverified files) and writes FOUR eval-bank files in the schema the dumper, the finaliser
(finalise_role_bank_ml2.py) and the analysis already read:
    signed_A_int.jsonl   bank A (same-entity domains), integer fills        <- the primary bank
    signed_B_int.jsonl   bank B (relative domains, subject-confounded), integer fills, analysed separately
    signed_A_dec.jsonl / signed_B_dec.jsonl   decimal fills, ONLY for languages whose writer declared a "." decimal
                         separator and stories with decimals_natural; NOTE these need a float-aware finaliser
                         (block.digit_runs splits "7.5" into two runs), so they are emitted but not finalised here.

WHY THIS BANK (DESIGN_SIGNED_BANK.md §1): in every word-problem source we use, rows where the minuend is the smaller
number are <= 0.3%, so no bank drawn from them separates operand ROLE from MAGNITUDE. Here the minuend is fixed by the
MEANING of the story (the later reading, the amount had, the actual value, the strokes taken) and the two numbers are
filled BOTH ways, so within a minimal pair the words are identical and only which number is larger changes.

=====================================================================================================================
VERSION 2 (2026-09-21) -- THE DISTRACTOR LEAK FIX.  Bank v1 shipped with EIGHT hardcoded numeral pairs and a
five-value distractor pool from which `pick_distractor` returned the FIRST non-colliding entry, with no randomisation.
The distractor was therefore a deterministic pure function of the operand pair: seven of the eight pairs took 17, and
(3,7) took 1998 only because "7" is a substring of "17".  TWO distractor values reached the whole bank, one of them
perfectly confounded with one operand pair.  A per-run probe that memorises two numerals scores 5232/5232 on operand
selection, so no selection claim measured on v1 means anything.  v2 changes three things and nothing else:

  (1) NUMERALS ARE DRAWN PER STORY, not hardcoded.  The eight numeral CATEGORIES of v1 survive (they are the design:
      single digits, two-digit moderate, near-equal, digit swap, near-equal across a length boundary, extreme length
      gap, x10 look-alike, six digits) and `pair_id` still names the category, so every downstream filter keeps its
      meaning and `substring_pair` is still category 6.  Each category now holds a large candidate pool, seeded-shuffled
      once, and story N takes entry N of it -- up to 8 x 32 = 256 distinct pairs instead of 8.  The draw is keyed on
      STORY_ID ONLY, so two languages telling their story number 5 still fill it with the same numerals and a
      cross-language comparison is not confounded by the numbers, exactly as in v1.

  (2) THE DISTRACTOR IS DRAWN AT RANDOM FROM THE OPERAND VALUE UNIVERSE.  Not from a private pool: from the set of
      values that appear as OPERANDS elsewhere in the bank.  A probe cannot identify the distractor by recognising its
      value, because every value it could recognise is a gold operand somewhere else.  The draw is seeded on
      (lang, story, category, order, qorder, position, hardness) and deliberately NOT on `kind`, so the two halves of a
      minimal pair still carry the identical distractor and remain word-identical.

  (3) TWO DISTRACTOR HARDNESS LEVELS, both emitted (16 extra rows per story, 96 instead of 80):
        easy    -- the distractor has a DIFFERENT digit length from both operands (v1's regime, diversified).
                   Excluding it is a type check.
        matched -- the distractor has the SAME digit length as one of the two operands, drawn at random which.
                   Excluding it requires reading the story.  `dist_hardness` carries the label; `distractor_pos`
                   still carries dpre/dsuf so every existing filter on it is unchanged.
      Row ids and pair keys for the matched arm carry the tag `-dpreh` / `-dsufh`. In BOTH arms the distractor's
      RANK among the three numerals is balanced over the ranks the pair admits, so no fixed "the distractor is the
      largest" rule beats the 1-in-3 chance line.

`--bank-version v1` restores the old pairs and the old first-match distractor and reproduces the shipped bank
BYTE FOR BYTE (md5 b34f3e89eb7dac92c71b90a8058edebf for signed_A_int.jsonl); it exists so this rewrite can be proved
to have changed nothing else.  The generator prints a LEAK AUDIT at the end: on v1 a value-memorising probe identifies
the distractor on 100% of rows, and that number is what v2 must destroy.
=====================================================================================================================

VERSION 3 (2026-09-22) -- THE SEMANTIC DISTRACTOR.  v2's distractor sentence is the writer's exercise-number style
sentence: a numeral of a DIFFERENT KIND from the two quantities ("Exercise {D}"), so a text-only reader excludes it by its
wording or its type without reading the story (B1 within-language 91.2% on v2). v3 adds TWO more hardness arms and changes
nothing else about the rows that already exist:
        sem1  -- the sentence is distfact/<code>.json's `distractor_fact` for the story: a THIRD QUANTITY OF THE SAME KIND
                 AND UNIT as the two compared, owned by a different entity/place/instrument/series (pass 1, 25 languages).
        sem2  -- the sentence is distfact2/<code>.json's: a second such sentence whose OWNER IS OF A DIFFERENT KIND from
                 sem1's (pass 2, 21 languages at shipping), so no one wording per story can be learned.
      In both the value is drawn as in `matched` (the digit length of one of the two operands, rank-balanced, from the
      operand universe), because the text now carries the unit and the value must not give the distractor away either.
      The sem arms exist exactly where the easy/matched arms exist (same 4 categories, same dpre/dsuf placement, same
      `distractor_ok` gate, same qlast-only cell), keyed `-dpres1`/`-dsufs1`/`-dpres2`/`-dsufs2`, with `dist_hardness`
      sem1/sem2, `bank_version` v3 and the writer's `dist_gloss`/`dist_entity_note` carried on the row for judges.
      EVERY OTHER ROW IS BYTE-IDENTICAL TO v2 (bank_version v2, source signed_bank_ml_v2): the generator prints the md5
      of the non-sem subset of each file, which must equal the shipped v2 file. `--langs` restricts the languages so the
      v2 reproduction can be checked after `verified/` has grown (39 languages on 09-22, v2 shipped on 25).
      THE QUESTION v3 ASKS: does the text-only baseline fall to chance on the sem arms while R2 stays at the host's ceiling?
=====================================================================================================================

VERSION 4 (2026-09-22) -- THE WILD-STRUCTURE FIX.  Readers fitted on v2/v3 score 98-99% in-bank and far lower on real English
word problems with 3-5 numerals (a test set); the 09-22 diagnosis found that every transfer miss keeps one gold operand
and swaps the other for a LIST-MATE, because a wild row's extra numerals are a list of THREE SAME-KIND quantities from which the
QUESTION selects two, and because wild rows mix subtraction, addition and multiplication.  v2/v3 carry exactly ONE distractor, of
a DIFFERENT owner, excludable without reading the question, and subtraction only.  v4 attacks both halves and, again, changes
nothing about the rows that already exist:

  (A) THE MULTI-DISTRACTOR ARM (all 25 languages, no new writing).  Three new arms put TWO or THREE of the distractor sentences
      we already have into ONE row, so the row carries 4 or 5 numerals instead of 3:
        multi2a  exercise-number sentence + sem1      (dist_hardness `multi2`, tag -d*m2a)
        multi2b  sem1 + sem2                          (dist_hardness `multi2`, tag -d*m2b)
        multi3   exercise-number + sem1 + sem2        (dist_hardness `multi3`, tag -d*m3)
      Each sentence is placed independently BEFORE the facts, AFTER them, or BETWEEN them at a sentence boundary of the
      template that falls between {M} and {S} where one exists (17% of templates); the pattern is a seeded uniform draw over
      positions^k and is NOT keyed on `kind`, so the two halves of a minimal pair stay word-identical.  `distractor_pos` is
      `dmulti` (so every existing dpre/dsuf filter simply excludes these rows, which is the right behaviour), with the actual
      placements in `dist_positions` and the sentences in `dist_sentences`.  Every value is drawn exactly as `matched` (the
      digit length of one of the two operands, rank-balanced over low/mid/high, from the operand value universe), pairwise
      distinct and non-colliding with the operands and the answer.
  (B) THE WILD-STYLE ENGLISH TEMPLATES (writers_wild/en_wild.json, 40 new templates written for this bank, no wild row ever
      copied).  A template may declare `"extra_slots": ["T"]` -- a THIRD SAME-KIND QUANTITY inside the facts, owned by the same
      person or scene, which the QUESTION does not select ("9 in the morning, 10 in the afternoon and 7 in the evening. How many
      more in the morning than in the evening?") -- and `"op": "addition" | "product"` for the non-subtraction shapes.  {T} is
      filled like a `matched` distractor (rank-balanced, digit length of an operand, distinct from both and from the answer);
      `op` sets `wild_op` (aspread / asum / aprod), `commutative` and `ans` exactly as the wild-problem banks carry them.  Row ids
      take `--id-prefix sgw` so a wild-style bank can be concatenated with the main bank without a row_id collision.
  EVERY OTHER ROW IS BYTE-IDENTICAL: the generator prints the md5 of the non-multi subset of each file (must equal the shipped
  v3 file) and of the non-sem non-multi subset (must equal the shipped v2 file).
=====================================================================================================================

CELLS PER STORY (96 rows in v2, 80 in v1; v3 adds 16 per story that has both sem sentences): order {min_first, sub_first} x 8 numeral categories x kind {pos, neg} x
qorder {qlast, qfirst} = 64, plus distractor variants on 4 of the categories x kind x qlast x order x hardness = 32
(exercise-number style sentence BEFORE the facts for two categories, AFTER the facts for the other two). kind=pos:
M=big, S=small (answer positive); kind=neg: M=small, S=big (answer NEGATIVE). The MAGNITUDE rule is right on pos and
wrong on neg; the FIRST-WRITTEN rule is right on min_first and wrong on sub_first; the SUBJECT rule is undefined on
bank A (one entity owns both numbers) and 100% on bank B by construction. All three are printed as exact counts.

TEXT = [distractor] facts [distractor] question lead_in   (qlast)   |   question [distractor] facts [distractor] lead_in (qfirst)
joined with a single space, or with nothing for ja/zh (no inter-sentence spaces in those scripts). The lead_in is the
writer's native "The answer is"; NOTHING English is appended (the doubled-cue lesson of 09-18).
`prov.gold_run_idx` is left for the finaliser to fill with block.digit_runs on the cluster."""
import argparse, collections, glob, hashlib, json, os, random, re, unicodedata

RUNS = re.compile(r'[0-9]+')
HERE = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser()
ap.add_argument('--src', default=os.path.join(HERE, 'verified'))
ap.add_argument('--out-dir', default=HERE)
ap.add_argument('--suffix', default='.verified.json', help='use ".json" with --src writers to preview on unverified files')
ap.add_argument('--seed', type=int, default=20260920)
ap.add_argument('--bank-version', default='v2', choices=['v1', 'v2', 'v3', 'v4'],
                help='v1 reproduces the shipped v1 bank byte for byte (8 hardcoded pairs, first-match distractor); v3 = v2 + the sem1/sem2 arms; '
                     'v4 = v3 + the multi-distractor arms + the {T} extra slot and the addition/product templates')
ap.add_argument('--id-prefix', default='sg', help="row_id / pair_key prefix; use 'sgw' for a wild-style bank so it can be concatenated with the main one")
ap.add_argument('--langs', default='', help='comma-separated language codes to include (default: every file under --src)')
ap.add_argument('--distfact', default=os.path.join(HERE, 'distfact'), help='pass-1 semantic distractor sentences (v3 sem1)')
ap.add_argument('--distfact2', default=os.path.join(HERE, 'distfact2'), help='pass-2 semantic distractor sentences (v3 sem2)')
ap.add_argument('--pairs-out', default=None, help='write the story -> numeral-pair table here (v2 only)')
a = ap.parse_args()
V2 = a.bank_version in ('v2', 'v3', 'v4'); V3 = a.bank_version in ('v3', 'v4'); V4 = (a.bank_version == 'v4'); SEM = ('sem1', 'sem2')

# v4's multi-distractor arms: arm name -> (the sentences it carries, the row_id tag, the dist_hardness label)
MULTI = (('multi2a', ('ex', 'sem1'), 'm2a', 'multi2'),
         ('multi2b', ('sem1', 'sem2'), 'm2b', 'multi2'),
         ('multi3', ('ex', 'sem1', 'sem2'), 'm3', 'multi3'))
MULTI_BY_NAME = {m[0]: m for m in MULTI}
SENT_END = re.compile(r'[.!?。！？؟।]')   # strong sentence enders only; a semicolon clause break reads badly with a whole sentence dropped into it

INT_PAIRS_V1 = [(7, 3), (49, 29), (51, 49), (94, 49), (1001, 999), (4870, 3), (1240, 124), (250000, 180000)]
DEC_PAIRS_V1 = [(7.5, 2.5), (10.25, 9.75)]
DIST_POOL_V1 = [17, 1998, 12, 2025, 6]
DIST_PAIR_IDX = {0: 'dpre', 2: 'dsuf', 4: 'dpre', 6: 'dsuf'}      # which categories get a distractor variant, and where
NOSPACE = {'ja', 'zh'}
MAX_STORY_ID = 64                 # the pair table is built for this many slots regardless of how many stories exist
HARDNESS = (('easy', 'matched') + (SEM if V3 else ()) + (tuple(m[0] for m in MULTI) if V4 else ())) if V2 else (None,)
TAG = {None: '', 'easy': '', 'matched': 'h', 'sem1': 's1', 'sem2': 's2'}   # row_id / pair_key suffix per hardness arm
TAG.update({m[0]: m[2] for m in MULTI})
OPS = {'subtraction': 'aspread', 'addition': 'asum', 'product': 'aprod'}


def apply_op(op, m, s):
    return (m - s) if op == 'subtraction' else ((m + s) if op == 'addition' else (m * s))


def fmt(v):
    return str(v) if isinstance(v, int) else ('%g' % v)


def rng(*parts):
    """A deterministic Random keyed on the parts and on --seed. Python's hash() is salted per process, so the key
    goes through blake2b instead: the bank must be reproducible on any machine, which is the whole point."""
    h = hashlib.blake2b(('|'.join(str(p) for p in parts)).encode('utf-8'), digest_size=8).digest()
    return random.Random(int.from_bytes(h, 'big') ^ (a.seed & 0xFFFFFFFFFFFFFFFF))


# ---------------------------------------------------------------- the eight numeral categories

def _ok(big, small, allow_substring=False):
    """Every constraint the row-level refusals would otherwise catch, applied at pool-construction time so that a bad
    pair costs a candidate rather than a dropped row (a dropped row widows its minimal pair and both are lost)."""
    if small <= 0 or big <= small: return False
    d = big - small
    if d == big or d == small: return False                    # the answer must not be written in the prompt
    sb, ss, sd = str(big), str(small), str(d)
    if not allow_substring and (ss in sb or sb in ss): return False
    if sd == sb or sd == ss: return False
    return True


def _cat_pools():
    """Candidate pools, one per category. Deliberately generated rather than listed: the v1 pairs are members of their
    own categories, so nothing about the design changes, only how many numerals instantiate it."""
    c = [[] for _ in range(8)]
    for big in range(2, 10):                                              # 0 single digits
        for small in range(1, big):
            if _ok(big, small): c[0].append((big, small))
    for big in range(30, 100):                                            # 1 two-digit, clear gap
        for small in range(11, big - 9):
            if _ok(big, small): c[1].append((big, small))
    for big in range(14, 100):                                            # 2 near-equal two-digit
        for small in range(big - 3, big):
            if small >= 11 and _ok(big, small): c[2].append((big, small))
    for x in range(2, 10):                                                # 3 digit swap
        for y in range(1, x):
            big, small = 10 * x + y, 10 * y + x
            if _ok(big, small): c[3].append((big, small))
    for big in range(1000, 1013):                                         # 4 near-equal across a length boundary
        for small in range(988, 1000):
            if _ok(big, small): c[4].append((big, small))
    for big in range(1000, 10000):                                        # 5 extreme length gap
        for small in range(2, 10):
            if _ok(big, small): c[5].append((big, small))
    for small in range(102, 990):                                         # 6 x10 look-alike (substring_pair)
        if small % 10 == 0: continue
        for r in range(10):
            big = small * 10 + r
            if _ok(big, small, allow_substring=True): c[6].append((big, small))
    for k in range(11, 100):                                              # 7 six digits
        for j in range(10, k):
            big, small = k * 10000, j * 10000
            if _ok(big, small): c[7].append((big, small))
    return c


def _dec_ok(big, small):
    """The decimal rows locate their operands with text.find, so a formatted operand must not be a substring of the
    other ("2.5" sits inside "12.5" and the first-written label silently flips). v1's two hand-picked pairs happened
    to satisfy this; a generated pool has to be told."""
    if small <= 0 or big <= small: return False
    sb, ss, sd = fmt(big), fmt(small), fmt(round(big - small, 4))
    if ss in sb or sb in ss: return False
    if sd == sb or sd == ss or sd in sb or sd in ss: return False
    return True


def _dec_pools():
    c = [[], []]
    for whole in range(2, 40):                                            # 0 halves, one decimal place
        for sm in range(1, whole):
            big, small = whole + 0.5, sm + 0.5
            if _dec_ok(big, small): c[0].append((big, small))
    for b in range(1000, 4000, 25):                                       # 1 near-equal, two decimal places
        for gap in (25, 50, 75):
            big, small = round(b / 100.0, 2), round((b - gap) / 100.0, 2)
            if _dec_ok(big, small): c[1].append((big, small))
    return c


def _table(pools, tag):
    """category -> [pair for story 1, pair for story 2, ...]. A seeded shuffle then position, so the pairs a story
    gets are stable, distinct across stories wherever the pool allows it, and identical in every language."""
    t = []
    for ci, pool in enumerate(pools):
        pool = sorted(pool)
        r = rng(tag, 'category', ci); r.shuffle(pool)
        t.append([pool[(sid - 1) % len(pool)] for sid in range(1, MAX_STORY_ID + 1)])
    return t


INT_TABLE = _table(_cat_pools(), 'int') if V2 else None
DEC_TABLE = _table(_dec_pools(), 'dec') if V2 else None


def pairs_for(sid, fill):
    if not V2: return INT_PAIRS_V1 if fill == 'int' else DEC_PAIRS_V1
    t = INT_TABLE if fill == 'int' else DEC_TABLE
    return [col[(sid - 1) % MAX_STORY_ID] for col in t]


# ---------------------------------------------------------------- the distractor

def pick_distractor_v1(mn, sb):
    vals = {fmt(mn), fmt(sb), fmt(abs(mn - sb))}
    for d in DIST_POOL_V1:
        sd = str(d)
        if any(sd in v or v in sd for v in vals): continue
        return d
    raise RuntimeError('no distractor for %r %r' % (mn, sb))


def _clean(d, mn, sb, ansv=None):
    """The v1 non-collision rule, kept verbatim: the distractor must not share a digit-substring with either operand
    or with the answer, so the three numerals in the prompt stay unambiguous for the digit-run locator.
    `ansv` overrides the answer for the non-subtraction operators of v4; left None it is |mn - sb| exactly as in v1/v2/v3."""
    sd = str(d); ansv = abs(mn - sb) if ansv is None else ansv
    return not any(sd in v or v in sd for v in (fmt(mn), fmt(sb), fmt(ansv)))


def pick_distractor_v2(mn, sb, universe_by_len, key):
    """Draw from the OPERAND value universe. `matched` (and v3's `sem1`/`sem2`) takes the digit length of one of the two
    operands (so the distractor cannot be spotted by size); `easy` takes any other available length (so excluding it is a type check).
    Both are values that are gold operands somewhere else in the bank, which is what kills the memorisation shortcut.

    Then BALANCE THE RANK. A value drawn freely lands outside the operand interval almost always -- the near-equal
    categories have nothing between them -- so `the distractor is the largest of the three` would beat the 1-in-3
    chance line without reading a word. The three ranks are tried in a seeded random order and the first feasible one
    is taken, which is uniform over whichever ranks the pair admits."""
    hard = key[-1]
    lm, ls = len(fmt(mn)), len(fmt(sb))
    lo, hi = min(mn, sb), max(mn, sb)
    r = rng(*key)
    if hard != 'easy':
        # sorted() so the two halves of a minimal pair agree: mn and sb swap with `kind`, and an unsorted [lm, ls]
        # hands the same permutation a different input. The distractor must be IDENTICAL within a minimal pair.
        lens = sorted({lm, ls})
    else:
        lens = [L for L in sorted(universe_by_len) if L not in (lm, ls) and L <= 4]
    cand = [d for L in lens for d in universe_by_len.get(L, ()) if _clean(d, mn, sb)]
    if not cand: return None
    rank = {'low': [d for d in cand if d < lo], 'mid': [d for d in cand if lo < d < hi], 'high': [d for d in cand if d > hi]}
    order = ['low', 'mid', 'high']; r.shuffle(order)
    for p in order:
        if rank[p]: return r.choice(sorted(rank[p]))
    return None


def unique_pair(op, mn, sb, extras):
    """Is the gold pair the ONLY pair of the row's numerals that realises the row's answer? On subtraction three numerals
    7, 9, 5 with the answer 2 admit both 7-5 and 9-7, and a reader that picked the second would look right; host_selection.py
    calls those rows collisions and throws them away. v4 refuses to write them in the first place (the v2/v3 draw is left
    exactly as it was, so the shipped banks stay byte-identical and keep whatever collisions they already had)."""
    vals = [mn, sb] + list(extras); want = apply_op(op, mn, sb)
    hits = sum(1 for i in range(len(vals)) for j in range(len(vals)) if i != j and apply_op(op, vals[i], vals[j]) == want)
    return hits == (1 if op == 'subtraction' else 2)      # a commutative operator counts the gold pair in both orders


def pick_matched_v4(mn, sb, universe_by_len, key, extras, ansv, op):
    """v4's draw for ONE extra numeral -- a multi-arm distractor sentence's value, or a wild template's {T}. Identical in
    spirit to `matched`: the digit length of one of the two operands, drawn from the operand value universe, rank-balanced
    over whichever of low / mid / high the pair admits; additionally distinct from every value already placed in the row,
    and refused if it would give the row a second pair realising the answer. A separate function so that the v2/v3 code
    path is untouched byte for byte."""
    lo, hi = min(mn, sb), max(mn, sb)
    r = rng(*key)
    taken = {mn, sb} | set(extras)
    lens = sorted({len(fmt(mn)), len(fmt(sb))})
    cand = [d for L in lens for d in universe_by_len.get(L, ())
            if _clean(d, mn, sb, ansv) and d not in taken and unique_pair(op, mn, sb, list(extras) + [d])]
    if not cand: return None
    rank = {'low': [d for d in cand if d < lo], 'mid': [d for d in cand if lo < d < hi], 'high': [d for d in cand if d > hi]}
    order = ['low', 'mid', 'high']; r.shuffle(order)
    for p in order:
        if rank[p]: return r.choice(sorted(rank[p]))
    return None


def split_points(tpl):
    """Character offsets in a FACTS TEMPLATE at which a distractor sentence may be inserted BETWEEN the two facts: the end of
    a sentence-final punctuation run that lies strictly between {M} and {S}. Computed on the template, never on the filled
    text, so the two halves of a minimal pair split at the same place however long their numerals are."""
    i, j = tpl.find('{M}'), tpl.find('{S}')
    if i < 0 or j < 0: return []
    lo, hi = min(i, j) + 3, max(i, j)
    out = []
    for m in SENT_END.finditer(tpl, lo, hi):
        k = m.end()
        while k < len(tpl) and tpl[k] in '  \t': k += 1
        if lo < k < hi: out.append(k)
    return out


rows = {k: [] for k in ('A_int', 'B_int', 'A_dec', 'B_dec')}
refused = collections.Counter(); per_lang = collections.Counter(); stories_used = collections.Counter()
files = sorted(glob.glob(os.path.join(a.src, '*' + a.suffix)))
docs = [json.load(open(f, encoding='utf-8')) for f in files]
if a.langs:
    keep = set(a.langs.split(',')); docs = [d for d in docs if d['language_code'] in keep]
    missing = keep - {d['language_code'] for d in docs}
    if missing: raise SystemExit('--langs names languages with no verified file: %s' % sorted(missing))
    print("languages restricted by --langs to %d: %s" % (len(docs), sorted(d['language_code'] for d in docs)))

# v3: the semantic distractor sentences, (arm, lang, story_id) -> the writer's item. Validated here again (one {D}, no digit
# in any script) so a bad file costs a refusal at generation time and never a malformed row.
SEMFACT = {}
if V3:
    for arm, dd in (('sem1', a.distfact), ('sem2', a.distfact2)):
        for f in sorted(glob.glob(os.path.join(dd, '*.json'))):
            sd = json.load(open(f, encoding='utf-8'))
            for it in sd['items']:
                t = it['distractor_fact']
                if t.count('{D}') != 1 or any(unicodedata.category(ch) == 'Nd' for ch in t):
                    raise SystemExit('bad %s sentence %s story %s: %r' % (arm, sd['language_code'], it['story_id'], t))
                SEMFACT[(arm, sd['language_code'], it['story_id'])] = it
    print("semantic distractor sentences loaded: sem1 %d, sem2 %d" % (sum(1 for k in SEMFACT if k[0] == 'sem1'), sum(1 for k in SEMFACT if k[0] == 'sem2')))
sem_missing = set()

# the operand value universe: every integer that is a gold operand in some row of this bank, bucketed by digit length
universe_by_len = collections.defaultdict(set)
if V2:
    for d in docs:
        for it in d['items']:
            for big, small in pairs_for(it['story_id'], 'int'):
                universe_by_len[len(str(big))].add(big); universe_by_len[len(str(small))].add(small)
    universe_by_len = {L: sorted(v) for L, v in universe_by_len.items()}

dist_audit = []
for d in docs:
    lang = d['language_code']; lead = d['lead_in'].strip(); dec_ok_lang = d.get('decimal_separator') == '.'
    sep = '' if lang in NOSPACE else ' '
    for it in d['items']:
        bank = it['bank']; sid = it['story_id']; dom = it['domain'].replace('_', ' ')
        q = it['question'].strip(); dist_tpl = it['distractor_sentence'].strip()
        op = it.get('op', 'subtraction')                      # v4: the template's operator; everything before v4 is subtraction
        if op not in OPS: raise SystemExit('story %s/%s: unknown op %r' % (lang, sid, op))
        extraT = V4 and ('T' in (it.get('extra_slots') or []))
        dec_pairs = pairs_for(sid, 'dec') if (dec_ok_lang and it.get('decimals_natural')) else []
        for fill, pairs in (('int', pairs_for(sid, 'int')), ('dec', dec_pairs)):
            for pid, (big, small) in enumerate(pairs):
                for order in ('min_first', 'sub_first'):
                    facts_tpl = it['facts_min_first' if order == 'min_first' else 'facts_sub_first'].strip()
                    variants = [('qlast', None, None), ('qfirst', None, None)]
                    if fill == 'int' and pid in DIST_PAIR_IDX and it.get('distractor_ok', True):
                        for hard in HARDNESS:
                            need = MULTI_BY_NAME[hard][1] if hard in MULTI_BY_NAME else ((hard,) if hard in SEM else ())
                            gap = [s for s in need if s in SEM and (s, lang, sid) not in SEMFACT]
                            if gap: sem_missing.update((s, lang, sid) for s in gap); continue
                            variants.append(('qlast', 'dmulti' if hard in MULTI_BY_NAME else DIST_PAIR_IDX[pid], hard))
                    for qorder, dpos, hard in variants:
                        for kind in ('pos', 'neg'):
                            mn, sb = (big, small) if kind == 'pos' else (small, big)
                            ansv = apply_op(op, mn, sb) if fill == 'int' else round(apply_op(op, mn, sb), 4)
                            leakv = abs(ansv) if op == 'subtraction' else ansv   # what must not appear in the prompt
                            ftpl = facts_tpl
                            ds = []; places = []; sents = ()
                            if extraT:
                                # the wild-style third same-kind quantity, inside the facts, chosen by the writer's {T}
                                tv = pick_matched_v4(mn, sb, universe_by_len, (lang, sid, pid, order, qorder, 'T'), (), leakv, op)
                                if tv is None: refused['no_T:%s' % lang] += 1; continue
                                ftpl = ftpl.replace('{T}', fmt(tv)); ds = [tv]
                            filled = lambda t: t.replace('{M}', fmt(mn)).replace('{S}', fmt(sb))
                            facts = filled(ftpl)
                            if dpos == 'dmulti':
                                sents = MULTI_BY_NAME[hard][1]
                                dvals = []
                                for si_, s in enumerate(sents):
                                    dv = pick_matched_v4(mn, sb, universe_by_len, (lang, sid, pid, order, qorder, 'multi', hard, si_), dvals, leakv, op)
                                    if dv is None: break
                                    dvals.append(dv)
                                if len(dvals) != len(sents): refused['no_multi_distractor:%s' % lang] += 1; continue
                                stpl = [dist_tpl if s == 'ex' else SEMFACT[(s, lang, sid)]['distractor_fact'].strip() for s in sents]
                                sp = split_points(ftpl)
                                opts = ['pre', 'suf'] + (['mid'] if sp else [])
                                rp = rng(lang, sid, pid, order, qorder, 'multipos', hard)   # NOT keyed on kind
                                places = [rp.choice(opts) for _ in sents]
                                parts = {'pre': [], 'mid': [], 'suf': []}
                                for s_i in range(len(sents)): parts[places[s_i]].append(stpl[s_i].replace('{D}', str(dvals[s_i])))
                                if parts['mid']:
                                    kk = sp[0]; core = filled(ftpl[:kk].rstrip()) + sep + sep.join(parts['mid']) + sep + filled(ftpl[kk:].lstrip())
                                else:
                                    core = facts
                                facts = sep.join(parts['pre'] + [core] + parts['suf'])
                                ds = [dvals[i] for p in ('pre', 'mid', 'suf') for i in range(len(sents)) if places[i] == p]
                            elif dpos:
                                if V2:
                                    # NOT keyed on kind: both halves of the minimal pair take the same distractor
                                    dv = pick_distractor_v2(mn, sb, universe_by_len, (lang, sid, pid, order, qorder, dpos, hard))
                                    if dv is None: refused['no_distractor:%s' % lang] += 1; continue
                                else:
                                    dv = pick_distractor_v1(mn, sb)
                                ds = [dv]
                                tpl = SEMFACT[(hard, lang, sid)]['distractor_fact'].strip() if hard in SEM else dist_tpl
                                dsent = tpl.replace('{D}', str(dv))
                                facts = (dsent + sep + facts) if dpos == 'dpre' else (facts + sep + dsent)
                            text = (facts + sep + q + sep + lead) if qorder == 'qlast' else (q + sep + facts + sep + lead)
                            text = text.rstrip()
                            vals = RUNS.findall(text)
                            if fill == 'int':
                                ivals = [int(v) for v in vals]
                                if ivals.count(mn) != 1 or ivals.count(sb) != 1: refused['operand_not_unique:%s' % lang] += 1; continue
                                if leakv in ivals: refused['answer_leak:%s' % lang] += 1; continue
                                if len(ivals) != 2 + len(ds): refused['stray_digits:%s' % lang] += 1; continue
                                mfirst = ivals.index(mn) < ivals.index(sb)
                            else:
                                mfirst = text.find(fmt(mn)) < text.find(fmt(sb))
                            tag = '' if not dpos else '-' + dpos + TAG[hard]
                            key = '%s_%s' % (bank, fill)
                            ver = ('v4' if (hard in MULTI_BY_NAME or extraT) else      # non-multi rows stay byte-identical to v3,
                                   ('v3' if hard in SEM else ('v2' if V2 else 'v1')))  # non-sem rows byte-identical to v2
                            row = dict(
                                row_id="%s:%s:%s:%d:%s:%s:%s-%d%s" % (a.id_prefix, lang, bank, sid, order, qorder, kind, pid, tag),
                                pair_key="%s%s:%s:%d:%s:%s:%d%s" % ('' if a.id_prefix == 'sg' else a.id_prefix + ':', lang, bank, sid, order, qorder, pid, tag),
                                status="scored", wild_op=OPS[op], lang=lang, stratum="signed", bank=bank, domain=dom,
                                kind=kind, variant=order, qorder=qorder, order_kind=kind, fill=fill, pair_id=pid,
                                has_distractor=bool(dpos) or bool(extraT), distractor_pos=dpos, substring_pair=(fill == 'int' and pid == 6),
                                source="signed_bank_ml_%s" % ver, text=text, list_values=[mn, sb] + ds, op=op,
                                a=mn, b=sb, ans=ansv, commutative=(op != 'subtraction'), ka=0, kb=0, kans=0, ds=ds,
                                stated_answer=None, answer_correct=None, answer_in_text=False, cut=True, slot_mode="whole",
                                selection_eligible=True, headline_eligible=(bank == 'A'), completion_valid=True,
                                minuend_is_larger=(kind == 'pos'), minuend_written_first=mfirst,
                                n_numerals_written=len(vals), answer_cue=lead, story_id=sid, unit=it.get('unit'),
                                sign_convention=it.get('sign_convention'), question=q, frame_gloss=it.get('gloss_en'),
                                verifier=it.get('verifier'),
                                prov=dict(locator="block.digit_runs (filled by the finaliser on the cluster)", gold_run_idx=None),
                            )
                            if V2: row['dist_hardness'] = hard; row['bank_version'] = ver
                            if hard in SEM:
                                sf = SEMFACT[(hard, lang, sid)]; row['dist_gloss'] = sf.get('gloss_en'); row['dist_entity_note'] = sf.get('entity_note')
                            if hard in MULTI_BY_NAME:
                                row['dist_hardness'] = MULTI_BY_NAME[hard][3]     # multi2 / multi3; dist_arm keeps the exact combination
                                row['dist_arm'] = hard; row['dist_sentences'] = list(sents); row['dist_positions'] = places
                                row['dist_glosses'] = [None if s == 'ex' else SEMFACT[(s, lang, sid)].get('gloss_en') for s in sents]
                            if extraT:
                                row['dist_hardness'] = 'wildT'; row['dist_arm'] = 'wildT'; row['extra_slots'] = ['T']
                                row['wild_shape'] = it.get('wild_shape'); row['dist_entity_note'] = it.get('extra_note')
                            rows[key].append(row)
                            if (dpos or extraT) and fill == 'int':
                                for dv_ in ds:
                                    dist_audit.append((dv_, (big, small), row['dist_hardness'], key))
                            per_lang['%s/%s' % (key, lang)] += 1
        stories_used['%s/%s' % (bank, lang)] += 1

os.makedirs(a.out_dir, exist_ok=True)
for key, rs in rows.items():
    p = os.path.join(a.out_dir, 'signed_%s.jsonl' % key)
    with open(p, 'w', encoding='utf-8') as fh:
        for r in rs: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    n = len(rs)
    print("== %s: %d rows -> %s" % (key, n, p))
    if not n: continue
    langs = sorted(set(r['lang'] for r in rs)); pos = sum(1 for r in rs if r['kind'] == 'pos')
    mf = sum(1 for r in rs if r['minuend_written_first']); dist = sum(1 for r in rs if r['has_distractor'])
    qf = sum(1 for r in rs if r['qorder'] == 'qfirst'); doms = collections.Counter(r['domain'] for r in rs)
    print("   languages %d %s" % (len(langs), langs))
    print("   stories %d, minimal pairs %d, distractor rows %d/%d, qfirst %d/%d, domains %s" %
          (len(set((r['lang'], r['story_id']) for r in rs)), sum(1 for c in collections.Counter(r['pair_key'] for r in rs).values() if c == 2), dist, n, qf, n, dict(doms)))
    if V2 and dist:
        hh = collections.Counter(r['dist_hardness'] for r in rs if r['has_distractor'])
        print("   distractor hardness %s" % dict(hh))
    if V4:
        print("   numerals per row %s; op %s; wild_op %s" % (dict(sorted(collections.Counter(r['n_numerals_written'] for r in rs).items())),
                                                             dict(collections.Counter(r['op'] for r in rs)), dict(collections.Counter(r['wild_op'] for r in rs))))
        arms = collections.Counter(r.get('dist_arm') for r in rs if r.get('dist_arm'))
        if arms:
            print("   v4 arms %s" % dict(arms))
            pp = collections.Counter(tuple(r['dist_positions']) for r in rs if r.get('dist_positions'))
            print("   multi placements %s" % {'+'.join(k): v for k, v in sorted(pp.items())})
    print("   EXACT BASELINES: magnitude rule right on pos %d/%d and neg 0/%d (overall %d/%d); first-written rule right on %d/%d "
          "(min_first %d/%d, sub_first 0/%d); subject rule %s." %
          (pos, pos, n - pos, pos, n, mf, n, mf, mf, n - mf, "UNDEFINED (one entity owns both numbers)" if key.startswith('A') else "100%% BY CONSTRUCTION (%d/%d) -- analyse separately" % (n, n)))
print("stories used per bank/language:", dict(sorted(stories_used.items())))
print("refusals:", dict(refused) or 'none')
if V4:
    MULTIH = ('multi2', 'multi3')
    for key in ('A_int', 'B_int'):
        rs = rows[key]
        nm = ''.join(json.dumps(r, ensure_ascii=False) + "\n" for r in rs if r.get('dist_hardness') not in MULTIH)
        print("v4 %s: NON-MULTI SUBSET md5 %s over %d rows (must equal the shipped v3 signed_%s.jsonl); multi rows %d (%s)" %
              (key, hashlib.md5(nm.encode('utf-8')).hexdigest(), sum(1 for r in rs if r.get('dist_hardness') not in MULTIH), key,
               sum(1 for r in rs if r.get('dist_hardness') in MULTIH),
               dict(collections.Counter(r.get('dist_arm') for r in rs if r.get('dist_hardness') in MULTIH))))
        bylang = collections.Counter((r['dist_arm'], r['lang']) for r in rs if r.get('dist_hardness') in MULTIH)
        for arm, _, _, _ in MULTI: print("   %s rows per language: %s" % (arm, dict(sorted((l, n) for (h, l), n in bylang.items() if h == arm))))
if V3:
    for key in ('A_int', 'B_int'):
        rs = rows[key]
        sub = ''.join(json.dumps(r, ensure_ascii=False) + "\n" for r in rs
                      if r.get('dist_hardness') not in SEM and r.get('dist_hardness') not in ('multi2', 'multi3'))
        print("v3 %s: NON-SEM SUBSET md5 %s over %d rows (must equal the shipped v2 signed_%s.jsonl); sem rows %d (sem1 %d, sem2 %d)" %
              (key, hashlib.md5(sub.encode('utf-8')).hexdigest(), sub.count("\n"), key,
               sum(1 for r in rs if r.get('dist_hardness') in SEM), sum(1 for r in rs if r.get('dist_hardness') == 'sem1'), sum(1 for r in rs if r.get('dist_hardness') == 'sem2')))
        bylang = collections.Counter((r['dist_hardness'], r['lang']) for r in rs if r.get('dist_hardness') in SEM)
        for arm in SEM: print("   %s rows per language: %s" % (arm, dict(sorted((l, n) for (h, l), n in bylang.items() if h == arm))))
    miss = collections.Counter((h, l) for h, l, _ in sem_missing)
    print("stories WITHOUT a sem sentence (arm, lang) -> stories:", dict(sorted(miss.items())) or 'none')

# ---------------------------------------------------------------- numerals + the leak audit
if V2:
    used = sorted(set((r['lang'], r['story_id']) for rs in rows.values() for r in rs))
    sids = sorted(set(s for _, s in used))
    allp = collections.defaultdict(set)
    for _, s in used:
        for pid, pr in enumerate(pairs_for(s, 'int')): allp[pid].add(pr)
    print("numeral pairs int: %d distinct over %d story slots; per category %s" %
          (sum(len(v) for v in allp.values()), len(sids), {k: len(v) for k, v in sorted(allp.items())}))
    for pid in sorted(allp): print("   cat %d: %s%s" % (pid, sorted(allp[pid])[:6], ' ...' if len(allp[pid]) > 6 else ''))
    if a.pairs_out:
        json.dump({str(s): pairs_for(s, 'int') for s in sids}, open(a.pairs_out, 'w'), indent=1)
        print("   story -> pair table written to", a.pairs_out)
else:
    print("numeral pairs int:", INT_PAIRS_V1, " dec:", DEC_PAIRS_V1)

if dist_audit:
    D = set(d for d, _, _, _ in dist_audit)
    O = set(v for rs in rows.values() for r in rs for v in (r['a'], r['b']) if isinstance(v, int))
    memorisable = sum(1 for d, _, _, _ in dist_audit if d not in O)
    bypair = collections.defaultdict(set)
    for d, pr, _, _ in dist_audit: bypair[d].add(pr)
    identifies = sum(1 for d, _, _, _ in dist_audit if len(bypair[d]) == 1)
    print("LEAK AUDIT over %d integer distractor rows" % len(dist_audit))
    print("   distinct distractor values %d; distinct operand values %d; distractor values that are NEVER an operand %d"
          % (len(D), len(O), len(D - O)))
    print("   rows whose distractor can be spotted BY VALUE ALONE (value never used as an operand): %d/%d (%.1f%%)"
          % (memorisable, len(dist_audit), 100.0 * memorisable / len(dist_audit)))
    print("   rows whose OPERAND PAIR is uniquely determined by the distractor value: %d/%d (%.1f%%)"
          % (identifies, len(dist_audit), 100.0 * identifies / len(dist_audit)))
    if V4:
        print("   per arm (one line per distractor VALUE placed, so a multi3 row contributes three):")
        for h in sorted(set(h for _, _, h, _ in dist_audit), key=str):
            g = [(d, pr) for d, pr, hh, _ in dist_audit if hh == h]
            mem = sum(1 for d, _ in g if d not in O)
            uniq = sum(1 for d, _ in g if len(bypair[d]) == 1)
            print("      %-8s values placed %6d, distinct %4d, never-an-operand %d (%.1f%%), pair-identifying %d (%.1f%%)"
                  % (h, len(g), len(set(d for d, _ in g)), mem, 100.0 * mem / len(g), uniq, 100.0 * uniq / len(g)))
        multi_rows = [r for rs in rows.values() for r in rs if r.get('dist_hardness') in ('multi2', 'multi3')]
        if multi_rows:
            nd = collections.Counter(len(r['ds']) for r in multi_rows)
            allv = sum(1 for r in multi_rows if len(set(r['ds'])) == len(r['ds']))
            print("   multi rows %d; distractors per row %s; rows whose distractor values are pairwise distinct %d/%d"
                  % (len(multi_rows), dict(sorted(nd.items())), allv, len(multi_rows)))
