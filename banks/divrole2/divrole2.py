"""divrole2.py -- the bigger, blind-verified division role bank (DR-ROLE's design, PREREG_divrole.md 0965080c, grown the
way subrole/ grew subtraction). stdlib only. Port of subrole/subrole.py (3fb169ad), with the division choices of
divrole/gen_divrole.py (0617b0d2).

{M} = the DIVIDEND (the amount that is divided), {S} = the DIVISOR, fixed by the template's words, never by size.
Each template has two written orders: `first` (M before S) and `second` (S before M), plus one `question`.
The answer is ALWAYS M / S, an exact fraction; when M < S it is a proper fraction (3/8), so every template must read
naturally with a fractional answer (3/8 of a litre each is fine, 3/8 of a bus is not).

Template sources (the `template_source` of every bank row; every table is reported by source):
  written  new templates from Sonnet writers, 12 per unit, one per division frame (FRAMES below), 16 units
  v5       the English v5 division templates that v5's blind verification kept (v5/clean/clean_v5_r1-16.json, op div),
           MINUS the 4 that DR-ROLE kept (those sit in drrole): 36 templates. DR-ROLE's Sonnet audit dropped all 36
           for "sensible fraction"; re-verified blind here as a calibration of the blind rubric.
  drrole   the 20 templates of the DR-ROLE bank (divrole/audit_verdicts.json keep == true: 16 digits-prose dp01-dp16
           + 4 v5), re-verified blind here. DRROLE_MODE (decision D-DR) says whether the kept ones enter the
           template-grouped folds ('bank') or stay a held-out REFERENCE scored only by the final frozen reader
           ('reference', fold = -1).

Commands
  python3 divrole2.py manifest                 # deterministic: units, chunks, seeds (refuses to move a unit once written)
  python3 divrole2.py status [--next]          # every unit / group / clean from the files on disk; --next = the next args
  python3 divrole2.py next <U>                 # the writer's unit spec (JSON): cells, output_path, attempt
  python3 divrole2.py validate <path>          # the writer's deterministic validator; ends "VALIDATE ok 12" or FAIL lines
  python3 divrole2.py close <C>                # accept every unit of chunk C, build the chunk's blind + key files
  python3 divrole2.py format <G> [<out>]       # the verifier's format gate (knows no labels)
  python3 divrole2.py clean <C>                # deterministic keep / drop per template from the blind verdicts; GO bar
  python3 divrole2.py gen [--out bank]         # the bank from every clean kept template (gen_divrole.py ported)
  python3 divrole2.py selftest                 # every check seen passing AND failing, per frame cell
"""
import sys
sys.dont_write_bytecode = True
import argparse, glob, hashlib, json, math, os, random, re, shutil, tempfile
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
SIGNED = os.path.dirname(HERE)
SEED = 'divrole2-2026-10-01'
CUE = 'The answer is'
V5_CLEAN = os.path.join(SIGNED, 'v5', 'clean', 'clean_v5_r1-16.json')
DR_CAND = os.path.join(SIGNED, 'divrole', 'templates_candidates.json')
DR_VERD = os.path.join(SIGNED, 'divrole', 'audit_verdicts.json')
INPUT_MD5 = {V5_CLEAN: 'e92b1741ff7d4cac752f18bf033f60e9', DR_CAND: '50573de4298894534756f4da9d8c7134',
             DR_VERD: 'c5c48ac2ac9e1d740b734b6743fe4ef3'}       # read, never edited
FORBID = ['/v5e2/', 'svamp', 'singleeq', 'gsm8k', 'key.json', 'key_withheld', 'answers_withheld', 'haiku_ab', 'redteam',
          'wildtest', 'wildeval']
N_PER_UNIT = 12
LO, HI = 2, 99                 # DR-ROLE's number range
TARGET_ROWS = 3000             # DR-ROLE's target; pairs per template = max(8, min(60, round(TARGET / (4 K_bank))))
NEAR_DUP = 0.45                # char-4-gram Jaccard at or above this = near duplicate (v5_common.NEAR_DUP)
GO_FRAC = 0.50                 # a chunk is GO iff kept(written) >= 50% of its written templates (PLAN.md section 5)
GO_MIN_TOTAL = 25              # and the pilot's total kept IN THE BANK (fold sources) >= 25 (5 per fold)
DRROLE_MODE = 'reference'      # decision D-DR (PREREG_divrole2.md): 'reference' (recommended) or 'bank'; set before gen
SOURCES = ('v5', 'drrole', 'written')

FRAMES = [
    ('D01', 'a sum of money (a bill, a fee, a prize, a fund) split equally among people; the dividend is the MONEY, the '
            'divisor is the NUMBER OF PEOPLE sharing it (each person\'s share = money divided by people)',
     ['restaurant bill', 'taxi fare', 'quiz prize', 'cabin rental', 'gift for a teacher', 'band gig fee',
      'office coffee fund', 'lottery syndicate', 'boat hire', 'pizza order', 'tip jar', 'allotment fee',
      'coach hire', 'rowing club grant', 'electricity bill', 'museum trip cost']),
    ('D02', 'an amount of food or material, measured in a unit (kilograms, litres, cups, metres), shared equally among '
            'people, animals or plants; the dividend is the AMOUNT, the divisor is the NUMBER OF RECIPIENTS (amount '
            'each one gets)',
     ['hay for horses', 'rice for families', 'fertiliser for rose bushes', 'cheese for picnic guests', 'clay for pupils',
      'yarn for knitters', 'water for camels', 'honey for neighbours', 'oats for goats', 'soil for seedlings',
      'milk for kittens', 'chocolate for children', 'paint for art students', 'grain for hens', 'sand for builders',
      'wax for candle makers']),
    ('D03', 'an amount (litres, kilograms, cups) poured or packed equally into containers; the dividend is the AMOUNT, '
            'the divisor is the NUMBER OF CONTAINERS (amount in each container)',
     ['soup into bowls', 'lemonade into glasses', 'sand into buckets', 'olive oil into bottles', 'paint into trays',
      'rice into jars', 'coffee into flasks', 'compost into pots', 'jam into jars', 'water into troughs',
      'flour into tins', 'juice into cups', 'birdseed into feeders', 'tea into teapots', 'syrup into jugs',
      'dog food into bowls']),
    ('D04', 'a length (or area) of material cut into equal pieces; the dividend is the LENGTH, the divisor is the NUMBER '
            'OF PIECES (size of each piece)',
     ['fabric roll', 'timber plank', 'garden hose', 'ribbon', 'copper pipe', 'fence wire', 'paper strip', 'cake slab',
      'carpet roll', 'licorice lace', 'curtain rail', 'climbing rope', 'chain', 'bamboo pole', 'sausage',
      'string of lights']),
    ('D05', 'a distance travelled in an amount of time; the dividend is the DISTANCE, the divisor is the TIME (distance '
            'per unit of time; the question must say "per hour" / "per minute", never the other way round)',
     ['snail', 'cyclist', 'glacier', 'sailing boat', 'tortoise', 'hiker', 'train', 'canoe', 'hot-air balloon',
      'jogger', 'tram', 'horse and cart', 'river barge', 'ice skater', 'delivery drone', 'garden slug']),
    ('D06', 'an amount produced, moved or filled in an amount of time; the dividend is the AMOUNT, the divisor is the '
            'TIME (amount per unit of time)',
     ['water pump', 'leaking tap', 'cider press', 'ice-cream machine', 'paper mill', 'snow cannon', 'honey extractor',
      'concrete mixer', 'yarn spinner', 'grain conveyor', 'fountain', 'olive press', 'sawmill', 'maple syrup tap',
      'rain gutter', 'fuel pump']),
    ('D07', 'a total cost paid for a quantity measured in a unit (kilograms, metres, litres, hours); the dividend is the '
            'COST, the divisor is the QUANTITY bought (price per unit)',
     ['cheese', 'apples', 'fabric', 'petrol', 'coffee beans', 'garden soil', 'rope', 'paint', 'grapes', 'olive oil',
      'gravel', 'wool', 'carpet', 'honey', 'firewood', 'parking']),
    ('D08', 'what was achieved (distance driven, area covered) using an amount of a resource (litres of fuel, cans of '
            'paint, bags of seed); the dividend is what was ACHIEVED, the divisor is the RESOURCE used (achieved per '
            'unit of resource)',
     ['delivery van fuel', 'motorboat fuel', 'paint on a fence', 'lawn seed', 'tractor diesel', 'floor varnish',
      'scooter battery', 'wallpaper paste', 'moped fuel', 'snow plough diesel', 'road paint', 'fertiliser on a field',
      'tile grout', 'lawnmower petrol', 'camper van fuel', 'wood stain on decking']),
    ('D09', 'an amount of one substance mixed into, or spread over, an amount of another (grams of salt in litres of '
            'water, kilograms of seed over square metres); the dividend is the SUBSTANCE, the divisor is the amount of '
            'the MEDIUM or AREA (substance per unit)',
     ['salt in soup', 'sugar in lemonade', 'dye in a vat', 'chlorine in a pool', 'seed on a field',
      'plant food in a tank', 'cocoa in milk', 'gravel on a path', 'mulch on a flower bed', 'yeast in dough',
      'spice in a sauce', 'lime on a meadow', 'grit on an icy road', 'tea leaves in a pot', 'soap in a bucket',
      'wax on a floor']),
    ('D10', 'a total amount gathered over several days, games or trips; the dividend is the TOTAL amount, the divisor is '
            'the NUMBER of days, games or trips (average per day / game / trip)',
     ['rainfall', 'milk from a dairy', 'goals in a season', 'running distance', 'snowfall', 'honey harvest',
      'fish caught', 'hours of sunshine', 'bakery flour use', 'library visits', 'electricity use', 'bus fuel',
      'apple harvest', 'study hours', 'swimming distance', 'tomato crop']),
    ('D11', 'money earned for an amount of time or work; the dividend is the MONEY earned, the divisor is the HOURS (or '
            'the units of work done) (pay per hour / per unit)',
     ['babysitter', 'gardener', 'tutor', 'dog walker', 'piano teacher', 'lifeguard', 'cafe worker', 'window cleaner',
      'translator', 'courier', 'street musician', 'house painter', 'lab assistant', 'farmhand', 'cleaner', 'referee']),
    ('D12', 'an amount of an ingredient used for a number of servings, portions or helpings; the dividend is the AMOUNT '
            'of the ingredient, the divisor is the NUMBER OF SERVINGS (amount per serving)',
     ['porridge oats', 'pancake flour', 'fruit salad', 'curry rice', 'smoothie yoghurt', 'pasta', 'trail mix nuts',
      'pizza cheese', 'lemonade sugar', 'hot cocoa powder', 'stew beef', 'muffin butter', 'salad dressing oil',
      'lentil soup', 'chilli beans', 'cake icing']),
]
FRAME_IDS = [f for f, _, _ in FRAMES]
# chunks: P1 = the pilot (4 writer units + the 36 v5 seeds + the 20 DR-ROLE templates, 104 templates = 416 blind texts,
# 4 verifier groups of 26); G1, G2 = growth (6 units = 72 templates = 288 texts each, 3 groups of 24), only after P1 is GO
CHUNKS = {
    'P1': dict(units=[f'DR2-u{u:02d}' for u in range(1, 5)], groups=['DR2V-p1a', 'DR2V-p1b', 'DR2V-p1c', 'DR2V-p1d'],
               seeds=True),
    'G1': dict(units=[f'DR2-u{u:02d}' for u in range(5, 11)], groups=['DR2V-g1a', 'DR2V-g1b', 'DR2V-g1c'], seeds=False),
    'G2': dict(units=[f'DR2-u{u:02d}' for u in range(11, 17)], groups=['DR2V-g2a', 'DR2V-g2b', 'DR2V-g2c'], seeds=False),
}
SEED_FILES = {'v5': 'seeds/v5_div_en.json', 'drrole': 'seeds/drrole_20.json'}
NUMBER_WORDS = ('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen '
                'seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred hundreds '
                'thousand thousands million millions billion dozen dozens half halves twice thrice double triple '
                'quadruple single couple pair pairs once first second third fourth fifth sixth seventh eighth ninth '
                'tenth eleventh twelfth quarter quarters thirds fourths fifths sixths sevenths eighths ninths tenths '
                'percent').split()     # subrole.NUMBER_WORDS + the fraction words (a fraction word is a hidden operand)
BANNED_Q = [(r'\bhow (?:many|much) (?:more|fewer|less)\b', 'how many more / fewer (a subtraction comparison)'),
            (r'\bdifference\b', 'difference (subtraction)'),
            (r'\bleft\b|\bleftover\b|\bremain', 'left / remain (a remainder, or subtraction)'),
            (r'\bwhole\b|\bfull\b|\bcomplete\b|\bcompletely\b|\bentire\b', 'whole / full (forces a whole-number answer)'),
            (r'\baltogether\b|\bin total\b|\btotal\b|\bin all\b|\bcombined\b', 'a total (reads as addition or multiplication)'),
            (r'\bratio\b', 'ratio (undirected)'), (r'\bhow many times\b', 'how many times (a comparison, not a share)'),
            (r'\bround\b|\brounded\b|\bnearest\b', 'rounding'), (r'\bper ?cent\b', 'percent')]
DIV_CUE = r'\beach\b|\bper\b|\bevery\b|\baverage\b|\bapiece\b'     # the question must name the share / the rate
VFLAGS = ('unnatural', 'ungrammatical', 'ambiguous', 'hidden_operand', 'another_pair_answers', 'integer_only',
          'cue_mismatch', 'number_dependent_grammar', 'not_single_step', 'role_only_in_question', 'other')
VBLOCK = ('unnatural', 'ungrammatical', 'ambiguous', 'hidden_operand', 'another_pair_answers', 'integer_only',
          'cue_mismatch', 'number_dependent_grammar', 'not_single_step')   # role_only_in_question + other: recorded only
VOPS = ('add', 'sub', 'mul', 'div', 'other')


def P(*a):
    print(*a, flush=True)


def md5f(p):
    return hashlib.md5(open(p, 'rb').read()).hexdigest()


def md5b(b):
    return hashlib.md5(b).hexdigest()


def refuse_forbidden(p):
    low = os.path.abspath(p).lower()
    for f in FORBID:
        if f in low:
            sys.exit(f"REFUSE: forbidden path {p} ({f})")


def dumpj(obj, path):
    b = (json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'wb').write(b)
    return md5b(b)


def loadj(p):
    return json.load(open(p, encoding='utf-8'))


def fstr(f):
    f = Fraction(f)
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


class Ctx:
    def __init__(self, root):
        self.root = root

    def p(self, *a):
        return os.path.join(self.root, *a)


def unit_index(uid):
    return int(uid.split('-u')[1])


def chunk_of(uid):
    return [c for c, d in CHUNKS.items() if uid in d['units']][0]


def fold_sources():
    return ('v5', 'drrole', 'written') if DRROLE_MODE == 'bank' else ('v5', 'written')


# ------------------------------------------------------------------------------------------------- manifest
def unit_spec(uid):
    k = unit_index(uid) - 1
    cells = [dict(cell=i + 1, frame=f, frame_desc=d, topic=tops[k % len(tops)]) for i, (f, d, tops) in enumerate(FRAMES)]
    return dict(unit_id=uid, chunk=chunk_of(uid), n_templates=N_PER_UNIT, cells=cells,
                tid_pattern=f"{uid}-NN (NN = cell number 01..12)")


def check_inputs():
    for p, m in INPUT_MD5.items():
        refuse_forbidden(p)
        if md5f(p) != m:
            sys.exit(f"REFUSE: {p} md5 {md5f(p)} != pinned {m}")


def extract_seeds():
    """(v5 seeds minus DR-ROLE's, DR-ROLE's 20), both sorted by tid"""
    check_inputs()
    C = {c['tid']: c for c in loadj(DR_CAND)}
    V = {v['tid']: v for v in loadj(DR_VERD)['verdicts']}
    dr_ids = sorted(t for t, v in V.items() if v['keep'] is True and v['natural'] is True and v['sensible_fraction'] is True
                    and v['dividend_unambiguous'] is True)
    dr = [dict(tid=t, source='drrole', frame='drrole', topic=C[t]['topic'], first=C[t]['first'], second=C[t]['second'],
               question=C[t]['question'], quotient_convention='', fraction_reading='', div_mode=C[t]['div_mode'],
               origin=C[t]['source']) for t in dr_ids]
    v5 = []
    for k in loadj(V5_CLEAN)['kept']:
        t = k['template']
        if k['lang'] == 'en' and t['op'] == 'div' and t['id'] not in dr_ids:
            v5.append(dict(tid=t['id'], source='v5', frame='v5', topic=t.get('topic', ''), first=t['base_first'],
                           second=t['base_second'], question=t['question'], quotient_convention='', fraction_reading='',
                           div_mode=t.get('div_mode', ''), origin='v5'))
    return sorted(v5, key=lambda s: s['tid']), dr


def cmd_manifest(ctx):
    idx_p = ctx.p('manifest', 'MANIFEST_INDEX.json')
    v5, dr = extract_seeds()
    sm = {}
    for src, L in (('v5', v5), ('drrole', dr)):
        srcfile = V5_CLEAN if src == 'v5' else DR_VERD
        sm[src] = dumpj(dict(source=os.path.relpath(srcfile, SIGNED), source_md5=md5f(srcfile), n=len(L), seeds=L),
                        ctx.p(SEED_FILES[src]))
    units = {}
    for C, d in CHUNKS.items():
        for u in d['units']:
            units[u] = dumpj(unit_spec(u), ctx.p('manifest', 'units', f'{u}.json'))
    idx = dict(seed=SEED, chunks=CHUNKS, n_per_unit=N_PER_UNIT, frames=FRAME_IDS, seed_files=SEED_FILES, seeds_md5=sm,
               seeds_n=dict(v5=len(v5), drrole=len(dr)), inputs_md5={os.path.relpath(p, SIGNED): m for p, m in INPUT_MD5.items()},
               units_md5=units, go_bar=dict(go_frac=GO_FRAC, go_min_total=GO_MIN_TOTAL))
    if os.path.exists(idx_p) and loadj(idx_p) != idx:
        sys.exit('REFUSE: manifest/MANIFEST_INDEX.json exists with different content (units are frozen once written)')
    m = dumpj(idx, idx_p)
    return idx, m


def all_seeds(ctx):
    out = []
    for src in ('v5', 'drrole'):
        p = ctx.p(SEED_FILES[src])
        if os.path.exists(p):
            out += loadj(p)['seeds']
    return out


# ------------------------------------------------------------------------------------------------- validator
def words(t):
    return re.findall(r"[a-z]+(?:'[a-z]+)?", t.lower())


def grams(t, n=4):
    s = re.sub(r'\s+', ' ', re.sub(r'\{[MS]\}', '#', t.lower())).strip()
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def jacc(a, b):
    return len(a & b) / max(1, len(a | b))


def both_grams(t):
    return grams(t['first'] + ' ' + t['question']), grams(t['second'] + ' ' + t['question'])


def near(ga, gb):
    """near duplicate on EITHER written order (first + question, or second + question): the gen fold rule"""
    return max(jacc(ga[0], gb[0]), jacc(ga[1], gb[1]))


def item_problems(it, cell=None, uid=None):
    """deterministic checks of one template; returns [(code, message)]"""
    p = []
    need = ('tid', 'frame', 'topic', 'first', 'second', 'question', 'quotient_convention', 'fraction_reading')
    miss = [f for f in need if not isinstance(it.get(f), str) or not it.get(f).strip()]
    if miss:
        return [('schema', f'missing or empty fields {miss}')]
    extra = sorted(set(it) - set(need) - {'notes'})
    if extra:
        p.append(('schema', f'unknown fields {extra}'))
    if cell is not None:
        if it['tid'] != f"{uid}-{cell['cell']:02d}":
            p.append(('schema', f"tid must be {uid}-{cell['cell']:02d}"))
        if it['frame'] != cell['frame'] or it['topic'] != cell['topic']:
            p.append(('cell', f"frame / topic must be exactly {cell['frame']!r} / {cell['topic']!r}"))
    for key, a, b in (('first', '{M}', '{S}'), ('second', '{S}', '{M}')):
        t = it[key]
        if t.count('{M}') != 1 or t.count('{S}') != 1:
            p.append(('slots', f'{key} needs exactly one {{M}} and one {{S}}'))
        elif t.index(a) > t.index(b):
            p.append(('order', f'{key} must write {a} before {b}'))
        if re.search(r'\{(?![MS]\})', t) or re.search(r'(?<!\{[MS])\}', t):
            p.append(('slots', f'{key} has a brace that is not {{M}} or {{S}}'))
        if re.search(r'\b(?:a|an)\s+\{[MS]\}', t, re.I):
            p.append(('article', f'{key}: never write "a" or "an" before a slot (it fits only some numbers)'))
    q = it['question']
    if '{' in q or '}' in q:
        p.append(('slots', 'the question must not contain a slot or a brace'))
    full = ' '.join((it['first'], it['second'], q))
    if re.search(r'\d', full) or re.search(r'[+\-*/=%×÷−]\s*\{', full):
        p.append(('digit', 'no digits and no arithmetic symbols anywhere'))
    low = full.lower()
    nw = sorted({w for w in NUMBER_WORDS if re.search(r"(?<![\w'’])%s(?![\w'’])" % re.escape(w), low)})
    if nw:
        p.append(('numberword', f'number or fraction words give hidden operands: {", ".join(nw)}'))
    if CUE.lower() in low:
        p.append(('cue', 'do not write the cue "The answer is"; the generator adds it'))
    if '\n' in full or '  ' in full:
        p.append(('format', 'no line breaks or double spaces'))
    if not q.rstrip().endswith('?'):
        p.append(('question', 'the question must end with "?"'))
    for rx, why in BANNED_Q:
        if re.search(rx, q.lower()):
            p.append(('banned', f'question: {why}'))
    if not re.search(DIV_CUE, q.lower()):
        p.append(('divcue', 'the question must name the share or the rate: "each", "per", "every", "average" or "apiece"'))
    for key, cap in (('first', 45), ('second', 45), ('question', 30)):
        if len(words(it[key])) > cap:
            p.append(('length', f'{key} has {len(words(it[key]))} words (cap {cap})'))
    w1 = {w for w in words(it['first']) if len(w) >= 3}
    w2 = {w for w in words(it['second']) if len(w) >= 3}
    if jacc(w1, w2) < 0.6:
        p.append(('reorder', f'second must reorder first, not rewrite it (content-word overlap {jacc(w1, w2):.2f} < 0.60)'))
    if 'divided by' not in it['quotient_convention'].lower():
        p.append(('quotient', 'quotient_convention must say "<dividend thing> divided by <divisor thing>"'))
    return p


def validate_file(ctx, path, quiet=False):
    """returns (ok, problems). Cross-checks: the unit spec, near-dups within the file, vs the seeds and vs accepted units."""
    refuse_forbidden(path)
    probs = []
    try:
        d = loadj(path)
    except Exception as e:
        return False, [('json', f'not JSON: {e}')]
    uid = d.get('unit_id') if isinstance(d, dict) else None
    if uid not in [u for c in CHUNKS.values() for u in c['units']]:
        return False, [('schema', 'top level must be {"unit_id": "DR2-uNN", "items": [...]}')]
    spec = unit_spec(uid)
    items = d.get('items')
    if not isinstance(items, list) or len(items) != N_PER_UNIT:
        return False, [('schema', f'items must be a list of {N_PER_UNIT} templates, one per cell in cell order')]
    for it, cell in zip(items, spec['cells']):
        if not isinstance(it, dict):
            probs.append((f'cell {cell["cell"]:02d}', 'schema', 'not an object')); continue
        for code, m in item_problems(it, cell, uid):
            probs.append((f"cell {cell['cell']:02d}", code, m))
    texts = [(it.get('tid', '?'), (grams(it.get('first', '') + ' ' + it.get('question', '')),
                                    grams(it.get('second', '') + ' ' + it.get('question', ''))))
             for it in items if isinstance(it, dict)]
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            s = near(texts[i][1], texts[j][1])
            if s >= NEAR_DUP:
                probs.append((texts[j][0], 'neardup', f'char-4-gram Jaccard {s:.2f} >= {NEAR_DUP} with {texts[i][0]}'))
    others = [(s['tid'], both_grams(s)) for s in all_seeds(ctx)]
    for f in sorted(glob.glob(ctx.p('accept', '*.json'))):
        a = loadj(f)
        if a['unit_id'] != uid:
            others += [(t['tid'], both_grams(t)) for t in a['items']]
    for tid, g in texts:
        for otid, og in others:
            s = near(g, og)
            if s >= NEAR_DUP:
                probs.append((tid, 'neardup', f'char-4-gram Jaccard {s:.2f} >= {NEAR_DUP} with existing {otid}'))
    return not probs, probs


def cmd_validate(ctx, path):
    ok, probs = validate_file(ctx, path)
    for where, code, m in probs[:80]:
        P(f"FAIL [{code}] {where}: {m}")
    if ok:
        P(f"VALIDATE ok {N_PER_UNIT}")
    else:
        P(f"VALIDATE FAIL {len(probs)} problem(s)")
    return ok


# ------------------------------------------------------------------------------------------------- units / next / status
def attempts(ctx, uid):
    out = []
    p0 = ctx.p('writers', f'{uid}.json')
    if os.path.exists(p0):
        out.append((0, p0))
    for k in range(1, 10):
        pk = ctx.p('writers', f'{uid}.r{k}.json')
        if os.path.exists(pk):
            out.append((k, pk))
    return out


def unit_state(ctx, uid):
    acc = glob.glob(ctx.p('accept', f'{uid}.a*.json'))
    if acc:
        return dict(status='accepted', path=sorted(acc)[-1])
    at = attempts(ctx, uid)
    for k, p in reversed(at):
        if validate_file(ctx, p)[0]:
            return dict(status='valid', attempt=k, path=p)
    if at:
        return dict(status='invalid', attempt=at[-1][0], path=at[-1][1])
    return dict(status='pending')


def cmd_next(ctx, uid):
    spec = unit_spec(uid)
    st = unit_state(ctx, uid)
    if st['status'] in ('accepted', 'valid'):
        spec.update(status=st['status'], note='this unit already has a valid file; nothing to write', output_path=st['path'])
    else:
        k = 0 if st['status'] == 'pending' else st['attempt'] + 1
        spec.update(status=st['status'], attempt=k,
                    output_path=ctx.p('writers', f'{uid}.json' if k == 0 else f'{uid}.r{k}.json'),
                    previous_attempt=st.get('path'),
                    brief=ctx.p('ADDON_divrole2_writer.md'))
    P(json.dumps(spec, indent=1, ensure_ascii=False))
    return spec


def group_output(ctx, G):
    bp = ctx.p('blind', f'{G}.blind.json')
    if not os.path.exists(bp):
        return None, 'blocked'
    blind = loadj(bp)
    best, state = None, 'pending'
    for c in [ctx.p('verify', f'{G}.json')] + [ctx.p('verify', f'{G}.r{k}.json') for k in range(1, 6)]:
        if not os.path.exists(c):
            continue
        try:
            ok = not check_format(blind, loadj(c))
        except Exception:
            ok = False
        if ok:
            best, state = c, 'done'
        elif state != 'done':
            state = 'bad-format'
    return best, state


def cmd_status(ctx, nxt=False):
    res = {}
    for C, d in CHUNKS.items():
        us = {u: unit_state(ctx, u)['status'] for u in d['units']}
        gs = {G: group_output(ctx, G)[1] for G in d['groups']}
        cl = ctx.p('clean', f'{C}.json')
        cs = loadj(cl)['verdict'] if os.path.exists(cl) else 'none'
        res[C] = (us, gs, cs)
        P(f"{C}: units {us} | groups {gs} | clean {cs}")
    if not nxt:
        return None
    for C, (us, gs, cs) in res.items():
        if cs == 'GO':
            continue
        if cs == 'NO-GO':
            P(f'NEXT wait: {C} is NO-GO; the project lead decides (re-pilot, or retry with new units)'); return None
        if C != 'P1' and res['P1'][2] != 'GO':
            P('NEXT wait: growth chunks start only after P1 is GO'); return None
        todo = [u for u, s in us.items() if s in ('pending', 'invalid')]
        if todo:
            a = {'chunk': C} if len(todo) == len(us) else {'chunk': C, 'units': todo}
        elif any(s != 'accepted' for s in us.values()):
            a = {'chunk': C, 'stages': ['close', 'verify', 'clean']}
        else:
            gtodo = [G for G, s in gs.items() if s != 'done']
            a = {'chunk': C, 'stages': ['verify', 'clean'], 'groups': gtodo} if gtodo else {'chunk': C, 'stages': ['clean']}
        P('NEXT ' + json.dumps(a)); return a
    P('NEXT gen (every chunk is GO; the project lead decides whether to grow further and D-DR, then `divrole2.py gen`)')
    return 'gen'


# ------------------------------------------------------------------------------------------------- close (accept + blind)
def pair_for(tkey):
    """the one verification pair per template: X > Y, X NOT a multiple of Y, so all four blind texts have a
    non-integer answer (a mixed number on a>b, a proper fraction on a<b) and fraction_natural is judged on every text"""
    rng = random.Random(f'{SEED}:verify-pair:{tkey}')
    while True:
        x = rng.randrange(LO + 3, HI + 1)
        y = rng.randrange(LO, x - 2)
        if x % y != 0:
            return x, y


def fill(t, key, m, s):
    return (t[key] + ' ' + t['question'] + ' ' + CUE).replace('{M}', str(m)).replace('{S}', str(s))


def cmd_close(ctx, C):
    d = CHUNKS[C]
    st = {u: unit_state(ctx, u) for u in d['units']}
    bad = [u for u, s in st.items() if s['status'] not in ('valid', 'accepted')]
    if bad:
        P(f"CLOSE FAIL units without a valid file: {bad} (status --next)"); return False
    T = []
    for u, s in st.items():
        if s['status'] == 'valid':
            data = loadj(s['path'])
            ap = ctx.p('accept', f"{u}.a{s['attempt']}.json")
            m = dumpj(dict(unit_id=u, attempt=s['attempt'], source_file=os.path.relpath(s['path'], ctx.root),
                           source_md5=md5f(s['path']), items=data['items']), ap)
            P(f"ACCEPT ok {u} attempt {s['attempt']} -> accept/{os.path.basename(ap)} md5 {m[:8]}")
            s = dict(status='accepted', path=ap)
        else:
            P(f"ACCEPT ok {u} (already accepted: {os.path.basename(s['path'])})")
        for it in loadj(s['path'])['items']:
            T.append(dict(it, source='written', unit=u))
    if d['seeds']:
        for sd in all_seeds(ctx):
            T.append(dict(sd, unit=sd['source']))
    nd = 0          # cross-unit near duplicates inside this chunk: reported, never dropped (gen clusters them)
    G_ = [both_grams(t) for t in T]
    for i in range(len(T)):
        for j in range(i + 1, len(T)):
            if T[i]['unit'] != T[j]['unit'] and near(G_[i], G_[j]) >= NEAR_DUP:
                nd += 1
    order = sorted(T, key=lambda t: (t['source'], t['tid']))
    random.Random(f'{SEED}:deal:{C}').shuffle(order)
    groups = {G: [] for G in d['groups']}
    for i, t in enumerate(order):
        groups[d['groups'][i % len(d['groups'])]].append(t)
    for G, ts in groups.items():
        texts = []
        for t in ts:
            tkey = f"{t['source']}:{t['tid']}"
            x, y = pair_for(tkey)
            for wo, key in (('F', 'first'), ('S', 'second')):
                for half, (m, s) in (('a>b', (x, y)), ('a<b', (y, x))):
                    texts.append(dict(text=fill(t, key, m, s), tkey=tkey, tid=t['tid'], source=t['source'],
                                      written_order=wo, half=half, M=m, S=s, gold=fstr(Fraction(m, s)),
                                      dividend_name='n1' if wo == 'F' else 'n2'))
        random.Random(f'{SEED}:shuffle:{G}').shuffle(texts)
        blind, key = [], {}
        for i, x in enumerate(texts):
            iid = f'{G}-t{i + 1:03d}'
            nums = re.findall(r'\d+', x['text'])
            if nums != ([str(x['M']), str(x['S'])] if x['written_order'] == 'F' else [str(x['S']), str(x['M'])]):
                P(f"CLOSE FAIL {x['tid']}: the filled text has numerals {nums}"); return False
            blind.append(dict(id=iid, text=x['text'], numbers={f'n{j + 1}': v for j, v in enumerate(nums)}))
            key[iid] = {k: x[k] for k in ('tkey', 'tid', 'source', 'written_order', 'half', 'M', 'S', 'gold', 'dividend_name')}
        bp = ctx.p('blind', f'{G}.blind.json')
        newb = (json.dumps(dict(verifier_unit=G, language='English', cue=CUE, n_items=len(blind), items=blind),
                           indent=1, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
        if os.path.exists(bp) and open(bp, 'rb').read() != newb:
            P(f"CLOSE FAIL blind/{G}.blind.json exists with different content (never rebuilt under a verifier)"); return False
        os.makedirs(os.path.dirname(bp), exist_ok=True)
        open(bp, 'wb').write(newb)
        km = dumpj(key, ctx.p('blind_key', f'{G}.key.json'))
        dumpj(dict(group=G, chunk=C, templates=sorted(f"{t['source']}:{t['tid']}" for t in ts), n_texts=len(blind),
                   blind_md5=md5b(newb), key_md5=km), ctx.p('manifest', 'groups', f'{G}.json'))
        P(f"BLIND ok {len(blind)} texts -> blind/{G}.blind.json ({len(ts)} templates)")
    cnt = {s: sum(t['source'] == s for t in T) for s in SOURCES}
    P(f"CLOSE ok {C}: {len(T)} templates (written {cnt['written']}, v5 {cnt['v5']}, drrole {cnt['drrole']}); "
      f"cross-unit near-duplicate pairs {nd} (reported only)")
    return True


# ------------------------------------------------------------------------------------------------- verifier format
def check_format(blind, out):
    probs = []
    if not isinstance(out, dict) or out.get('verifier_unit') != blind['verifier_unit'] or not isinstance(out.get('items'), list):
        return ['top level must be {"verifier_unit": <G>, "items": [...]} with the right verifier_unit']
    want = {it['id']: it for it in blind['items']}
    seen = set()
    for x in out['items']:
        if not isinstance(x, dict) or 'id' not in x:
            probs.append('an item without an id'); continue
        if x['id'] in seen:
            probs.append(f"{x['id']}: duplicate id"); continue
        seen.add(x['id'])
        if x['id'] not in want:
            probs.append(f"{x['id']}: not in the blind file"); continue
        p = lambda m: probs.append(f"{x['id']}: {m}")
        miss = [f for f in ('op', 'operands', 'role', 'answer', 'fraction_natural', 'flags', 'note') if f not in x]
        if miss:
            p(f'missing fields {miss}'); continue
        nums = want[x['id']]['numbers']
        if x['op'] not in VOPS:
            p(f'op must be one of {VOPS}'); continue
        if not isinstance(x['flags'], list) or any(f not in VFLAGS for f in x['flags']) or len(set(x['flags'])) != len(x['flags']):
            p(f'flags must be distinct values from {VFLAGS}')
        if not isinstance(x['note'], str) or ((x['flags'] or x['op'] == 'other') and not x['note'].strip()):
            p('note must be a string, and non-empty when you raise a flag or answer op "other"')
        ans = None
        if isinstance(x['answer'], str) and re.fullmatch(r'-?\d+(/\d+)?', x['answer'].strip()) and not re.search(r'/0+$', x['answer'].strip()):
            ans = Fraction(x['answer'].strip())
        elif x['answer'] != 'none':
            p('answer must be an integer, p/q, or "none"')
        if x['op'] == 'other':
            if x['operands'] is not None or x['role'] is not None or x['fraction_natural'] is not None:
                p('op "other" needs operands null, role null, fraction_natural null')
            continue
        o = x['operands']
        if not (isinstance(o, list) and len(o) == 2 and all(v in nums for v in o) and o[0] != o[1]):
            p(f'operands must be two different names from {list(nums)}'); continue
        a_, b_ = Fraction(int(nums[o[0]])), Fraction(int(nums[o[1]]))
        if x['op'] in ('sub', 'div'):
            if x['role'] not in o:
                p('role must be one of the two operands for sub / div'); continue
            r = Fraction(int(nums[x['role']]))
            other = b_ if x['role'] == o[0] else a_
            want_v = r - other if x['op'] == 'sub' else (r / other if other else None)
        else:
            if x['role'] is not None:
                p('role must be null for add / mul')
            want_v = a_ + b_ if x['op'] == 'add' else a_ * b_
        if ans is None or want_v is None or ans != want_v:
            p(f"answer {x['answer']} is not what your op / operands / role give ({want_v})")
        if x['op'] == 'div' and ans is not None and ans.denominator != 1:
            if x['fraction_natural'] not in (True, False):
                p('a non-integer division answer needs fraction_natural true or false')
        elif x['fraction_natural'] is not None:
            p('fraction_natural must be null unless op is div and the answer is not a whole number')
    for iid in want:
        if iid not in seen:
            probs.append(f'{iid}: missing')
    return probs


def cmd_format(ctx, G, outp=None):
    bp = ctx.p('blind', f'{G}.blind.json')
    outp = outp or ctx.p('verify', f'{G}.json')
    if not os.path.exists(bp) or not os.path.exists(outp):
        P(f"FORMAT FAIL missing {bp if not os.path.exists(bp) else outp}"); return False
    try:
        out = loadj(outp)
    except Exception as e:
        P(f"FORMAT FAIL not JSON: {e}"); return False
    probs = check_format(loadj(bp), out)
    for q in probs[:60]:
        P(f"  FAIL {q}")
    if probs:
        P(f"FORMAT FAIL {len(probs)} problem(s)"); return False
    P(f"FORMAT ok {len(loadj(bp)['items'])}")
    return True


# ------------------------------------------------------------------------------------------------- clean
def cmd_clean(ctx, C, quiet=False):
    d = CHUNKS[C]
    per = {}
    for G in d['groups']:
        best, st = group_output(ctx, G)
        if st != 'done':
            P(f"CLEAN FAIL {G} is {st}"); return None
        key = loadj(ctx.p('blind_key', f'{G}.key.json'))
        for x in loadj(best)['items']:
            k = key[x['id']]
            per.setdefault(k['tkey'], []).append((k, x))
    tpl = {}
    for u in d['units']:
        for it in loadj(unit_state(ctx, u)['path'])['items']:
            tpl[f"written:{it['tid']}"] = dict(it, source='written', unit=u)
    if d['seeds']:
        for sd in all_seeds(ctx):
            tpl[f"{sd['source']}:{sd['tid']}"] = dict(sd, unit=sd['source'])
    kept, dropped = [], []
    for tk in sorted(per):
        why = []
        rows = per[tk]
        if len(rows) != 4:
            why.append(f'{len(rows)} texts, expected 4')
        for k, x in rows:
            tag = f"{k['written_order']}{k['half']}"
            if x['op'] != 'div':
                why.append(f'{tag}: op {x["op"]}')
                continue
            if x['role'] != k['dividend_name']:
                why.append(f'{tag}: role {x["role"]} is not the dividend {k["dividend_name"]}')
            if sorted(x['operands']) != ['n1', 'n2']:
                why.append(f'{tag}: operands {x["operands"]}')
            if Fraction(x['answer']) != Fraction(k['gold']):
                why.append(f'{tag}: answer {x["answer"]} != {k["gold"]}')
            if Fraction(k['gold']).denominator != 1 and x['fraction_natural'] is not True:
                why.append(f'{tag}: a fractional answer does not read naturally')
            bl = [f for f in x['flags'] if f in VBLOCK]
            if bl:
                why.append(f'{tag}: flags {bl}')
        roq = sum('role_only_in_question' in x['flags'] for _, x in rows)
        rec = dict(tpl[tk], tkey=tk, role_only_in_question=roq)
        if why:
            dropped.append(dict(tkey=tk, reasons=why, notes=[x['note'] for _, x in rows if x['note']]))
        else:
            kept.append(rec)
    n_by = {s: sum(1 for t in tpl.values() if t['source'] == s) for s in SOURCES}
    k_by = {s: sum(1 for t in kept if t['source'] == s) for s in SOURCES}
    in_bank = sum(k_by[s] for s in fold_sources())
    go = k_by['written'] >= math.ceil(GO_FRAC * n_by['written']) and (not d['seeds'] or in_bank >= GO_MIN_TOTAL)
    res = dict(chunk=C, verdict='GO' if go else 'NO-GO', kept=kept, dropped=dropped,
               kept_by_source={s: [k_by[s], n_by[s]] for s in SOURCES}, drrole_mode=DRROLE_MODE,
               kept_in_bank=in_bank,
               bar=f"kept(written) >= {GO_FRAC:.0%} of written" +
                   (f" and kept in the bank ({'+'.join(fold_sources())}) >= {GO_MIN_TOTAL}" if d['seeds'] else ''))
    dumpj(res, ctx.p('clean', f'{C}.json'))
    if not quiet:
        for dr in dropped:
            P(f"  DROP {dr['tkey']}: {'; '.join(dr['reasons'][:4])}")
        P(f"CLEAN ok {C} kept {len(kept)}/{len(tpl)} (" + ', '.join(f"{s} {k_by[s]}/{n_by[s]}" for s in SOURCES) +
          f"; in the bank {in_bank}) -> {res['verdict']} ({res['bar']})")
    return res


# ------------------------------------------------------------------------------------------------- gen (DR-ROLE port)
def draw_pairs(rng, n):
    """gen_divrole.draw_pairs verbatim: half X = kY (an integer quotient on the a>b row), half general (X not a multiple)"""
    out, seen = [], set()
    while len(out) < n:
        if len(out) % 2 == 0:                                   # multiple: X = k * Y
            y = rng.randrange(2, 13); k = rng.randrange(2, 10); x = k * y
            kind = 'multiple'
        else:                                                   # general: X > Y, X not a multiple of Y
            x = rng.randrange(LO + 1, HI + 1); y = rng.randrange(LO, x)
            kind = 'general'
            if x % y == 0:
                continue
        if not (LO <= y < x <= HI) or (x, y) in seen:
            continue
        seen.add((x, y)); out.append((x, y, kind))
    return out


def cmd_gen(ctx, out=None, quiet=False):
    out = out or ctx.p('bank')
    K = []
    for C in CHUNKS:
        cp = ctx.p('clean', f'{C}.json')
        if os.path.exists(cp):
            c = loadj(cp)
            if c['verdict'] != 'GO':
                sys.exit(f'REFUSE: clean/{C}.json is {c["verdict"]}; only GO chunks enter the bank')
            if c.get('drrole_mode') != DRROLE_MODE:
                sys.exit(f'REFUSE: clean/{C}.json was cleaned under DRROLE_MODE {c.get("drrole_mode")!r}, now {DRROLE_MODE!r} '
                         f'(re-run `clean {C}` after changing D-DR)')
            K += c['kept']
    FS = fold_sources()
    B = [t for t in K if t['source'] in FS]                     # the bank: template-grouped folds
    R = [t for t in K if t['source'] not in FS]                 # the held-out reference (fold -1)
    if len(B) < 5:
        sys.exit(f'REFUSE: only {len(B)} kept templates in the bank; template-grouped 5-fold needs >= 5')
    npair = max(8, min(60, round(TARGET_ROWS / (4 * len(B)))))
    # near-duplicate clusters (char-4-gram Jaccard >= NEAR_DUP on first + question OR on second + question, union-find)
    # share ONE fold, so a held-out template never has a near-twin in the training folds in either written order
    keys = sorted(t['tkey'] for t in B)
    byk = {t['tkey']: t for t in K}
    par = {k: k for k in keys}

    def find(k):
        while par[k] != k:
            par[k] = par[par[k]]; k = par[k]
        return k
    GG = {t['tkey']: both_grams(t) for t in K}
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if near(GG[keys[i]], GG[keys[j]]) >= NEAR_DUP:
                par[find(keys[j])] = find(keys[i])
    clusters = {}
    for k in keys:
        clusters.setdefault(find(k), []).append(k)
    frng = random.Random(SEED + ':folds')
    order = []
    for src in FS:
        ids = sorted(c for c in clusters if byk[c]['source'] == src); frng.shuffle(ids); order += ids
    fold = {}
    for i, c in enumerate(order):
        for k in clusters[c]:
            fold[k] = i % 5
    for t in R:
        fold[t['tkey']] = -1
    ref_near = sorted({r['tkey'] for r in R for b in B if near(GG[r['tkey']], GG[b['tkey']]) >= NEAR_DUP})
    rows = []
    for t in sorted(K, key=lambda t: t['tkey']):
        rng = random.Random(f"{SEED}:{t['tkey']}")
        for p, (x, y, kind) in enumerate(draw_pairs(rng, npair)):
            for wo, key, gidx in (('F', 'first', [0, 1]), ('S', 'second', [1, 0])):
                for half, (m, s) in (('a>b', (x, y)), ('a<b', (y, x))):
                    written = [m, s] if wo == 'F' else [s, m]
                    f = Fraction(m, s); sw = Fraction(s, m)
                    rows.append(dict(
                        row_id=f"dr2:en:{t['tkey']}:{p:02d}:{wo}:{'lt' if half == 'a<b' else 'gt'}",
                        pair_key=f"dr2:en:{t['tkey']}:{p:02d}", status='scored', lang='en', stratum='divrole2',
                        source='divrole2_v1', template_source=t['source'], template_id=t['tid'], frame=t['frame'],
                        topic=t['topic'], div_mode=t.get('div_mode', 'rate_or_share') or 'rate_or_share',
                        drrole_origin=t.get('origin') if t['source'] == 'drrole' else None,
                        text=fill(t, key, m, s), answer_cue=CUE, op='division', op_short='div',
                        a=m, b=s, ans=float(f), ans_frac=f"{f.numerator}/{f.denominator}", ans_is_int=f.denominator == 1,
                        swap_frac=f"{sw.numerator}/{sw.denominator}",
                        half=half, written_order=wo, variant='min_first' if wo == 'F' else 'sub_first',
                        minuend_is_larger=half == 'a>b', minuend_written_first=wo == 'F',     # gen_divrole key names
                        dividend_is_larger=half == 'a>b', dividend_written_first=wo == 'F',
                        written_smaller_first=written[0] < written[1], pair_kind=kind,
                        role_only_in_question=t.get('role_only_in_question', 0), reference=t['source'] not in FS,
                        ref_near_dup_of_bank=t['tkey'] in ref_near, list_values=written, n_numerals_written=2,
                        fold=fold[t['tkey']],
                        prov=dict(locator='block.digit_runs(tok, ids)', n_runs=2, gold_run_idx=gidx,
                                  run_lens=[len(str(v)) for v in written],
                                  note='gold_run_idx = [DIVIDEND run, DIVISOR run] in written-run indices')))
    os.makedirs(os.path.join(out, 'dump'), exist_ok=True)
    blob = ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in rows).encode('utf-8')
    open(os.path.join(out, 'dump', 'DIVROLE2.jsonl'), 'wb').write(blob)
    cnt = lambda f, rr=rows: {str(v): sum(1 for r in rr if f(r) == v) for v in sorted({f(r) for r in rr}, key=str)}
    bank_rows = [r for r in rows if r['fold'] >= 0]
    cen = dict(seed=SEED, drrole_mode=DRROLE_MODE, fold_sources=list(FS), kept=len(K),
               kept_by_source={s: sum(t['source'] == s for t in K) for s in SOURCES},
               bank_templates=len(B), reference_templates=len(R), reference_near_dup_of_bank=ref_near,
               pairs_per_template=npair, rows=len(rows), bank_rows=len(bank_rows), reference_rows=len(rows) - len(bank_rows),
               near_dup_clusters=sum(1 for c in clusters.values() if len(c) > 1),
               templates_in_near_dup_clusters=sum(len(c) for c in clusters.values() if len(c) > 1),
               rows_by_half=cnt(lambda r: r['half']), rows_by_order=cnt(lambda r: r['written_order']),
               rows_by_smaller_first=cnt(lambda r: r['written_smaller_first']),
               rows_by_cell=cnt(lambda r: f"{r['written_order']}|{r['half']}"),
               rows_by_source=cnt(lambda r: r['template_source']), rows_by_frame=cnt(lambda r: r['frame']),
               rows_by_pair_kind=cnt(lambda r: r['pair_kind']), rows_int_gold=cnt(lambda r: f"{r['half']}|{r['ans_is_int']}"),
               rows_by_fold=cnt(lambda r: r['fold']),
               templates_by_fold={str(f): sorted(t for t in fold if fold[t] == f) for f in range(-1, 5)})
    cb = (json.dumps(cen, indent=1, sort_keys=True) + '\n').encode('utf-8')
    open(os.path.join(out, 'bank_census.json'), 'wb').write(cb)
    open(os.path.join(out, 'BANK.md5'), 'w').write(f"{md5b(blob)}  dump/DIVROLE2.jsonl\n{md5b(cb)}  bank_census.json\n")
    if not quiet:
        P(f"GEN-DIVROLE2 kept {len(K)} templates (bank {len(B)}, reference {len(R)}; D-DR {DRROLE_MODE}), {npair} pairs "
          f"each, rows {len(rows)} (bank {len(bank_rows)}; a<b {cen['rows_by_half'].get('a<b')}, a>b "
          f"{cen['rows_by_half'].get('a>b')}), md5 {md5b(blob)}")
    return rows, cen, md5b(blob)


# ------------------------------------------------------------------------------------------------- selftest
FIXTURES = {   # one known-good template per frame cell (selftest only; never shown to a writer)
    'D01': ('After dinner the restaurant bill came to {M} dollars. It was split equally among {S} friends.',
            'After dinner {S} friends split the restaurant bill equally. It came to {M} dollars.',
            "How many dollars was each friend's share of the bill?", 'dollars of the bill divided by friends'),
    'D02': ('The farm set aside {M} kilograms of hay for the winter, shared equally among its {S} horses.',
            'The farm shares equally among its {S} horses the {M} kilograms of hay set aside for the winter.',
            'How many kilograms of hay does each horse get?', 'kilograms of hay divided by horses'),
    'D03': ('At the beach the children piled up {M} kilograms of sand and shared it out equally into {S} buckets.',
            'At the beach the children shared out equally into {S} buckets the {M} kilograms of sand they piled up.',
            'How many kilograms of sand ended up in each bucket?', 'kilograms of sand divided by buckets'),
    'D04': ('The tailor took a roll of fabric {M} metres long and cut it into {S} curtains of equal length.',
            'The tailor cut {S} curtains of equal length from a roll of fabric {M} metres long.',
            'How many metres of fabric went into each curtain?', 'metres of fabric divided by curtains'),
    'D05': ('Over the morning the snail crawled {M} centimetres along the wall. The crawl took {S} minutes.',
            'Over the morning the snail spent {S} minutes on its crawl along the wall, covering {M} centimetres.',
            'How many centimetres did the snail crawl per minute?', 'centimetres divided by minutes'),
    'D06': ('The water pump moved {M} litres from the cellar in {S} minutes.',
            'In {S} minutes the water pump moved {M} litres from the cellar.',
            'How many litres did the pump move per minute?', 'litres moved divided by minutes'),
    'D07': ('At the market a shopper paid {M} dollars for {S} kilograms of cheese.',
            'At the market a shopper bought {S} kilograms of cheese and paid {M} dollars.',
            'What was the price of the cheese per kilogram, in dollars?', 'dollars paid divided by kilograms'),
    'D08': ('The delivery van drove {M} kilometres this week. It burned {S} litres of fuel doing so.',
            'The delivery van burned {S} litres of fuel this week, driving {M} kilometres.',
            'How many kilometres did the van drive per litre of fuel?', 'kilometres divided by litres of fuel'),
    'D09': ('The cook stirred {M} grams of salt into the soup pot, which holds {S} litres of soup.',
            'The soup pot holds {S} litres of soup, and the cook stirred {M} grams of salt into it.',
            'How many grams of salt are there per litre of soup?', 'grams of salt divided by litres of soup'),
    'D10': ('This month the town measured {M} millimetres of rain over its {S} rainy days.',
            'Over its {S} rainy days this month the town measured {M} millimetres of rain.',
            'What was the average rainfall per rainy day, in millimetres?', 'millimetres of rain divided by rainy days'),
    'D11': ('The babysitter earned {M} dollars on Saturday for {S} hours of work.',
            'The babysitter worked {S} hours on Saturday and earned {M} dollars.',
            'How many dollars did the babysitter earn per hour?', 'dollars earned divided by hours'),
    'D12': ('The recipe uses {M} cups of oats to make {S} servings of porridge.',
            'To make {S} servings of porridge, the recipe uses {M} cups of oats.',
            'How many cups of oats go into each serving?', 'cups of oats divided by servings'),
}


def fixture_unit(uid):
    spec = unit_spec(uid)
    items = []
    for c in spec['cells']:
        f, s, q, qc = FIXTURES[c['frame']]
        items.append(dict(tid=f"{uid}-{c['cell']:02d}", frame=c['frame'], topic=c['topic'], first=f, second=s,
                          question=q, quotient_convention=qc, fraction_reading='a fraction means less than a whole unit each'))
    return dict(unit_id=uid, items=items)


MUTANTS = [   # (code the validator must raise, mutation of one item)
    ('schema', lambda it: it.pop('quotient_convention')),
    ('cell', lambda it: it.update(topic='something else')),
    ('slots', lambda it: it.update(first=it['first'].replace('{S}', 'some'))),
    ('order', lambda it: it.update(second=it['first'])),
    ('slots', lambda it: it.update(question=it['question'][:-1] + ' {M}?')),
    ('article', lambda it: it.update(first=it['first'].replace('{S}', 'a {S}', 1))),
    ('digit', lambda it: it.update(first=it['first'] + ' It had 3 helpers.')),
    ('numberword', lambda it: it.update(first=it['first'] + ' It had a dozen helpers.')),
    ('numberword', lambda it: it.update(first=it['first'] + ' A quarter of it was spare.')),
    ('cue', lambda it: it.update(question=it['question'] + ' The answer is')),
    ('question', lambda it: it.update(question=it['question'].rstrip('?') + '.')),
    ('banned', lambda it: it.update(question='How many are left over for each of them?')),
    ('banned', lambda it: it.update(question='How many full boxes does each of them get?')),
    ('divcue', lambda it: it.update(question='How much did they get?')),
    ('length', lambda it: it.update(first=it['first'] + ' It was a very long and busy and noisy and cheerful and '
                                    'crowded and sunny and windy and bright and lively day for everyone there, with '
                                    'music and games and food and laughter and stories and songs from morning until '
                                    'the quiet evening finally came.')),
    ('reorder', lambda it: it.update(second='Things were quiet: {S} came, and later {M} went.')),
    ('quotient', lambda it: it.update(quotient_convention='the amount over the count')),
]


def cmd_selftest():
    global DRROLE_MODE
    res = []
    mode0 = DRROLE_MODE

    def check(name, ok):
        res.append((name, bool(ok)))
        P(f"  {'ok  ' if ok else 'FAIL'} {name}")
    tmp = tempfile.mkdtemp(prefix='divrole2_st_')
    try:
        DRROLE_MODE = 'reference'
        ctx = Ctx(tmp)
        i1, m1 = cmd_manifest(ctx)
        i2, m2 = cmd_manifest(Ctx(os.path.join(tmp, 'b')))
        check(f'manifest deterministic ({m1[:8]} twice); units {len(i1["units_md5"])}/16; seeds v5 {i1["seeds_n"]["v5"]}/36, '
              f'drrole {i1["seeds_n"]["drrole"]}/20', m1 == m2 and len(i1['units_md5']) == 16
              and i1['seeds_n'] == dict(v5=36, drrole=20))
        seeds = all_seeds(ctx)
        dr = [s for s in seeds if s['source'] == 'drrole']
        check(f"drrole seeds: 16 digits-prose + 4 v5 ({sum(s['origin'] == 'digits_prose' for s in dr)} + "
              f"{sum(s['origin'] == 'v5' for s in dr)}); no tid in both sources",
              sum(s['origin'] == 'digits_prose' for s in dr) == 16 and sum(s['origin'] == 'v5' for s in dr) == 4
              and len({s['tid'] for s in seeds}) == len(seeds) == 56)
        sbad = [s['tid'] for s in seeds if [c for c, _ in item_problems(dict(s, fraction_reading='x', quotient_convention='x'))
                                            if c in ('slots', 'order', 'digit')]]
        check(f'the 56 seeds are structurally sound (slots / order / no digits): {56 - len(sbad)}/56 {sbad}', not sbad)
        try:
            idxp = ctx.p('manifest', 'MANIFEST_INDEX.json'); j = loadj(idxp); j['n_per_unit'] = 99; dumpj(j, idxp)
            cmd_manifest(ctx); refused = False
        except SystemExit:
            refused = True
        check('manifest refuses to move a frozen unit spec', refused)
        dumpj(i1, ctx.p('manifest', 'MANIFEST_INDEX.json'))
        # validator: the fixture unit passes; per frame cell, every mutant is caught with its own code
        for u in CHUNKS['P1']['units']:
            dumpj(fixture_unit(u), ctx.p('writers', f'{u}.json'))
        ok, probs = validate_file(ctx, ctx.p('writers', 'DR2-u01.json'))
        check(f'validator: the 12-cell fixture unit passes (VALIDATE ok 12) {probs[:3]}', ok)
        tot = 0
        for ci, f in enumerate(FRAME_IDS):
            caught = 0
            for code, mf in MUTANTS:
                d = fixture_unit('DR2-u01')
                mf(d['items'][ci])
                p = os.path.join(tmp, 'mut.json'); dumpj(d, p)
                ok, probs = validate_file(ctx, p)
                caught += (not ok) and any(c == code and w == f'cell {ci + 1:02d}' for w, c, _ in probs)
            tot += caught
            check(f'validator cell {ci + 1:02d} ({f}): the good template passes and {caught}/{len(MUTANTS)} mutants are '
                  f'caught with their own code', caught == len(MUTANTS))
        P(f"  (validator mutants caught: {tot}/{len(MUTANTS) * len(FRAME_IDS)})")
        d = fixture_unit('DR2-u01'); d['items'] = d['items'][:11]
        p = os.path.join(tmp, 'mut.json'); dumpj(d, p)
        check('validator: 11 items -> FAIL', not validate_file(ctx, p)[0])
        d = fixture_unit('DR2-u01'); d['items'][5] = dict(d['items'][3], tid='DR2-u01-06', frame='D06', topic=d['items'][5]['topic'])
        dumpj(d, p)
        check('validator: a near-duplicate inside the unit -> FAIL [neardup]',
              any(c == 'neardup' for _, c, _ in validate_file(ctx, p)[1]))
        for src in ('v5', 'drrole'):
            s0 = [s for s in seeds if s['source'] == src][0]
            d = fixture_unit('DR2-u01')
            d['items'][0].update(first=s0['first'], second=s0['second'], question=s0['question'])
            dumpj(d, p)
            check(f'validator: a copy of a {src} seed ({s0["tid"]}) -> FAIL [neardup]',
                  any(c == 'neardup' and 'existing ' + s0['tid'] in m for _, c, m in validate_file(ctx, p)[1]))
        d = fixture_unit('DR2-u01'); a0 = d['items'][0]; a1 = d['items'][1]
        a1.update(second=a0['second'], question=a0['question'])     # near twin on second + question only
        a1['first'] = 'Down the lane, ' + a1['first']
        dumpj(d, p)
        j1 = jacc(grams(a0['first'] + ' ' + a0['question']), grams(a1['first'] + ' ' + a1['question']))
        j2 = jacc(grams(a0['second'] + ' ' + a0['question']), grams(a1['second'] + ' ' + a1['question']))
        check(f'validator: a near-duplicate on second + question only (J first {j1:.2f} < {NEAR_DUP}, J second {j2:.2f}) '
              f'-> FAIL [neardup] (both written orders checked)',
              j1 < NEAR_DUP <= j2 and any(c == 'neardup' and w == a1['tid'] for w, c, _ in validate_file(ctx, p)[1]))
        # status / next / attempts
        dumpj(dict(fixture_unit('DR2-u04'), items=fixture_unit('DR2-u04')['items'][:3]), ctx.p('writers', 'DR2-u04.json'))
        st = unit_state(ctx, 'DR2-u04')
        check(f"status: an invalid attempt -> invalid; next gives attempt 1 -> writers/DR2-u04.r1.json",
              st['status'] == 'invalid' and next_spec(ctx, 'DR2-u04')['output_path'].endswith('DR2-u04.r1.json'))
        a = cmd_status(ctx, nxt=True)
        check(f'status --next with one invalid unit: {a}', a == {'chunk': 'P1', 'units': ['DR2-u04']})
        dumpj(fixture_unit('DR2-u04'), ctx.p('writers', 'DR2-u04.r1.json'))
        check('status: the valid retry makes the unit valid', unit_state(ctx, 'DR2-u04')['status'] == 'valid')
        a = cmd_status(ctx, nxt=True)
        check(f'status --next with every unit valid: {a}', a == {'chunk': 'P1', 'stages': ['close', 'verify', 'clean']})
        ok = cmd_close(ctx, 'P1')
        check('close P1: accept 4 units + 4 blind files', ok and len(glob.glob(ctx.p('blind', '*.json'))) == 4)
        check('close is idempotent (a second close changes nothing)', cmd_close(ctx, 'P1'))
        leak = 0; ntext = 0; nonint = 0; sizes = []
        for G in CHUNKS['P1']['groups']:
            bl = loadj(ctx.p('blind', f'{G}.blind.json')); kk = loadj(ctx.p('blind_key', f'{G}.key.json'))
            leak += set(bl) != {'verifier_unit', 'language', 'cue', 'n_items', 'items'}
            sizes.append(len(bl['items']))
            for it in bl['items']:
                ntext += 1
                nonint += Fraction(kk[it['id']]['gold']).denominator != 1
                leak += (set(it) != {'id', 'text', 'numbers'} or '{' in it['text'] or 'DR2-u' in it['text']
                         or 'W5-' in it['text'] or re.search(r'\bdp\d', it['text']) is not None)
        check(f'blind files: {ntext} texts = 4 x 104 templates in groups {sizes}, no slot, id or label leaks ({leak}); '
              f'non-integer gold on {nonint}/{ntext}', leak == 0 and ntext == 416 and nonint == ntext)
        # format gate: an oracle passes, mutants fail
        G = 'DR2V-p1a'
        bl = loadj(ctx.p('blind', f'{G}.blind.json')); key = loadj(ctx.p('blind_key', f'{G}.key.json'))

        def orc_item(it, k):
            other = 'n2' if k['dividend_name'] == 'n1' else 'n1'
            return dict(id=it['id'], op='div', operands=[k['dividend_name'], other], role=k['dividend_name'],
                        answer=k['gold'], fraction_natural=True if Fraction(k['gold']).denominator != 1 else None,
                        flags=[], note='')

        def oracle(Gx):
            blx = loadj(ctx.p('blind', f'{Gx}.blind.json')); kx = loadj(ctx.p('blind_key', f'{Gx}.key.json'))
            return dict(verifier_unit=Gx, items=[orc_item(it, kx[it['id']]) for it in blx['items']])
        orc = oracle(G)
        check(f'format: the oracle passes ({len(orc["items"])} items)', not check_format(bl, orc))
        o2 = json.loads(json.dumps(orc)); x0 = o2['items'][0]; f0 = Fraction(x0['answer'])
        x0['answer'] = f"{f0.numerator * 3}/{f0.denominator * 3}"
        check('format: an unreduced but equal fraction (3p/3q) passes', not check_format(bl, o2))
        lt_i = next(i for i, x in enumerate(orc['items']) if Fraction(x['answer']) < 1)
        M = [('wrong answer for its own op', lambda o: o['items'][0].update(answer='12345')),
             ('decimal answer', lambda o: o['items'][0].update(answer='0.375')),
             ('role not an operand', lambda o: o['items'][0].update(role='n3')),
             ('fraction without fraction_natural', lambda o: o['items'][lt_i].update(fraction_natural=None)),
             ('fraction_natural on an add', lambda o: o['items'][0].update(op='add', role=None, answer=str(sum(
                 int(v) for v in {i['id']: i for i in bl['items']}[o['items'][0]['id']]['numbers'].values())))),
             ('other with operands', lambda o: o['items'][0].update(op='other', note='x')),
             ('flag without note', lambda o: o['items'][0].update(flags=['ambiguous'])),
             ('unknown flag', lambda o: o['items'][0].update(flags=['nice'], note='x')),
             ('missing item', lambda o: o['items'].pop()),
             ('duplicate', lambda o: o['items'].append(dict(o['items'][0])))]
        for nm, mf in M:
            o = json.loads(json.dumps(orc)); mf(o)
            check(f'format mutant fails: {nm}', bool(check_format(bl, o)))
        # clean: the oracle keeps everything -> GO; mutants drop exactly their template
        for Gx in CHUNKS['P1']['groups']:
            dumpj(oracle(Gx), ctx.p('verify', f'{Gx}.json'))
        r = cmd_clean(ctx, 'P1', quiet=True)
        check(f"clean on the oracle: kept {len(r['kept'])}/104 ({r['kept_by_source']}; in the bank {r['kept_in_bank']}) "
              f"-> {r['verdict']}", len(r['kept']) == 104 and r['verdict'] == 'GO' and r['kept_in_bank'] == 84)
        tk_lt = key[orc['items'][lt_i]['id']]['tkey']
        o = json.loads(json.dumps(orc)); o['items'][lt_i]['fraction_natural'] = False
        dumpj(o, ctx.p('verify', f'{G}.json'))
        r = cmd_clean(ctx, 'P1', quiet=True)
        check(f'clean: fraction_natural false on one a<b text drops exactly that template ({tk_lt})',
              len(r['kept']) == 103 and [d['tkey'] for d in r['dropped']] == [tk_lt])
        o = json.loads(json.dumps(orc)); x = o['items'][0]; x['role'] = x['operands'][1]
        x['answer'] = fstr(1 / Fraction(key[x['id']]['gold']))
        x['fraction_natural'] = True if Fraction(x['answer']).denominator != 1 else None
        dumpj(o, ctx.p('verify', f'{G}.json'))
        r = cmd_clean(ctx, 'P1', quiet=True)
        check('clean: the role swapped on one text (answer S/M) drops its template',
              len(r['kept']) == 103 and 'role' in r['dropped'][0]['reasons'][0])
        o = json.loads(json.dumps(orc)); o['items'][0].update(flags=['integer_only'], note='asks a whole count')
        dumpj(o, ctx.p('verify', f'{G}.json'))
        r = cmd_clean(ctx, 'P1', quiet=True)
        check('clean: a blocking flag (integer_only) drops its template', len(r['kept']) == 103)
        o = json.loads(json.dumps(orc)); o['items'][0].update(flags=['role_only_in_question'], note='role from the question')
        dumpj(o, ctx.p('verify', f'{G}.json'))
        r = cmd_clean(ctx, 'P1', quiet=True)
        check('clean: role_only_in_question is recorded, not blocking', len(r['kept']) == 104
              and sum(t['role_only_in_question'] for t in r['kept']) == 1)
        # GO bar arithmetic: drop every v5 seed and every written template but 24 -> GO iff written >= 24 and bank >= 25
        for Gx in CHUNKS['P1']['groups']:     # the null fixture: every text read as multiplication -> NO-GO
            o = oracle(Gx)
            nn = {i['id']: i for i in loadj(ctx.p('blind', f'{Gx}.blind.json'))['items']}
            for xx in o['items']:
                v = [int(v) for v in nn[xx['id']]['numbers'].values()]
                xx.update(op='mul', role=None, fraction_natural=None, answer=str(v[0] * v[1]))
            dumpj(o, ctx.p('verify', f'{Gx}.json'))
        r = cmd_clean(ctx, 'P1', quiet=True)
        check(f"clean: the null fixture (every text read as multiplication) -> kept {len(r['kept'])}/104, {r['verdict']}",
              r['verdict'] == 'NO-GO' and not r['kept'])
        a = cmd_status(ctx, nxt=True)
        check(f'status --next after a NO-GO pilot refuses to go on ({a})', a is None)
        try:
            cmd_gen(ctx, quiet=True); refused = False
        except SystemExit:
            refused = True
        check('gen refuses a NO-GO chunk', refused)
        # the GO bar edge: only drrole kept (20, outside the bank in reference mode) + 24 written -> GO needs bank >= 25
        keep_src = lambda k: k['source'] == 'drrole' or (k['source'] == 'written' and k['tid'].startswith('DR2-u0') and
                                                         int(k['tid'][-2:]) <= 6)
        for Gx in CHUNKS['P1']['groups']:
            o = oracle(Gx); kx = loadj(ctx.p('blind_key', f'{Gx}.key.json'))
            for xx in o['items']:
                if not keep_src(kx[xx['id']]):
                    xx.update(flags=['unnatural'], note='x')
            dumpj(o, ctx.p('verify', f'{Gx}.json'))
        r = cmd_clean(ctx, 'P1', quiet=True)
        check(f"GO bar: written 24/48 + drrole 20 kept but only {r['kept_in_bank']} in the bank (reference mode) -> "
              f"{r['verdict']} (needs >= 25 in the bank)", r['verdict'] == 'NO-GO' and r['kept_by_source']['written'] == [24, 48])
        DRROLE_MODE = 'bank'
        r = cmd_clean(ctx, 'P1', quiet=True)
        check(f"GO bar: the same verdicts in bank mode -> {r['kept_in_bank']} in the bank -> {r['verdict']}",
              r['verdict'] == 'GO' and r['kept_in_bank'] == 44)
        DRROLE_MODE = 'reference'
        for Gx in CHUNKS['P1']['groups']:
            dumpj(oracle(Gx), ctx.p('verify', f'{Gx}.json'))
        cmd_clean(ctx, 'P1', quiet=True)
        a = cmd_status(ctx, nxt=True)
        check(f'status --next after a GO pilot points to G1: {a}', a == {'chunk': 'G1'})
        # gen: the DR-ROLE design, checked on the fixture bank (reference mode)
        rows, cen, bm = cmd_gen(ctx, out=os.path.join(tmp, 'bank1'), quiet=True)
        rows2, cen2, bm2 = cmd_gen(ctx, out=os.path.join(tmp, 'bank2'), quiet=True)
        npr = cen['pairs_per_template']
        check(f'gen deterministic (md5 {bm[:8]} twice), rows {len(rows)} = 4 x {npr} x 104 (bank 84 + reference 20)',
              bm == bm2 and len(rows) == 4 * npr * 104 and cen['bank_templates'] == 84 and cen['reference_templates'] == 20)
        lt = [r for r in rows if r['half'] == 'a<b']; gt = [r for r in rows if r['half'] == 'a>b']
        dv = lambda r: r['list_values'][r['prov']['gold_run_idx'][0]]; ds = lambda r: r['list_values'][r['prov']['gold_run_idx'][1]]
        size_lt = sum(dv(r) > ds(r) for r in lt); size_gt = sum(dv(r) > ds(r) for r in gt)
        check(f'gen: SIZE rule names the dividend on a<b {size_lt}/{len(lt)} and on a>b {size_gt}/{len(gt)}',
              size_lt == 0 and size_gt == len(gt) and len(lt) == len(gt))
        order_s = sum(r['prov']['gold_run_idx'][0] == 0 for r in rows if r['written_order'] == 'S')
        check(f'gen: FIRST-WRITTEN rule names the dividend on S rows {order_s}/{len(rows) // 2}', order_s == 0)
        sf = sum(r['written_smaller_first'] for r in rows)
        check(f'gen: smaller number written first on {sf}/{len(rows)} rows (exactly half)', sf * 2 == len(rows))
        okg = all(Fraction(r['ans_frac']) == Fraction(dv(r), ds(r)) and r['a'] == dv(r) and r['b'] == ds(r)
                  and Fraction(r['swap_frac']) == Fraction(ds(r), dv(r)) and abs(r['ans'] - dv(r) / ds(r)) < 1e-12
                  and re.findall(r'\d+', r['text']) == [str(v) for v in r['list_values']] for r in rows)
        check('gen: gold = dividend run / divisor run (exact), swap = its inverse, numerals == regex runs on every row', okg)
        ilt = sum(r['ans_is_int'] for r in lt); igt = sum(r['ans_is_int'] for r in gt)
        mgt = sum(r['pair_kind'] == 'multiple' for r in gt)
        check(f'gen: integer gold on a<b {ilt}/{len(lt)} (never) and on a>b {igt}/{len(gt)} (= the multiple pairs, {mgt})',
              ilt == 0 and igt == mgt == len(gt) // npr * ((npr + 1) // 2))
        folds = {}
        for r in rows:
            folds.setdefault(r['template_id'] + r['template_source'], set()).add(r['fold'])
        fx = {}
        for r in rows:
            if r['template_source'] == 'written':
                fx.setdefault(r['template_id'].split('-')[-1], set()).add(r['fold'])
        check(f"gen: near-duplicate templates across units share a fold (the 4 identical fixture units: "
              f"{sum(len(v) == 1 for v in fx.values())}/12 cells in one fold; {cen['near_dup_clusters']} clusters)",
              len(fx) == 12 and all(len(v) == 1 for v in fx.values()))
        tbf = {k: len(v) for k, v in cen['templates_by_fold'].items()}
        refok = all((r['fold'] == -1) == (r['template_source'] == 'drrole') == r['reference'] for r in rows)
        check(f"gen: template-grouped folds (every template in one fold); templates per fold {tbf}; drrole rows are the "
              f"reference (fold -1) {refok}", all(len(v) == 1 for v in folds.values()) and refok
              and min(tbf[str(f)] for f in range(5)) >= 5 and tbf['-1'] == 20)
        DRROLE_MODE = 'bank'
        for C_ in ('P1',):
            cmd_clean(ctx, C_, quiet=True)
        rows3, cen3, bm3 = cmd_gen(ctx, out=os.path.join(tmp, 'bank3'), quiet=True)
        f3 = {r['fold'] for r in rows3 if r['template_source'] == 'drrole'}
        dpc = {}
        for r in rows3:
            if r['template_source'] == 'drrole':
                dpc.setdefault(r['template_id'], r['fold'])
        check(f"gen in bank mode: drrole templates take folds {sorted(f3)} (no -1), every row in folds 0-4, "
              f"{cen3['bank_templates']} bank templates; near-twins dp02 / dp12 share a fold "
              f"({dpc.get('dp02')} / {dpc.get('dp12')})",
              -1 not in f3 and all(0 <= r['fold'] < 5 for r in rows3) and cen3['bank_templates'] == 104
              and dpc.get('dp02') == dpc.get('dp12'))
        DRROLE_MODE = 'reference'
        try:
            cmd_gen(ctx, out=os.path.join(tmp, 'bank4'), quiet=True); refused = False
        except SystemExit:
            refused = True
        check('gen refuses a clean file made under the other D-DR mode', refused)
    finally:
        DRROLE_MODE = mode0
        shutil.rmtree(tmp, ignore_errors=True)
    n_ok = sum(ok for _, ok in res)
    P(f"SELFTEST {'PASS' if n_ok == len(res) else 'FAIL'} {n_ok}/{len(res)}")
    return n_ok == len(res)


def next_spec(ctx, uid):
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        return cmd_next(ctx, uid)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd', required=True)
    sp.add_parser('manifest')
    s = sp.add_parser('status'); s.add_argument('--next', action='store_true')
    s = sp.add_parser('next'); s.add_argument('unit')
    s = sp.add_parser('validate'); s.add_argument('path')
    s = sp.add_parser('close'); s.add_argument('chunk', choices=sorted(CHUNKS))
    s = sp.add_parser('format'); s.add_argument('group'); s.add_argument('out', nargs='?')
    s = sp.add_parser('clean'); s.add_argument('chunk', choices=sorted(CHUNKS))
    s = sp.add_parser('gen'); s.add_argument('--out')
    sp.add_parser('selftest')
    a = ap.parse_args()
    ctx = Ctx(HERE)
    if a.cmd == 'manifest':
        idx, m = cmd_manifest(ctx)
        P(f"MANIFEST ok units {len(idx['units_md5'])}, chunks {list(CHUNKS)}, seeds {idx['seeds_n']}, MANIFEST_INDEX md5 {m}")
    elif a.cmd == 'status':
        cmd_status(ctx, a.next)
    elif a.cmd == 'next':
        cmd_next(ctx, a.unit)
    elif a.cmd == 'validate':
        sys.exit(0 if cmd_validate(ctx, a.path) else 1)
    elif a.cmd == 'close':
        sys.exit(0 if cmd_close(ctx, a.chunk) else 1)
    elif a.cmd == 'format':
        sys.exit(0 if cmd_format(ctx, a.group, a.out) else 1)
    elif a.cmd == 'clean':
        sys.exit(0 if cmd_clean(ctx, a.chunk) else 1)
    elif a.cmd == 'gen':
        cmd_gen(ctx, a.out)
    elif a.cmd == 'selftest':
        sys.exit(0 if cmd_selftest() else 1)


if __name__ == '__main__':
    main()
