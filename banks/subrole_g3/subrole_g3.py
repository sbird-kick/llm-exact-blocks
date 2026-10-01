"""subrole_g3.py -- the SUBTRACTION TOP-UP increment (chunk G3) of the stamped subrole bank (PREREG_subrole.md, md5
2ebad611; bank e75e670a). It is an INCREMENT: the stamped bank and every file under signed/subrole/ are read, never written.

Why. The stamped bank kept 190/222 templates (written 168/192, v5 seeds 22/30). This chunk writes 3 new units SR-u17..u19
(12 templates each, one per frame F01-F12, on 36 topics that no stamped unit used), blind-verifies them exactly as the
stamped chunks were, and generates a separate held-out bank `bank/dump/SUBROLE_G3.jsonl` (fold = -2, template_source =
written_g3) on which the FROZEN SR-ROLE reader (fitted by subrole/fit_subrole.py on the stamped bank) is scored.

Identical to the stamped subrole.py (3fb169ad), and checked to be source-identical by the selftest (AST of each function):
  the per-template validator item_problems, the verifier format gate check_format, the blind fill (pair_for, fill), the
  bank fill (draw_pairs), the near-duplicate measure (grams, jacc, NEAR_DUP 0.45), the frames F01-F12 (the 16 stamped
  topics per frame unchanged), the banned-question list, the verifier flags and blocking flags, and the GO bar
  (kept(written) >= 50% of written). The clean keep rule is the stamped rule, line for line.
Extended (the only changes):
  * near-duplicates are checked in BOTH written orders (first + question OR second + question, Jaccard >= 0.45):
      - validate: within the unit, against the other G3 units, and against every stamped candidate (the 30 v5 seeds and
        the 192 stamped written templates, kept or dropped) -> FAIL [neardup], the writer rewrites;
      - close: against every template in the stamped BANK (the 190 kept in subrole/clean/*.json) -> REPORTED and DROPPED
        (never put in a blind file; clean records it as dropped; it counts as a written template in the GO bar);
      - gen: the same check again (drop + report), and the within-G3 cross-unit pairs are reported (nothing is fitted
        on fold -2, so they share no fold rule).
  * gen: fold = -2 on every row, template_source = written_g3, source = subrole_g3, row ids sr:en:written_g3:...
  * the stamped files are md5-pinned (STAMPED_PIN) and refused if they drift.

Commands
  python3 subrole_g3.py manifest                 # deterministic: units SR-u17..u19 (refuses to move a unit once written)
  python3 subrole_g3.py status [--next]          # every unit / group / clean from the files on disk; --next = the next args
  python3 subrole_g3.py next <U>                 # the writer's unit spec (JSON): cells, output_path, attempt
  python3 subrole_g3.py validate <path>          # the writer's deterministic validator; ends "VALIDATE ok 12" or FAIL lines
  python3 subrole_g3.py close G3                 # accept every unit, drop near-twins of the stamped bank, build blind + key
  python3 subrole_g3.py format <G> [<out>]       # the verifier's format gate (knows no labels)
  python3 subrole_g3.py clean G3                 # deterministic keep / drop per template from the blind verdicts; GO bar
  python3 subrole_g3.py gen [--out bank]         # the increment bank bank/dump/SUBROLE_G3.jsonl (fold -2)
  python3 subrole_g3.py selftest                 # every check seen passing AND failing
"""
import sys
sys.dont_write_bytecode = True
import argparse, ast, glob, hashlib, importlib.util, json, math, os, random, re, shutil, tempfile
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
SIGNED = os.path.dirname(HERE)
STAMPED = os.path.join(SIGNED, 'subrole')          # READ ONLY: no code path in this file writes under it
SEED = 'subrole-2026-10-01'                        # the stamped seed: fills are keyed by template key (written_g3:...)
CUE = 'The answer is'
FORBID = ['/v5e2/', 'svamp', 'singleeq', 'gsm8k', 'key.json', 'key_withheld', 'answers_withheld', 'haiku_ab', 'redteam',
          'wildtest', 'wildeval']
N_PER_UNIT = 12
LO, HI = 2, 99                 # DR-ROLE's number range
TARGET_ROWS = 3000             # pairs per template = max(8, min(60, round(TARGET / (4 K)))), the stamped formula
NEAR_DUP = 0.45                # char-4-gram Jaccard at or above this = near duplicate (the stamped value)
GO_FRAC = 0.50                 # a chunk is GO iff kept(written) >= 50% of its written templates (the stamped bar)
FOLD_G3 = -2                   # increment rows: never used for fitting (the stamped bank uses folds 0..4)
TSRC = 'written_g3'
# the stamped files this increment reads, pinned (SUBROLE_CODE.md5 of the stamped dir; BANK.md5; PREREG_subrole.md5)
STAMPED_PIN = {
    'clean/P1.json': 'c35ce359eead16258d455dce41e2cc8f',
    'clean/G1.json': 'b467ec9440bd4195e45635c3f295f1df',
    'clean/G2.json': 'f1edc6839815f989136b8ca0f3fd9a0e',
    'seeds/v5_signed_sub_en.json': '4fb2817b6de1406dc0f0cbf7127a1a3f',
}
STAMPED_SUBROLE_PY_MD5 = '05446a450ef5811e8cc95a5c38c8158b'   # this repo's banks/subrole/subrole.py (project copy 3fb169ad)
STAMPED_BANK_MD5 = 'e75e670a85eb1be6d2d62c8fa8dccce8'
STAMPED_PREREG_MD5 = '2ebad611c7ff9b05dc3c5550dd3b3f2d'
STAMPED_KEPT = 190

FRAMES = [
    ('F01', 'temperature change between two times; the minuend is the LATER reading (later minus earlier)',
     ['greenhouse', 'freezer', 'lake water', 'mountain hut', 'desert night', 'aquarium', 'attic', 'ski slope',
      'garden soil', 'lab sample', 'car interior', 'beach sand', 'cave', 'city street', 'bread oven', 'weather balloon']),
    ('F02', 'money in versus money out over a period; the minuend is the money IN (balance = in minus out)',
     ['school lunch card', 'club fund', 'savings jar', 'phone credit', 'shop till', 'class trip fund', 'charity box',
      'game wallet', 'bus pass', 'bakery cashbox', 'allowance', 'market stall', 'toll card', 'arcade card', 'cafe tab',
      'scout troop kitty']),
    ('F03', 'a height above a reference level, then a move down; the minuend is the STARTING height (height now = start '
            'minus descent; below the reference is negative)',
     ['hiker above a lake', 'hot-air balloon above a field', 'lift above the lobby', 'drone above a rooftop',
      'climber above base camp', 'kite above a hill', 'crane hook above a dock', 'bucket above a well rim',
      'window cleaner above the street', 'cable car above the station', 'bird above a cliff edge',
      'paraglider above a beach', 'gondola above a river', 'tree surgeon above the lawn', 'diver above a pool deck',
      'rope ladder above a deck']),
    ('F04', 'points won versus points lost in a contest; the minuend is the points WON (net score = won minus lost)',
     ['quiz team', 'chess club', 'card game', 'video game level', 'spelling bee', 'darts league', 'hockey season',
      'debating team', 'basketball league', 'trivia app', 'board game', 'bowling night', 'tennis ladder',
      'rugby season', 'robotics contest', 'football season']),
    ('F05', 'stock received versus stock sent out in a period; the minuend is the amount RECEIVED (net change = received '
            'minus sent out)',
     ['warehouse', 'bookstore', 'pharmacy', 'toy shop', 'bike shop', 'seed bank', 'shoe store', 'florist',
      'hardware store', 'flour store', 'library', 'animal shelter', 'car park', 'hotel', 'museum cloakroom', 'ferry deck']),
    ('F06', 'an actual amount versus a planned target; the minuend is the ACTUAL amount (actual minus target; a '
            'shortfall is negative)',
     ['sales target', 'reading goal', 'daily steps', 'fundraising drive', 'factory quota', 'recycling target',
      'practice minutes', 'volunteer hours', 'tree planting', 'crop yield', 'class attendance', 'savings plan',
      'ticket sales', 'cycling distance', 'water budget', 'swimming laps']),
    ('F07', 'a count at an earlier time versus a later time; the minuend is the LATER count (change from earlier to '
            'later = later minus earlier)',
     ['town population', 'club members', 'school enrolment', 'bird count', 'orchard trees', 'bus riders', 'app users',
      'beehives', 'lake fish', 'newsletter subscribers', 'market stalls', 'festival visitors', 'factory workers',
      'choir singers', 'farm cows', 'newspaper readers']),
    ('F08', 'money earned versus money spent by a venture; the minuend is the money EARNED (profit = earned minus spent; '
            'a loss is negative)',
     ['lemonade stand', 'bake sale', 'car wash', 'school play', 'craft fair', 'food truck', 'concert', 'garage sale',
      'plant nursery', 'tutoring service', 'dog walking', 'fishing boat', 'cinema night', 'book fair', 'ice rink',
      'pottery class']),
    ('F09', 'a move forward and then a move back along a line; the minuend is the FORWARD move (position = forward minus '
            'back; behind the start is negative)',
     ['toy robot on a track', 'frog on a path', 'train on a line', 'game token on a board', 'snail on a wall',
      'toy car on a ramp', 'runner on a track', 'cursor on a screen', 'tram on a street', 'ant on a branch',
      'sled on a slope', 'crab on a beach', 'cart on a rail', 'rowing boat on a canal', 'skater on a rink',
      'tortoise in a garden']),
    ('F10', 'a weight at an earlier time versus a later time; the minuend is the LATER weight (change = later minus '
            'earlier; a loss is negative)',
     ['puppy', 'kitten', 'sack of rice', 'pumpkin', 'bread dough', 'beehive', 'harvest crate', 'boxer', 'piglet',
      'watermelon', 'compost bin', 'cheese wheel', 'sourdough starter', 'hay bale', 'firewood stack', 'parcel']),
    ('F11', 'a water level above a mark, then a fall; the minuend is the STARTING level (level now = start minus fall; '
            'below the mark is negative)',
     ['river gauge', 'reservoir', 'canal lock', 'pond', 'rain barrel', 'fish tank', 'harbour wall', 'well',
      'swimming pool', 'fountain basin', 'flood wall', 'irrigation tank', 'lake dock', 'water tower', 'beaver dam',
      'mill race']),
    ('F12', 'votes for versus votes against a proposal; the minuend is the votes FOR (margin = for minus against; a '
            'defeat is negative)',
     ['student council', 'town meeting', 'book club', 'team captain', 'park bench', 'lunch menu', 'club rule',
      'school mascot', 'class trip', 'band name', 'garden plan', 'library hours', 'bus route', 'movie night',
      'uniform colour', 'festival theme']),
]
N_STAMPED_TOPICS = 16
# G3: three NEW topics per frame (topic indices 16, 17, 18 = units SR-u17, u18, u19); disjoint from every stamped topic
# of every frame (selftest). The stamped unit_spec rule topic = tops[(unit - 1) % len(tops)] is unchanged.
TOPICS_G3 = {
    'F01': ['hospital incubator', 'sauna', 'wine cellar'],
    'F02': ['robotics team account', 'hiking club purse', 'family holiday fund'],
    'F03': ['helicopter above a helipad', 'mountain goat above a stream', 'stage platform above the orchestra pit'],
    'F04': ['archery club', 'volleyball season', 'cricket season'],
    'F05': ['food bank', 'garden centre', 'stationery cupboard'],
    'F06': ['blood donation drive', 'newspaper deliveries', 'meals served'],
    'F07': ['swallows in a barn', 'library members', 'marathon entrants'],
    'F08': ['puppet show', 'charity run', 'snow shovelling business'],
    'F09': ['bead on an abacus wire', 'model boat on a pond', 'squirrel on a fence'],
    'F10': ['lamb', 'foal', 'sack of potatoes'],
    'F11': ['bathtub', "ship's ballast tank", 'paddling pool'],
    'F12': ['skate park plan', 'class pet', 'cafeteria playlist'],
}
FRAMES = [(f, d, tops + TOPICS_G3[f]) for f, d, tops in FRAMES]
FRAME_IDS = [f for f, _, _ in FRAMES]
CHUNKS = {
    'G3': dict(units=['SR-u17', 'SR-u18', 'SR-u19'], groups=['SRV-g3a', 'SRV-g3b', 'SRV-g3c'], seeds=False),
}
NUMBER_WORDS = ('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen '
                'seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred hundreds '
                'thousand thousands million millions billion dozen dozens half halves twice thrice double triple '
                'quadruple single couple pair pairs once first second third fourth fifth sixth seventh eighth ninth '
                'tenth eleventh twelfth').split()      # v5_common.EN_EXTRA_NUMBER_WORDS + the cardinals + multipliers
BANNED_Q = [(r'\bhow (?:many|much) (?:more|fewer|less)\b(?! or)', 'how many more / fewer (positive-only)'),
            (r'\bby how much\b', 'by how much (asks a magnitude)'),
            (r'\bleft\b', 'left (positive-only)'), (r'\bremain', 'remain (positive-only)'),
            (r'\bhow far apart\b', 'how far apart (undirected)'), (r'\bgap\b', 'gap (undirected)'),
            (r'\bdifference\b', 'difference (read as a magnitude, the oosprose audit)'),
            (r'\baltogether\b|\bin total\b|\btotal\b|\bin all\b', 'a total (reads as addition)'),
            (r'\babsolute\b', 'absolute (undirected)'), (r'\bhow many times\b', 'how many times (division)')]
VFLAGS = ('unnatural', 'ungrammatical', 'ambiguous', 'hidden_operand', 'another_pair_answers', 'magnitude_only',
          'cue_mismatch', 'number_dependent_grammar', 'not_single_step', 'role_only_in_question', 'other')
VBLOCK = ('unnatural', 'ungrammatical', 'ambiguous', 'hidden_operand', 'another_pair_answers', 'magnitude_only',
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


class Ctx:
    """root = the G3 working dir (written); stamped = the stamped subrole dir (READ ONLY); pins = STAMPED_PIN, or None
       for a selftest fixture stamped dir"""
    def __init__(self, root, stamped=STAMPED, pins=STAMPED_PIN):
        self.root = root
        self.stamped = stamped
        self.pins = pins

    def p(self, *a):
        out = os.path.join(self.root, *a)
        if os.path.abspath(out).startswith(os.path.abspath(self.stamped) + os.sep):
            sys.exit(f"REFUSE: {out} is under the stamped dir (read only)")
        return out

    def s(self, *a):
        return os.path.join(self.stamped, *a)


def unit_index(uid):
    return int(uid.split('-u')[1])


def chunk_of(uid):
    c = [c for c, d in CHUNKS.items() if uid in d['units']]
    if not c:
        sys.exit(f"REFUSE: {uid} is not a G3 unit ({CHUNKS['G3']['units']})")
    return c[0]


# ------------------------------------------------------------------------------------------------- the stamped bank
def stamped_check_pins(ctx):
    if ctx.pins is None:
        return
    for rel, want in ctx.pins.items():
        p = ctx.s(rel)
        if not os.path.exists(p):
            sys.exit(f"REFUSE: stamped file {p} missing")
        got = md5f(p)
        if got != want:
            sys.exit(f"REFUSE: stamped file {rel} md5 {got} != pinned {want} (the stamped bank must not move)")


def stamped_kept(ctx):
    """every template in the stamped BANK: the kept list of each stamped clean/*.json (190 in the real dir)"""
    stamped_check_pins(ctx)
    out = []
    for p in sorted(glob.glob(ctx.s('clean', '*.json'))):
        c = loadj(p)
        if c.get('verdict') != 'GO':
            continue
        for t in c['kept']:
            out.append(dict(tkey=t['tkey'], first=t['first'], second=t['second'], question=t['question']))
    if ctx.pins is not None and len(out) != STAMPED_KEPT:
        sys.exit(f"REFUSE: the stamped clean files hold {len(out)} kept templates, not {STAMPED_KEPT}")
    return out


def stamped_candidates(ctx):
    """every stamped CANDIDATE (kept or dropped): the seeds file + stamped accept/*.json (when present, the laptop) +
       the kept list (which covers the kept ones where accept/ is absent, e.g. a cluster copy)"""
    seen = {}
    for t in stamped_kept(ctx):
        seen[t['tkey']] = t
    sp = ctx.s('seeds', 'v5_signed_sub_en.json')
    if os.path.exists(sp):
        for s in loadj(sp)['seeds']:
            seen.setdefault(f"v5:{s['tid']}", dict(tkey=f"v5:{s['tid']}", first=s['first'], second=s['second'],
                                                  question=s['question']))
    for f in sorted(glob.glob(ctx.s('accept', '*.json'))):
        for t in loadj(f)['items']:
            seen.setdefault(f"written:{t['tid']}", dict(tkey=f"written:{t['tid']}", first=t['first'], second=t['second'],
                                                       question=t['question']))
    return [seen[k] for k in sorted(seen)]


def g12(t):
    """the two near-duplicate signatures: first + question, second + question"""
    return grams(t['first'] + ' ' + t['question']), grams(t['second'] + ' ' + t['question'])


def neardup_pairs(A, B, same_ok=None):
    """every (a, b) with Jaccard >= NEAR_DUP on first + question OR second + question; A, B lists of dicts with tkey"""
    out = []
    GA = [(a, g12(a)) for a in A]
    GB = [(b, g12(b)) for b in B]
    for a, (a1, a2) in GA:
        for b, (b1, b2) in GB:
            if a['tkey'] == b['tkey'] or (same_ok and same_ok(a, b)):
                continue
            j1, j2 = jacc(a1, b1), jacc(a2, b2)
            if j1 >= NEAR_DUP or j2 >= NEAR_DUP:
                out.append(dict(a=a['tkey'], b=b['tkey'], j_first=round(j1, 3), j_second=round(j2, 3)))
    return out


def max_j(A, B):
    """the highest Jaccard of any A template to any B template, per order (reported)"""
    m1 = m2 = (0.0, None, None)
    GB = [(b, g12(b)) for b in B]
    for a in A:
        a1, a2 = g12(a)
        for b, (b1, b2) in GB:
            j1, j2 = jacc(a1, b1), jacc(a2, b2)
            if j1 > m1[0]:
                m1 = (round(j1, 3), a['tkey'], b['tkey'])
            if j2 > m2[0]:
                m2 = (round(j2, 3), a['tkey'], b['tkey'])
    return dict(first=list(m1), second=list(m2))


# ------------------------------------------------------------------------------------------------- manifest
def unit_spec(uid):
    k = unit_index(uid) - 1
    cells = [dict(cell=i + 1, frame=f, frame_desc=d, topic=tops[k % len(tops)]) for i, (f, d, tops) in enumerate(FRAMES)]
    return dict(unit_id=uid, chunk=chunk_of(uid), n_templates=N_PER_UNIT, cells=cells,
                tid_pattern=f"{uid}-NN (NN = cell number 01..12)")


def cmd_manifest(ctx):
    idx_p = ctx.p('manifest', 'MANIFEST_INDEX.json')
    K = stamped_kept(ctx)
    units = {}
    for C, d in CHUNKS.items():
        for u in d['units']:
            units[u] = dumpj(unit_spec(u), ctx.p('manifest', 'units', f'{u}.json'))
    idx = dict(seed=SEED, chunks=CHUNKS, n_per_unit=N_PER_UNIT, frames=FRAME_IDS, topics_g3=TOPICS_G3, units_md5=units,
               go_bar=dict(go_frac=GO_FRAC), fold=FOLD_G3, template_source=TSRC, near_dup=NEAR_DUP,
               stamped=dict(dir='signed/subrole', pins=ctx.pins, kept=len(K), subrole_py_md5=STAMPED_SUBROLE_PY_MD5,
                            bank_md5=STAMPED_BANK_MD5, prereg_md5=STAMPED_PREREG_MD5))
    if os.path.exists(idx_p) and loadj(idx_p) != idx:
        sys.exit('REFUSE: manifest/MANIFEST_INDEX.json exists with different content (units are frozen once written)')
    m = dumpj(idx, idx_p)
    return idx, m


# ------------------------------------------------------------------------------------------------- validator
# words / grams / jacc / item_problems: VERBATIM from the stamped subrole.py (the selftest compares the AST)
def words(t):
    return re.findall(r"[a-z]+(?:'[a-z]+)?", t.lower())


def grams(t, n=4):
    s = re.sub(r'\s+', ' ', re.sub(r'\{[MS]\}', '#', t.lower())).strip()
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def jacc(a, b):
    return len(a & b) / max(1, len(a | b))


def item_problems(it, cell=None, uid=None):
    """deterministic checks of one template; returns [(code, message)]"""
    p = []
    need = ('tid', 'frame', 'topic', 'first', 'second', 'question', 'sign_convention', 'negative_reading')
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
    q = it['question']
    if '{' in q or '}' in q:
        p.append(('slots', 'the question must not contain a slot or a brace'))
    full = ' '.join((it['first'], it['second'], q))
    if re.search(r'\d', full) or re.search(r'[+\-*/=%×÷−]\s*\{', full):
        p.append(('digit', 'no digits and no arithmetic symbols anywhere'))
    low = full.lower()
    nw = sorted({w for w in NUMBER_WORDS if re.search(r"(?<![\w'’])%s(?![\w'’])" % re.escape(w), low)})
    if nw:
        p.append(('numberword', f'number words give hidden operands: {", ".join(nw)}'))
    if CUE.lower() in low:
        p.append(('cue', 'do not write the cue "The answer is"; the generator adds it'))
    if '\n' in full or '  ' in full:
        p.append(('format', 'no line breaks or double spaces'))
    if not q.rstrip().endswith('?'):
        p.append(('question', 'the question must end with "?"'))
    for rx, why in BANNED_Q:
        if re.search(rx, q.lower()):
            p.append(('banned', f'question: {why}'))
    if re.search(r'\bchange\b', q.lower()) and not re.search(r'\bfrom\b|\bnet\b|\bminus\b|\bover the\b', q.lower()):
        p.append(('direction', 'a "change" question must state its direction ("from ... to ...", "net", "minus", "over the ...")'))
    for key, cap in (('first', 45), ('second', 45), ('question', 30)):
        if len(words(it[key])) > cap:
            p.append(('length', f'{key} has {len(words(it[key]))} words (cap {cap})'))
    w1 = {w for w in words(it['first']) if len(w) >= 3}
    w2 = {w for w in words(it['second']) if len(w) >= 3}
    if jacc(w1, w2) < 0.6:
        p.append(('reorder', f'second must reorder first, not rewrite it (content-word overlap {jacc(w1, w2):.2f} < 0.60)'))
    if 'minus' not in it['sign_convention'].lower():
        p.append(('sign', 'sign_convention must say "<minuend thing> minus <subtrahend thing>"'))
    return p


def validate_file(ctx, path, quiet=False):
    """returns (ok, problems). Cross-checks: the unit spec; near-duplicates in BOTH orders within the file, against the
       other accepted G3 units and against every stamped candidate (seeds + stamped written, kept or dropped)."""
    refuse_forbidden(path)
    probs = []
    try:
        d = loadj(path)
    except Exception as e:
        return False, [('json', f'not JSON: {e}')]
    uid = d.get('unit_id') if isinstance(d, dict) else None
    if uid not in [u for c in CHUNKS.values() for u in c['units']]:
        return False, [('schema', 'top level must be {"unit_id": "SR-uNN", "items": [...]} with a G3 unit id')]
    spec = unit_spec(uid)
    items = d.get('items')
    if not isinstance(items, list) or len(items) != N_PER_UNIT:
        return False, [('schema', f'items must be a list of {N_PER_UNIT} templates, one per cell in cell order')]
    for it, cell in zip(items, spec['cells']):
        if not isinstance(it, dict):
            probs.append((f'cell {cell["cell"]:02d}', 'schema', 'not an object')); continue
        for code, m in item_problems(it, cell, uid):
            probs.append((f"cell {cell['cell']:02d}", code, m))
    texts = [(it.get('tid', '?'), grams(it.get('first', '') + ' ' + it.get('question', '')),
              grams(it.get('second', '') + ' ' + it.get('question', ''))) for it in items if isinstance(it, dict)]
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            s1, s2 = jacc(texts[i][1], texts[j][1]), jacc(texts[i][2], texts[j][2])
            if s1 >= NEAR_DUP or s2 >= NEAR_DUP:
                probs.append((texts[j][0], 'neardup', f'char-4-gram Jaccard {s1:.2f} (first + question) / {s2:.2f} '
                              f'(second + question) >= {NEAR_DUP} with {texts[i][0]}'))
    others = [(t['tkey'], *g12(t)) for t in stamped_candidates(ctx)]
    for f in sorted(glob.glob(ctx.p('accept', '*.json'))):
        a = loadj(f)
        if a['unit_id'] != uid:
            others += [(f"{TSRC}:{t['tid']}", *g12(t)) for t in a['items']]
    for tid, g1, g2 in texts:
        for otk, o1, o2 in others:
            s1, s2 = jacc(g1, o1), jacc(g2, o2)
            if s1 >= NEAR_DUP or s2 >= NEAR_DUP:
                probs.append((tid, 'neardup', f'char-4-gram Jaccard {s1:.2f} (first + question) / {s2:.2f} '
                              f'(second + question) >= {NEAR_DUP} with existing {otk}'))
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
                    brief=ctx.p('ADDON_subrole_g3_writer.md'))
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
            P(f'NEXT wait: {C} is NO-GO; the project lead decides (retry with new units, or stop)'); return None
        todo = [u for u, s in us.items() if s in ('pending', 'invalid')]
        if todo:
            a = {'chunk': C} if len(todo) == len(us) else {'chunk': C, 'units': todo}
        elif any(s != 'accepted' for s in us.values()):
            a = {'chunk': C, 'stages': ['close', 'verify', 'clean']}
        else:
            gtodo = [G for G, s in gs.items() if s != 'done']
            a = {'chunk': C, 'stages': ['verify', 'clean'], 'groups': gtodo} if gtodo else {'chunk': C, 'stages': ['clean']}
        P('NEXT ' + json.dumps(a)); return a
    P('NEXT gen (G3 is GO: `subrole_g3.py gen`, then fill the [FILL AT GEN] lines of ADDENDUM_subrole_g3.md)')
    return 'gen'


# ------------------------------------------------------------------------------------------------- close (accept + blind)
# pair_for / fill: VERBATIM from the stamped subrole.py
def pair_for(tkey):
    rng = random.Random(f'{SEED}:verify-pair:{tkey}')
    while True:
        x = rng.randrange(LO + 3, HI + 1)
        y = rng.randrange(LO, x - 2)
        if x != y:
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
            T.append(dict(it, source=TSRC, unit=u, tkey=f"{TSRC}:{it['tid']}"))
    # near-twins of the stamped BANK (both orders): reported and DROPPED here (never shown to a verifier)
    SK = stamped_kept(ctx)
    tw = neardup_pairs(T, SK)
    excl = sorted({x['a'] for x in tw})
    # cross-unit near duplicates inside G3 (both orders): reported, never dropped (fold -2: nothing is fitted on them)
    nd = neardup_pairs(T, T, same_ok=lambda a, b: a['unit'] == b['unit'] or a['tkey'] > b['tkey'])
    ndp = dict(chunk=C, rule=f'char-4-gram Jaccard >= {NEAR_DUP} on first + question OR second + question',
               vs_stamped_bank=dict(n_stamped=len(SK), pairs=tw, dropped=excl, max_j=max_j(T, SK)),
               within_g3_cross_unit=dict(pairs=nd, note='reported only'))
    npath = ctx.p('manifest', 'groups', f'{C}.neardup.json')
    nb = (json.dumps(ndp, indent=1, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
    if os.path.exists(npath) and open(npath, 'rb').read() != nb:
        P(f"CLOSE FAIL manifest/groups/{C}.neardup.json exists with different content"); return False
    os.makedirs(os.path.dirname(npath), exist_ok=True)
    open(npath, 'wb').write(nb)
    for x in tw:
        P(f"  NEAR-TWIN of the stamped bank, DROPPED: {x['a']} ~ {x['b']} J first {x['j_first']} / second {x['j_second']}")
    T2 = [t for t in T if t['tkey'] not in excl]
    order = sorted(T2, key=lambda t: t['tid'])
    random.Random(f'{SEED}:deal:{C}').shuffle(order)
    groups = {G: [] for G in d['groups']}
    for i, t in enumerate(order):
        groups[d['groups'][i % len(d['groups'])]].append(t)
    for G, ts in groups.items():
        texts = []
        for t in ts:
            tkey = t['tkey']
            x, y = pair_for(tkey)
            for wo, key in (('F', 'first'), ('S', 'second')):
                for half, (m, s) in (('a>b', (x, y)), ('a<b', (y, x))):
                    texts.append(dict(text=fill(t, key, m, s), tkey=tkey, tid=t['tid'], source=t['source'],
                                      written_order=wo, half=half, M=m, S=s, gold=m - s,
                                      minuend_name='n1' if wo == 'F' else 'n2'))
        random.Random(f'{SEED}:shuffle:{G}').shuffle(texts)
        blind, key = [], {}
        for i, x in enumerate(texts):
            iid = f'{G}-t{i + 1:03d}'
            nums = re.findall(r'\d+', x['text'])
            if nums != ([str(x['M']), str(x['S'])] if x['written_order'] == 'F' else [str(x['S']), str(x['M'])]):
                P(f"CLOSE FAIL {x['tid']}: the filled text has numerals {nums}"); return False
            blind.append(dict(id=iid, text=x['text'], numbers={f'n{j + 1}': v for j, v in enumerate(nums)}))
            key[iid] = {k: x[k] for k in ('tkey', 'tid', 'source', 'written_order', 'half', 'M', 'S', 'gold', 'minuend_name')}
        bp = ctx.p('blind', f'{G}.blind.json')
        newb = (json.dumps(dict(verifier_unit=G, language='English', cue=CUE, n_items=len(blind), items=blind),
                           indent=1, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
        if os.path.exists(bp) and open(bp, 'rb').read() != newb:
            P(f"CLOSE FAIL blind/{G}.blind.json exists with different content (never rebuilt under a verifier)"); return False
        os.makedirs(os.path.dirname(bp), exist_ok=True)
        open(bp, 'wb').write(newb)
        km = dumpj(key, ctx.p('blind_key', f'{G}.key.json'))
        dumpj(dict(group=G, chunk=C, templates=sorted(t['tkey'] for t in ts), n_texts=len(blind),
                   blind_md5=md5b(newb), key_md5=km), ctx.p('manifest', 'groups', f'{G}.json'))
        P(f"BLIND ok {len(blind)} texts -> blind/{G}.blind.json ({len(ts)} templates)")
    P(f"CLOSE ok {C}: {len(T)} templates written, {len(excl)} dropped as near-twins of the {len(SK)}-template stamped bank, "
      f"{len(T2)} to the verifiers; cross-unit near-duplicate pairs inside G3 {len(nd)} (reported only); nearest stamped "
      f"J first {ndp['vs_stamped_bank']['max_j']['first'][0]} / second {ndp['vs_stamped_bank']['max_j']['second'][0]}")
    return True


# ------------------------------------------------------------------------------------------------- verifier format
# check_format: VERBATIM from the stamped subrole.py
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
        miss = [f for f in ('op', 'operands', 'role', 'answer', 'negative_natural', 'flags', 'note') if f not in x]
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
        if isinstance(x['answer'], str) and re.fullmatch(r'-?\d+(/\d+)?', x['answer'].strip()) and not x['answer'].endswith('/0'):
            ans = Fraction(x['answer'].strip())
        elif x['answer'] != 'none':
            p('answer must be an integer, p/q, or "none"')
        if x['op'] == 'other':
            if x['operands'] is not None or x['role'] is not None or x['negative_natural'] is not None:
                p('op "other" needs operands null, role null, negative_natural null')
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
        if x['op'] == 'sub' and ans is not None and ans < 0:
            if x['negative_natural'] not in (True, False):
                p('a negative subtraction answer needs negative_natural true or false')
        elif x['negative_natural'] is not None:
            p('negative_natural must be null unless op is sub and the answer is negative')
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
    npath = ctx.p('manifest', 'groups', f'{C}.neardup.json')
    if not os.path.exists(npath):
        P(f"CLEAN FAIL {C} has no close record (manifest/groups/{C}.neardup.json)"); return None
    nd = loadj(npath)['vs_stamped_bank']
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
            tpl[f"{TSRC}:{it['tid']}"] = dict(it, source=TSRC, unit=u)
    kept, dropped = [], []
    for tk in sorted(nd['dropped']):                 # near-twins of the stamped bank: dropped at close, no blind texts
        dropped.append(dict(tkey=tk, reasons=[f"near-twin of the stamped bank: {x['b']} (J first {x['j_first']} / second "
                                              f"{x['j_second']})" for x in nd['pairs'] if x['a'] == tk], notes=[]))
    for tk in sorted(per):
        # ---- the stamped keep rule, line for line
        why = []
        rows = per[tk]
        if len(rows) != 4:
            why.append(f'{len(rows)} texts, expected 4')
        for k, x in rows:
            tag = f"{k['written_order']}{k['half']}"
            if x['op'] != 'sub':
                why.append(f'{tag}: op {x["op"]}')
                continue
            if x['role'] != k['minuend_name']:
                why.append(f'{tag}: role {x["role"]} is not the minuend {k["minuend_name"]}')
            if sorted(x['operands']) != ['n1', 'n2']:
                why.append(f'{tag}: operands {x["operands"]}')
            if Fraction(x['answer']) != k['gold']:
                why.append(f'{tag}: answer {x["answer"]} != {k["gold"]}')
            if k['half'] == 'a<b' and x['negative_natural'] is not True:
                why.append(f'{tag}: a negative answer does not read naturally')
            bl = [f for f in x['flags'] if f in VBLOCK]
            if bl:
                why.append(f'{tag}: flags {bl}')
        roq = sum('role_only_in_question' in x['flags'] for _, x in rows)
        rec = dict(tpl[tk], tkey=tk, role_only_in_question=roq)
        if why:
            dropped.append(dict(tkey=tk, reasons=why, notes=[x['note'] for _, x in rows if x['note']]))
        else:
            kept.append(rec)
    missing = sorted(set(tpl) - set(per) - set(nd['dropped']))
    if missing:
        P(f"CLEAN FAIL templates with no verdict and no close drop: {missing[:5]}"); return None
    nw = len(tpl)
    kw = len(kept)
    go = kw >= math.ceil(GO_FRAC * nw)
    res = dict(chunk=C, verdict='GO' if go else 'NO-GO', kept=kept, dropped=dropped, kept_written=[kw, nw],
               dropped_near_twin_of_stamped=len(nd['dropped']), bar=f"kept(written) >= {GO_FRAC:.0%} of written")
    dumpj(res, ctx.p('clean', f'{C}.json'))
    if not quiet:
        for dr in dropped:
            P(f"  DROP {dr['tkey']}: {'; '.join(dr['reasons'][:4])}")
        P(f"CLEAN ok {C} kept {len(kept)}/{nw} written ({len(nd['dropped'])} dropped as near-twins of the stamped bank) "
          f"-> {res['verdict']} ({res['bar']})")
    return res


# ------------------------------------------------------------------------------------------------- gen (stamped port)
# draw_pairs: VERBATIM from the stamped subrole.py
def draw_pairs(rng, n):
    out, seen = [], set()
    while len(out) < n:
        if len(out) % 2 == 0:                                   # near: the two numbers 1..9 apart
            y = rng.randrange(LO, HI - 1); x = y + rng.randrange(1, 10); kind = 'near'
        else:                                                   # far: 10 or more apart
            x = rng.randrange(LO + 10, HI + 1); y = rng.randrange(LO, x - 9); kind = 'far'
        if not (LO <= y < x <= HI) or (x, y) in seen:
            continue
        seen.add((x, y)); out.append((x, y, kind))
    return out


def cmd_gen(ctx, out=None, quiet=False):
    out = out or ctx.p('bank')
    cp = ctx.p('clean', 'G3.json')
    if not os.path.exists(cp):
        sys.exit('REFUSE: no clean/G3.json (run the chunk first)')
    c = loadj(cp)
    if c['verdict'] != 'GO':
        sys.exit(f'REFUSE: clean/G3.json is {c["verdict"]}; only a GO chunk enters the bank')
    K0 = [dict(t) for t in c['kept']]
    SK = stamped_kept(ctx)
    tw = neardup_pairs(K0, SK)                       # again at gen: a near-twin of the stamped bank never enters
    twk = sorted({x['a'] for x in tw})
    K = [t for t in K0 if t['tkey'] not in twk]
    if len(K) < 1:
        sys.exit('REFUSE: no kept templates')
    npair = max(8, min(60, round(TARGET_ROWS / (4 * len(K)))))
    nd = neardup_pairs(K, K, same_ok=lambda a, b: a['tkey'] > b['tkey'])
    rows = []
    for t in sorted(K, key=lambda t: t['tkey']):
        rng = random.Random(f"{SEED}:{t['tkey']}")
        for p, (x, y, kind) in enumerate(draw_pairs(rng, npair)):
            for wo, key, gidx in (('F', 'first', [0, 1]), ('S', 'second', [1, 0])):
                for half, (m, s) in (('a>b', (x, y)), ('a<b', (y, x))):
                    written = [m, s] if wo == 'F' else [s, m]
                    rows.append(dict(
                        row_id=f"sr:en:{t['tkey']}:{p:02d}:{wo}:{'lt' if half == 'a<b' else 'gt'}",
                        pair_key=f"sr:en:{t['tkey']}:{p:02d}", status='scored', lang='en', stratum='subrole',
                        source='subrole_g3', template_source=TSRC, template_id=t['tid'], frame=t['frame'],
                        topic=t['topic'], text=fill(t, key, m, s), answer_cue=CUE, op='subtraction', op_short='sub',
                        a=m, b=s, ans=m - s, swap=s - m, magnitude=abs(m - s), half=half, written_order=wo,
                        minuend_is_larger=half == 'a>b', minuend_written_first=wo == 'F',
                        written_smaller_first=written[0] < written[1], pair_kind=kind,
                        role_only_in_question=t.get('role_only_in_question', 0), list_values=written,
                        n_numerals_written=2, fold=FOLD_G3,
                        prov=dict(locator='block.digit_runs(tok, ids)', n_runs=2, gold_run_idx=gidx,
                                  run_lens=[len(str(v)) for v in written],
                                  note='gold_run_idx = [MINUEND run, SUBTRAHEND run] in written-run indices')))
    os.makedirs(os.path.join(out, 'dump'), exist_ok=True)
    blob = ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in rows).encode('utf-8')
    open(os.path.join(out, 'dump', 'SUBROLE_G3.jsonl'), 'wb').write(blob)
    cnt = lambda f: {str(v): sum(1 for r in rows if f(r) == v) for v in sorted({f(r) for r in rows}, key=str)}
    cen = dict(seed=SEED, increment='G3', fold=FOLD_G3, template_source=TSRC, kept=len(K),
               kept_after_close=len(K0), dropped_at_gen_near_twin_of_stamped=twk, pairs_per_template=npair, rows=len(rows),
               stamped=dict(kept=len(SK), bank_md5=STAMPED_BANK_MD5, prereg_md5=STAMPED_PREREG_MD5, pins=ctx.pins),
               near_dup_vs_stamped=dict(pairs=tw, max_j=max_j(K, SK)),
               near_dup_within_g3=dict(pairs=nd, note='reported only (fold -2, nothing is fitted on these rows)'),
               rows_by_half=cnt(lambda r: r['half']), rows_by_order=cnt(lambda r: r['written_order']),
               rows_by_smaller_first=cnt(lambda r: r['written_smaller_first']),
               rows_by_cell=cnt(lambda r: f"{r['written_order']}|{r['half']}"),
               rows_by_source=cnt(lambda r: r['template_source']), rows_by_frame=cnt(lambda r: r['frame']),
               rows_by_fold=cnt(lambda r: r['fold']), templates=sorted(t['tkey'] for t in K))
    cb = (json.dumps(cen, indent=1, sort_keys=True) + '\n').encode('utf-8')
    open(os.path.join(out, 'bank_census.json'), 'wb').write(cb)
    open(os.path.join(out, 'BANK.md5'), 'w').write(f"{md5b(blob)}  dump/SUBROLE_G3.jsonl\n{md5b(cb)}  bank_census.json\n")
    if not quiet:
        for x in tw:
            P(f"  NEAR-TWIN of the stamped bank, DROPPED at gen: {x['a']} ~ {x['b']} J {x['j_first']} / {x['j_second']}")
        P(f"GEN-SUBROLE-G3 kept {len(K)} templates ({len(twk)} near-twins of the stamped bank dropped at gen), {npair} pairs "
          f"each, rows {len(rows)} (a<b {cen['rows_by_half'].get('a<b')}, a>b {cen['rows_by_half'].get('a>b')}), fold "
          f"{FOLD_G3}, within-G3 near-dup pairs {len(nd)} (reported), md5 {md5b(blob)}")
    return rows, cen, md5b(blob)


# ------------------------------------------------------------------------------------------------- selftest
FIXTURES = {   # one known-good template per frame cell (selftest only; never shown to a writer) -- the stamped fixtures
    'F01': ('The greenhouse thermometer read {M} degrees at noon. At dawn it had read {S} degrees.',
            'The greenhouse thermometer read {S} degrees at dawn. At noon it read {M} degrees.',
            'What was the change in the greenhouse temperature from dawn to noon?', 'noon reading minus dawn reading'),
    'F02': ('This month the club fund took in {M} dollars from dues. It paid out {S} dollars for supplies.',
            'This month the club fund paid out {S} dollars for supplies. It took in {M} dollars from dues.',
            "What was the club fund's balance for the month, money taken in minus money paid out?", 'money in minus money out'),
    'F03': ('A hiker stood {M} metres above the lake shore. She then climbed down {S} metres.',
            'A hiker climbed down {S} metres from where she had stood, {M} metres above the lake shore.',
            'How many metres above the lake shore is the hiker now?', 'starting height minus descent'),
    'F04': ('Over the season the quiz team won {M} points in its rounds. It lost {S} points as penalties.',
            'Over the season the quiz team lost {S} points as penalties. It won {M} points in its rounds.',
            "What was the quiz team's net score for the season?", 'points won minus points lost'),
    'F05': ('This week the bookstore received {M} boxes of books. It sent out {S} boxes of books to other branches.',
            'This week the bookstore sent out {S} boxes of books to other branches. It received {M} boxes of books.',
            "What was the net change in the bookstore's stock of boxes this week?", 'boxes received minus boxes sent out'),
    'F06': ('The bakery actually sold {M} loaves on Friday. Its target for the day was {S} loaves.',
            "The bakery's target for Friday was {S} loaves. It actually sold {M} loaves.",
            "How far above its target were the bakery's Friday sales, counting a shortfall as below?", 'actual sales minus target'),
    'F07': ('The choir has {M} singers this year. Last year it had {S} singers.',
            'Last year the choir had {S} singers. This year it has {M} singers.',
            'What was the change in the number of choir singers from last year to this year?', 'this year minus last year'),
    'F08': ('The lemonade stand earned {M} dollars in sales on Saturday. Its lemons and cups cost {S} dollars.',
            "The lemonade stand's lemons and cups cost {S} dollars on Saturday. It earned {M} dollars in sales.",
            "What was the stand's profit for Saturday?", 'money earned minus money spent'),
    'F09': ('A toy robot rolled {M} centimetres forward along the track. Then it rolled {S} centimetres backward.',
            'A toy robot rolled {S} centimetres backward along the track, after it had rolled {M} centimetres forward.',
            'How far forward of its starting point did the robot end up?', 'forward distance minus backward distance'),
    'F10': ('The puppy weighed {M} ounces at the end of the month. At the start of the month it had weighed {S} ounces.',
            'At the start of the month the puppy weighed {S} ounces. At the end of the month it weighed {M} ounces.',
            "What was the change in the puppy's weight from the start of the month to the end?", 'end weight minus start weight'),
    'F11': ('On Monday the river gauge showed the water {M} centimetres above the warning mark. By Friday the level had '
            'dropped {S} centimetres.',
            'By Friday the river level had dropped {S} centimetres since Monday, when the gauge showed the water {M} '
            'centimetres above the warning mark.',
            'How many centimetres above the warning mark was the water on Friday?', 'Monday level minus the drop'),
    'F12': ('At the town meeting {M} people voted for the new park bench. Another {S} people voted against it.',
            'At the town meeting {S} people voted against the new park bench, while {M} people voted for it.',
            'What was the margin of votes for the bench over votes against it?', 'votes for minus votes against'),
}


def fixture_unit(uid):
    spec = unit_spec(uid)
    items = []
    for c in spec['cells']:
        f, s, q, sc = FIXTURES[c['frame']]
        items.append(dict(tid=f"{uid}-{c['cell']:02d}", frame=c['frame'], topic=c['topic'], first=f, second=s,
                          question=q, sign_convention=sc, negative_reading='a negative answer means the other way'))
    return dict(unit_id=uid, items=items)


MUTANTS = [   # (code the validator must raise, mutation of one item) -- the stamped mutants
    ('schema', lambda it: it.pop('sign_convention')),
    ('cell', lambda it: it.update(topic='something else')),
    ('slots', lambda it: it.update(first=it['first'].replace('{S}', 'some'))),
    ('order', lambda it: it.update(second=it['first'])),
    ('slots', lambda it: it.update(question=it['question'][:-1] + ' {M}?')),
    ('digit', lambda it: it.update(first=it['first'] + ' It had 3 helpers.')),
    ('numberword', lambda it: it.update(first=it['first'] + ' It had a dozen helpers.')),
    ('cue', lambda it: it.update(question=it['question'] + ' The answer is')),
    ('question', lambda it: it.update(question=it['question'].rstrip('?') + '.')),
    ('banned', lambda it: it.update(question='How many more are left now?')),
    ('banned', lambda it: it.update(question='What is the difference between the two readings?')),
    ('direction', lambda it: it.update(question='What was the change?')),
    ('length', lambda it: it.update(first=it['first'] + ' It was a very long and busy and noisy and cheerful and '
                                    'crowded and sunny and windy and bright and lively day for everyone there, with '
                                    'music and games and food and laughter and stories and songs from morning until '
                                    'the quiet evening finally came.')),
    ('reorder', lambda it: it.update(second='Things were quiet: {S} came, and later {M} went.')),
    ('sign', lambda it: it.update(sign_convention='later reading first')),
]

VERBATIM = ('words', 'grams', 'jacc', 'item_problems', 'pair_for', 'fill', 'check_format', 'draw_pairs', 'md5f', 'md5b',
            'refuse_forbidden', 'dumpj', 'loadj', 'fixture_unit')
SAME_CONST = ('SEED', 'CUE', 'FORBID', 'N_PER_UNIT', 'LO', 'HI', 'TARGET_ROWS', 'NEAR_DUP', 'GO_FRAC', 'NUMBER_WORDS',
              'BANNED_Q', 'VFLAGS', 'VBLOCK', 'VOPS')


def _fake_stamped(root, kept, seeds=()):
    """a selftest stamped dir: clean/X.json (GO) with the given kept templates, a seeds file; pins bypassed (None)"""
    dumpj(dict(chunk='X', verdict='GO', kept=[dict(t) for t in kept], dropped=[]), os.path.join(root, 'clean', 'X.json'))
    dumpj(dict(n=len(seeds), seeds=list(seeds)), os.path.join(root, 'seeds', 'v5_signed_sub_en.json'))
    return root


def cmd_selftest():
    res = []

    def check(name, ok):
        res.append((name, bool(ok)))
        P(f"  {'ok  ' if ok else 'FAIL'} {name}")
    # 0. identity with the stamped pipeline (source of every shared function, every shared constant)
    sp = os.path.join(STAMPED, 'subrole.py')
    sm = md5f(sp) if os.path.exists(sp) else None
    check(f'stamped subrole.py present and pinned ({(sm or "missing")[:8]} == {STAMPED_SUBROLE_PY_MD5[:8]})',
          sm == STAMPED_SUBROLE_PY_MD5)
    if sm == STAMPED_SUBROLE_PY_MD5:
        spec = importlib.util.spec_from_file_location('subrole_stamped_ro', sp)
        S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
        st_src = open(sp, encoding='utf-8').read(); my_src = open(os.path.abspath(__file__), encoding='utf-8').read()
        st_f = {n.name: ast.dump(n) for n in ast.parse(st_src).body if isinstance(n, ast.FunctionDef)}
        my_f = {n.name: ast.dump(n) for n in ast.parse(my_src).body if isinstance(n, ast.FunctionDef)}
        same = [n for n in VERBATIM if st_f.get(n) == my_f.get(n) and n in my_f]
        check(f'verbatim functions are AST-identical to the stamped subrole.py: {len(same)}/{len(VERBATIM)} '
              f'{sorted(set(VERBATIM) - set(same))}', len(same) == len(VERBATIM))
        cs = [c for c in SAME_CONST if getattr(S, c) == globals()[c]]
        check(f'shared constants identical (seed, cue, forbid, number range, near-dup 0.45, GO 50%, banned questions, '
              f'flags): {len(cs)}/{len(SAME_CONST)}', len(cs) == len(SAME_CONST))
        fr = all(f == g and d == e and tops[:N_STAMPED_TOPICS] == st for (f, d, tops), (g, e, st) in zip(FRAMES, S.FRAMES))
        check('frames F01-F12 and their 16 stamped topics unchanged (G3 topics appended at 16..18)',
              fr and len(FRAMES) == len(S.FRAMES) == 12)
        fx = all(FIXTURES[k] == S.FIXTURES[k] for k in S.FIXTURES) and len(FIXTURES) == len(S.FIXTURES)
        mu = len(MUTANTS) == len(S.MUTANTS) and all(a[0] == b[0] for a, b in zip(MUTANTS, S.MUTANTS))
        check('selftest fixtures and mutant codes identical to the stamped selftest', fx and mu)
    stt = {t for _, _, tops in FRAMES for t in tops[:N_STAMPED_TOPICS]}
    g3t = [t for f in FRAME_IDS for t in TOPICS_G3[f]]
    check(f'G3 topics: {len(set(g3t))}/36 distinct, none equal to any of the {len(stt)} stamped topics of any frame',
          len(set(g3t)) == 36 and not (set(g3t) & stt))
    us = {u: unit_spec(u) for u in CHUNKS['G3']['units']}
    check('unit specs: SR-u17/u18/u19 take topics 16/17/18 of each frame (stamped rule (unit - 1) % 19)',
          all(us[u]['cells'][i]['topic'] == TOPICS_G3[f][j] for j, u in enumerate(CHUNKS['G3']['units'])
              for i, f in enumerate(FRAME_IDS)))
    # 1. the real stamped bank: pins + 190 kept (read only)
    real = Ctx(os.path.join(tempfile.gettempdir(), 'nonexistent_g3_root'))
    try:
        SK = stamped_kept(real); okp = True
    except SystemExit as e:
        SK = []; okp = False; P(f"     {e}")
    check(f'the real stamped bank: pinned clean files verify and hold {len(SK)}/{STAMPED_KEPT} kept templates', okp and
          len(SK) == STAMPED_KEPT)
    bankp = os.path.join(STAMPED, 'bank', 'dump', 'SUBROLE.jsonl')
    real_row = None
    if os.path.exists(bankp):
        with open(bankp, encoding='utf-8') as fh:
            real_row = json.loads(fh.readline())
    if SK:
        nfx = len(neardup_pairs([dict(t, tkey=f"fx:{t['tid']}") for t in fixture_unit('SR-u17')['items']], SK))
        P(f"     (informational) the 12 selftest fixtures have {nfx} near-duplicate pair(s) with the real stamped bank, "
          f"so the selftest below runs on a fixture stamped dir")
    tmp = tempfile.mkdtemp(prefix='subrole_g3_st_')
    try:
        # a fixture stamped dir: one REAL stamped kept template (when available) + a synthetic one
        syn = dict(tkey='written:SR-u99-01', tid='SR-u99-01', first='A heron stood {M} paces from the reeds. It then '
                   'waded {S} paces.', second='A heron waded {S} paces, having stood {M} paces from the reeds.',
                   question='How many paces from the reeds is the heron now?')
        realk = dict(SK[0]) if SK else dict(syn, tkey='written:SR-u98-01')
        A = _fake_stamped(os.path.join(tmp, 'stampedA'), [realk, syn])
        ctx = Ctx(os.path.join(tmp, 'g3'), stamped=A, pins=None)
        i1, m1 = cmd_manifest(ctx)
        i2, m2 = cmd_manifest(Ctx(os.path.join(tmp, 'g3b'), stamped=A, pins=None))
        check(f'manifest deterministic ({m1[:8]} twice); units {len(i1["units_md5"])}/3', m1 == m2 and len(i1['units_md5']) == 3)
        try:
            idxp = ctx.p('manifest', 'MANIFEST_INDEX.json'); j = loadj(idxp); j['n_per_unit'] = 99; dumpj(j, idxp)
            cmd_manifest(ctx); refused = False
        except SystemExit:
            refused = True
        check('manifest refuses to move a frozen unit spec', refused)
        dumpj(i1, ctx.p('manifest', 'MANIFEST_INDEX.json'))
        try:
            ctx.p('..', 'stampedA', 'clean', 'X.json'); wr = False
        except SystemExit:
            wr = True
        check('a write path under the stamped dir is refused (Ctx.p)', wr)
        # validator
        for u in CHUNKS['G3']['units']:
            dumpj(fixture_unit(u), ctx.p('writers', f'{u}.json'))
        ok, probs = validate_file(ctx, ctx.p('writers', 'SR-u17.json'))
        check(f'validator: the 12-cell fixture unit passes (VALIDATE ok 12) {probs[:2]}', ok)
        for ci, f in enumerate(FRAME_IDS):
            caught = 0
            for code, mf in MUTANTS:
                d = fixture_unit('SR-u17')
                mf(d['items'][ci])
                p = os.path.join(tmp, 'mut.json'); dumpj(d, p)
                ok, probs = validate_file(ctx, p)
                caught += (not ok) and any(c == code and w == f'cell {ci + 1:02d}' for w, c, _ in probs)
            check(f'validator cell {ci + 1:02d} ({f}): {caught}/{len(MUTANTS)} mutants caught with their own code',
                  caught == len(MUTANTS))
        d = fixture_unit('SR-u17'); d['items'] = d['items'][:11]
        p = os.path.join(tmp, 'mut.json'); dumpj(d, p)
        check('validator: 11 items -> FAIL', not validate_file(ctx, p)[0])
        d = fixture_unit('SR-u17'); d['items'][0]['tid'] = 'x'; d['unit_id'] = 'SR-u05'; dumpj(d, p)
        check('validator: a stamped unit id (SR-u05) -> FAIL [schema]',
              validate_file(ctx, p)[1][:1] == [validate_file(ctx, p)[1][0]] and validate_file(ctx, p)[1][0][0] == 'schema')
        d = fixture_unit('SR-u17'); d['items'][5] = dict(d['items'][3], tid='SR-u17-06', frame='F06', topic=d['items'][5]['topic'])
        dumpj(d, p)
        check('validator: a near-duplicate inside the unit -> FAIL [neardup]',
              any(c == 'neardup' for _, c, _ in validate_file(ctx, p)[1]))
        d = fixture_unit('SR-u17')
        d['items'][0].update(first=realk['first'], second=realk['second'], question=realk['question'])
        dumpj(d, p)
        pr = validate_file(ctx, p)[1]
        check(f"validator: a copy of a stamped kept template ({realk['tkey']}) -> FAIL [neardup] naming it",
              any(c == 'neardup' and realk['tkey'] in m for _, c, m in pr))
        # second-order-ONLY near-twin: the stamped fixture B shares second + question with SR-u17-01, not first
        tw = dict(tkey='written:SR-u97-01', tid='SR-u97-01',
                  first='Volunteers counted {M} votes in favour of a new mural for the station; a rival plan drew {S}.',
                  second=FIXTURES['F01'][1], question=FIXTURES['F01'][2])
        f17 = fixture_unit('SR-u17')['items'][0]
        j1 = jacc(*[grams(x['first'] + ' ' + x['question']) for x in (f17, tw)])
        j2 = jacc(*[grams(x['second'] + ' ' + x['question']) for x in (f17, tw)])
        B = _fake_stamped(os.path.join(tmp, 'stampedB'), [realk, syn, tw])
        ctxB = Ctx(ctx.root, stamped=B, pins=None)
        prB = validate_file(ctxB, ctx.p('writers', 'SR-u17.json'))[1]
        check(f'validator: a SECOND-order-only near-twin of a stamped template (J first {j1:.2f} < 0.45, second {j2:.2f}) '
              f'-> FAIL [neardup] naming it', j1 < NEAR_DUP <= j2 and any(c == 'neardup' and tw['tkey'] in m for _, c, m in prB))
        # status / next / attempts
        dumpj(dict(fixture_unit('SR-u19'), items=fixture_unit('SR-u19')['items'][:3]), ctx.p('writers', 'SR-u19.json'))
        st = unit_state(ctx, 'SR-u19')
        check("status: an invalid attempt -> invalid; next gives attempt 1 -> writers/SR-u19.r1.json",
              st['status'] == 'invalid' and next_spec(ctx, 'SR-u19')['output_path'].endswith('SR-u19.r1.json'))
        a = cmd_status(ctx, nxt=True)
        check(f'status --next with one invalid unit: {a}', a == {'chunk': 'G3', 'units': ['SR-u19']})
        dumpj(fixture_unit('SR-u19'), ctx.p('writers', 'SR-u19.r1.json'))
        check('status: the valid retry makes the unit valid', unit_state(ctx, 'SR-u19')['status'] == 'valid')
        a = cmd_status(ctx, nxt=True)
        check(f'status --next with every unit valid: {a}', a == {'chunk': 'G3', 'stages': ['close', 'verify', 'clean']})
        # close (no near-twins under A)
        ok = cmd_close(ctx, 'G3')
        check('close G3: accept 3 units + 3 blind files', ok and len(glob.glob(ctx.p('blind', '*.json'))) == 3)
        check('close is idempotent (a second close changes nothing)', cmd_close(ctx, 'G3'))
        leak = 0; ntext = 0
        for G in CHUNKS['G3']['groups']:
            bl = loadj(ctx.p('blind', f'{G}.blind.json'))
            leak += set(bl) != {'verifier_unit', 'language', 'cue', 'n_items', 'items'}
            for it in bl['items']:
                ntext += 1
                leak += set(it) != {'id', 'text', 'numbers'} or '{' in it['text'] or 'SR-u' in it['text'] or 'g3' in it['text']
        check(f'blind files: {ntext} texts = 4 x 36 templates, no slot, id or label leaks ({leak})', leak == 0 and ntext == 144)
        nd0 = loadj(ctx.p('manifest', 'groups', 'G3.neardup.json'))
        check(f"close reports the within-G3 cross-unit near-duplicates (the 3 identical fixture units: "
              f"{len(nd0['within_g3_cross_unit']['pairs'])} pairs = 12 cells x 3) and drops none of them",
              len(nd0['within_g3_cross_unit']['pairs']) == 36 and not nd0['vs_stamped_bank']['dropped'])
        # format gate
        G = 'SRV-g3a'
        bl = loadj(ctx.p('blind', f'{G}.blind.json')); key = loadj(ctx.p('blind_key', f'{G}.key.json'))

        def orc_item(it, k):
            other = 'n2' if k['minuend_name'] == 'n1' else 'n1'
            return dict(id=it['id'], op='sub', operands=[k['minuend_name'], other], role=k['minuend_name'],
                        answer=str(k['gold']), negative_natural=True if k['gold'] < 0 else None, flags=[], note='')

        def oracle(cx, Gx):
            blx = loadj(cx.p('blind', f'{Gx}.blind.json')); kx = loadj(cx.p('blind_key', f'{Gx}.key.json'))
            return dict(verifier_unit=Gx, items=[orc_item(it, kx[it['id']]) for it in blx['items']])
        orc = oracle(ctx, G)
        check(f'format: the oracle passes ({len(orc["items"])} items)', not check_format(bl, orc))
        neg_i = next(i for i, x in enumerate(orc['items']) if x['negative_natural'] is True)
        M = [('wrong answer for its own op', lambda o: o['items'][0].update(answer='12345')),
             ('role not an operand', lambda o: o['items'][0].update(role='n3')),
             ('negative without negative_natural', lambda o: o['items'][neg_i].update(negative_natural=None)),
             ('other with operands', lambda o: o['items'][0].update(op='other', note='x')),
             ('flag without note', lambda o: o['items'][0].update(flags=['ambiguous'])),
             ('unknown flag', lambda o: o['items'][0].update(flags=['nice'], note='x')),
             ('missing item', lambda o: o['items'].pop()),
             ('duplicate', lambda o: o['items'].append(dict(o['items'][0])))]
        for nm, mf in M:
            o = json.loads(json.dumps(orc)); mf(o)
            check(f'format mutant fails: {nm}', bool(check_format(bl, o)))
        # clean
        for Gx in CHUNKS['G3']['groups']:
            dumpj(oracle(ctx, Gx), ctx.p('verify', f'{Gx}.json'))
        r = cmd_clean(ctx, 'G3', quiet=True)
        check(f"clean on the oracle: kept {len(r['kept'])}/36 (written {r['kept_written']}) -> {r['verdict']}",
              len(r['kept']) == 36 and r['verdict'] == 'GO')
        tk_neg = key[orc['items'][neg_i]['id']]['tkey']
        o = json.loads(json.dumps(orc)); o['items'][neg_i]['negative_natural'] = False
        dumpj(o, ctx.p('verify', f'{G}.json'))
        r = cmd_clean(ctx, 'G3', quiet=True)
        check(f'clean: negative_natural false on one a<b text drops exactly that template ({tk_neg})',
              len(r['kept']) == 35 and [d['tkey'] for d in r['dropped']] == [tk_neg])
        o = json.loads(json.dumps(orc)); x = o['items'][0]; x['role'] = x['operands'][1]
        x['answer'] = str(-key[x['id']]['gold']); x['negative_natural'] = True if -key[x['id']]['gold'] < 0 else None
        dumpj(o, ctx.p('verify', f'{G}.json'))
        r = cmd_clean(ctx, 'G3', quiet=True)
        check('clean: the role swapped on one text (answer S-M) drops its template',
              len(r['kept']) == 35 and 'role' in r['dropped'][0]['reasons'][0])
        o = json.loads(json.dumps(orc)); o['items'][0].update(flags=['magnitude_only'], note='reads as a size')
        dumpj(o, ctx.p('verify', f'{G}.json'))
        r = cmd_clean(ctx, 'G3', quiet=True)
        check('clean: a blocking flag (magnitude_only) drops its template', len(r['kept']) == 35)
        o = json.loads(json.dumps(orc)); o['items'][0].update(flags=['role_only_in_question'], note='role from the question')
        dumpj(o, ctx.p('verify', f'{G}.json'))
        r = cmd_clean(ctx, 'G3', quiet=True)
        check('clean: role_only_in_question is recorded, not blocking', len(r['kept']) == 36
              and sum(t['role_only_in_question'] for t in r['kept']) == 1)
        for Gx in CHUNKS['G3']['groups']:     # the null fixture: every text answered as addition -> NO-GO
            o = oracle(ctx, Gx)
            nn = {i['id']: i for i in loadj(ctx.p('blind', f'{Gx}.blind.json'))['items']}
            for xx in o['items']:
                xx.update(op='add', role=None, negative_natural=None,
                          answer=str(sum(int(v) for v in nn[xx['id']]['numbers'].values())))
            dumpj(o, ctx.p('verify', f'{Gx}.json'))
        r = cmd_clean(ctx, 'G3', quiet=True)
        check(f"clean: the null fixture (every text read as addition) -> kept {len(r['kept'])}/36, {r['verdict']}",
              r['verdict'] == 'NO-GO' and not r['kept'])
        a = cmd_status(ctx, nxt=True)
        check(f'status --next after a NO-GO chunk refuses to go on ({a})', a is None)
        try:
            cmd_gen(ctx, quiet=True); refused = False
        except SystemExit:
            refused = True
        check('gen refuses a NO-GO chunk', refused)
        # the GO bar is the stamped one: 18/36 kept -> GO, 17/36 -> NO-GO
        for nkeep, want in ((18, 'GO'), (17, 'NO-GO')):
            keepk = sorted({key_[x]['tkey'] for Gx in CHUNKS['G3']['groups']
                            for key_ in [loadj(ctx.p('blind_key', f'{Gx}.key.json'))] for x in key_})[:nkeep]
            for Gx in CHUNKS['G3']['groups']:
                kx = loadj(ctx.p('blind_key', f'{Gx}.key.json')); o = oracle(ctx, Gx)
                for xx in o['items']:
                    if kx[xx['id']]['tkey'] not in keepk:
                        xx.update(flags=['unnatural'], note='x')
                dumpj(o, ctx.p('verify', f'{Gx}.json'))
            r = cmd_clean(ctx, 'G3', quiet=True)
            check(f"GO bar (stamped, kept(written) >= 50%): kept {len(r['kept'])}/36 -> {r['verdict']}",
                  len(r['kept']) == nkeep and r['verdict'] == want)
        for Gx in CHUNKS['G3']['groups']:
            dumpj(oracle(ctx, Gx), ctx.p('verify', f'{Gx}.json'))
        cmd_clean(ctx, 'G3', quiet=True)
        a = cmd_status(ctx, nxt=True)
        check(f'status --next after a GO chunk points to gen: {a}', a == 'gen')
        # gen
        rows, cen, bm = cmd_gen(ctx, out=os.path.join(tmp, 'bank1'), quiet=True)
        rows2, cen2, bm2 = cmd_gen(ctx, out=os.path.join(tmp, 'bank2'), quiet=True)
        check(f'gen deterministic (md5 {bm[:8]} twice), rows {len(rows)} = 4 x {cen["pairs_per_template"]} x 36 '
              f'(stamped formula: {max(8, min(60, round(TARGET_ROWS / 144)))} pairs)', bm == bm2
              and len(rows) == 4 * cen['pairs_per_template'] * 36 and cen['pairs_per_template'] == round(TARGET_ROWS / 144))
        check(f"gen: every row fold {FOLD_G3}, template_source {TSRC}, source subrole_g3, row id sr:en:{TSRC}:...",
              all(r['fold'] == FOLD_G3 and r['template_source'] == TSRC and r['source'] == 'subrole_g3'
                  and r['row_id'].startswith(f'sr:en:{TSRC}:') for r in rows))
        if real_row is not None:
            check(f"gen: the row schema equals the stamped bank's ({len(real_row)} fields, prov "
                  f"{sorted(real_row['prov'])})", set(rows[0]) == set(real_row) and set(rows[0]['prov']) == set(real_row['prov']))
            with open(bankp, encoding='utf-8') as fh:
                sids = {json.loads(l)['row_id'] for l in fh if l.strip()}
            check(f'gen: no row id collides with the {len(sids)} stamped row ids', not ({r['row_id'] for r in rows} & sids))
        else:
            check('gen: the stamped bank is present for the schema check', False)
        lt = [r for r in rows if r['half'] == 'a<b']; gt = [r for r in rows if r['half'] == 'a>b']
        size_lt = sum(r['list_values'][r['prov']['gold_run_idx'][0]] > r['list_values'][r['prov']['gold_run_idx'][1]] for r in lt)
        size_gt = sum(r['list_values'][r['prov']['gold_run_idx'][0]] > r['list_values'][r['prov']['gold_run_idx'][1]] for r in gt)
        check(f'gen: SIZE rule names the minuend on a<b {size_lt}/{len(lt)} and on a>b {size_gt}/{len(gt)}',
              size_lt == 0 and size_gt == len(gt) and len(lt) == len(gt))
        order_s = sum(r['prov']['gold_run_idx'][0] == 0 for r in rows if r['written_order'] == 'S')
        check(f'gen: FIRST-WRITTEN rule names the minuend on S rows {order_s}/{len(rows) // 2}', order_s == 0)
        sf = sum(r['written_smaller_first'] for r in rows)
        check(f'gen: smaller number written first on {sf}/{len(rows)} rows (exactly half)', sf * 2 == len(rows))
        okg = all(r['ans'] == r['list_values'][r['prov']['gold_run_idx'][0]] - r['list_values'][r['prov']['gold_run_idx'][1]]
                  and re.findall(r'\d+', r['text']) == [str(v) for v in r['list_values']] for r in rows)
        check('gen: gold = minuend run - subtrahend run and numerals == regex runs on every row', okg)
        neg = sum(r['ans'] < 0 for r in rows)
        check(f'gen: negative golds {neg}/{len(rows)} (= every a<b row)', neg == len(lt))
        check(f"gen: within-G3 near-dup pairs reported ({len(cen['near_dup_within_g3']['pairs'])} = 36 for the 3 identical "
              f"units), none vs the stamped fixture", len(cen['near_dup_within_g3']['pairs']) == 36
              and not cen['near_dup_vs_stamped']['pairs'])
        # gen re-checks the stamped bank: under B (a second-order twin of cell 01) cell 01 of all three units drops
        rowsB, cenB, _ = cmd_gen(ctxB, out=os.path.join(tmp, 'bankB'), quiet=True)
        dB = cenB['dropped_at_gen_near_twin_of_stamped']
        check(f'gen drops and reports near-twins of the stamped bank found at gen (second order only): {dB}',
              dB == [f'{TSRC}:SR-u17-01', f'{TSRC}:SR-u18-01', f'{TSRC}:SR-u19-01'] and cenB['kept'] == 33
              and len(rowsB) == 4 * cenB['pairs_per_template'] * 33 and len(cenB['near_dup_vs_stamped']['pairs']) == 3)
        # close drops near-twins of the stamped bank BEFORE the verifiers (a fresh root, units pre-accepted, stamped B)
        ctxC = Ctx(os.path.join(tmp, 'g3c'), stamped=B, pins=None)
        for u in CHUNKS['G3']['units']:
            dumpj(dict(unit_id=u, attempt=0, source_file='x', source_md5='x', items=fixture_unit(u)['items']),
                  ctxC.p('accept', f'{u}.a0.json'))
        okC = cmd_close(ctxC, 'G3')
        ntC = sum(loadj(ctxC.p('blind', f'{Gx}.blind.json'))['n_items'] for Gx in CHUNKS['G3']['groups'])
        ndC = loadj(ctxC.p('manifest', 'groups', 'G3.neardup.json'))['vs_stamped_bank']
        check(f"close drops near-twins of the stamped bank (second order only) before the verifiers: dropped "
              f"{ndC['dropped']}, blind texts {ntC} = 4 x 33", okC and ntC == 132 and ndC['dropped'] ==
              [f'{TSRC}:SR-u17-01', f'{TSRC}:SR-u18-01', f'{TSRC}:SR-u19-01'])
        for Gx in CHUNKS['G3']['groups']:
            dumpj(oracle(ctxC, Gx), ctxC.p('verify', f'{Gx}.json'))
        rC = cmd_clean(ctxC, 'G3', quiet=True)
        check(f"clean records the close drops as dropped written templates: kept {len(rC['kept'])}/36, dropped "
              f"{len(rC['dropped'])} (near-twin), {rC['verdict']}", len(rC['kept']) == 33 and rC['kept_written'] == [33, 36]
              and all('near-twin' in d['reasons'][0] for d in rC['dropped']) and rC['verdict'] == 'GO')
        # the pinned stamped files refuse a drift
        Dd = os.path.join(tmp, 'stampedD'); shutil.copytree(A, Dd)
        try:
            stamped_kept(Ctx(tmp, stamped=Dd, pins={'clean/X.json': '0' * 32})); refused = False
        except SystemExit:
            refused = True
        check('a stamped file whose md5 drifted from its pin is refused', refused)
    finally:
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
        P(f"MANIFEST ok units {len(idx['units_md5'])}, chunks {list(CHUNKS)}, stamped kept {idx['stamped']['kept']}, "
          f"MANIFEST_INDEX md5 {m}")
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
