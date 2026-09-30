#!/usr/bin/env python3
"""v5_common.py -- shared constants and helpers for BANK v5 (stdlib only; imported by every v5 tool).

What lives here and nowhere else:
  * LANGS (the 25 languages of v4, taken from v4/gen_v4.log line 1 / v4/signed_A_int.jsonl), the verifier GROUPS of 5,
    the SLICES of scenario topics (24 slices x 6 topics; a writer unit gets one HALF-slice = 3 topics), and the
    deterministic unit -> half-slice assignment;
  * the template schema (keys, vocabularies, per-unit quotas) that the writer brief states and validate_v5.py enforces;
  * text helpers: placeholder parsing, the numeral-free skeleton, the character-4-gram Jaccard used for near-duplicates
    (threshold NEAR_DUP = 0.45; evidence: `validate_v5.py --calibrate`), sentence split points (the v4 rule);
  * the four operators, and PLANTED ENGLISH UNITS used only by the selftests (written for them; never a bank input).
The leaf text checks (digits in any script, number words, script fractions, ru/uk and ar/fa separation) are imported
from validate_single.py beside this file (the project's md5 df1c37d9), and called only on placeholder-free strings.
"""
import sys
sys.dont_write_bytecode = True   # no __pycache__: write nothing beyond the files the brief names
import hashlib
import json
import os
import random
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
SIGNED = os.path.dirname(HERE)
ROLE = os.path.dirname(SIGNED)
sys.path.insert(0, HERE)
import validate_single as VS  # noqa: E402  (leaf helpers only: digit_chars, number_words_in, script_problem, file_script_problems)

# ------------------------------------------------------------------ languages, groups
LANGS = ('ar', 'bn', 'de', 'el', 'en', 'es', 'fa', 'fr', 'he', 'hi', 'id', 'it', 'ja', 'ko', 'nl', 'pl', 'pt', 'ru',
         'sw', 'ta', 'th', 'tr', 'uk', 'vi', 'zh')
LANG_NAMES = {'ar': 'Arabic', 'bn': 'Bengali', 'de': 'German', 'el': 'Greek', 'en': 'English', 'es': 'Spanish',
              'fa': 'Persian', 'fr': 'French', 'he': 'Hebrew', 'hi': 'Hindi', 'id': 'Indonesian', 'it': 'Italian',
              'ja': 'Japanese', 'ko': 'Korean', 'nl': 'Dutch', 'pl': 'Polish', 'pt': 'Portuguese', 'ru': 'Russian',
              'sw': 'Swahili', 'ta': 'Tamil', 'th': 'Thai', 'tr': 'Turkish', 'uk': 'Ukrainian', 'vi': 'Vietnamese',
              'zh': 'Chinese'}
# Opus-medium verifier groups of 5 (the 09-22 / 09-24 / 09-29 convention: one Opus verifier per 4-5 languages)
GROUPS = (('en', 'de', 'nl', 'fr', 'es'), ('it', 'pt', 'el', 'ru', 'uk'), ('pl', 'tr', 'ar', 'he', 'fa'),
          ('hi', 'bn', 'ta', 'th', 'vi'), ('id', 'sw', 'ja', 'ko', 'zh'))
NOSPACE = {'ja', 'zh'}                       # v4 generator: no inter-sentence space in these scripts

# ------------------------------------------------------------------ tiers and units
UNIT_TEMPLATES = 12                          # templates per writer unit = 1 per (op x shape) cell
TIERS = {'T1': 8, 'T2': 16, 'T3': 32}        # writer units per language (T1 2,400 / T2 4,800 / T3 9,600 templates)
MAX_UNITS = TIERS['T3']
ROWS_PER_TEMPLATE = 24                       # gen_v5.py: base 4 + T 8 + ex 2 + sem 2 + T+sentence 4 + T+ex+sem 4


def unit_tier(k):
    """The smallest tier that contains writer unit k (1-based)."""
    for t in ('T1', 'T2', 'T3'):
        if k <= TIERS[t]:
            return t
    raise ValueError(k)


def writer_uid(lang, k):
    return 'W5-%s-u%02d' % (lang, k)


def verifier_uid(g, k):
    return 'V5-g%d-u%02d' % (g + 1, k)


# ------------------------------------------------------------------ scenario slices (disjoint topic sets)
SLICES = [
    ('S01', 'kitchens and bakeries', ['bread_and_pastry', 'restaurant_kitchen', 'school_canteen', 'catering',
                                      'market_food_stall', 'home_cooking']),
    ('S02', 'farms and orchards', ['dairy', 'orchard_harvest', 'poultry', 'grain_fields', 'beekeeping', 'greenhouse']),
    ('S03', 'schools and learning', ['classroom_supplies', 'exam_marks', 'school_trip', 'homework', 'science_fair',
                                     'school_library_corner']),
    ('S04', 'books and printing', ['library_loans', 'bookshop', 'printing_press', 'newspaper', 'archive',
                                   'bookbinding']),
    ('S05', 'sport and tournaments', ['football', 'athletics', 'swimming', 'cycling_race', 'chess_club',
                                      'basketball']),
    ('S06', 'roads and rail', ['trains', 'buses', 'car_park', 'road_traffic', 'taxis', 'freight_trucks']),
    ('S07', 'air and sea travel', ['airport', 'ferry', 'harbour', 'cruise_ship', 'cargo_ship', 'airline_baggage']),
    ('S08', 'weather and climate', ['temperature', 'rainfall', 'snowfall', 'wind_measurement', 'river_level',
                                    'air_quality']),
    ('S09', 'money and banking', ['bank_account', 'savings', 'loans_and_debt', 'currency_exchange',
                                  'household_budget', 'payroll']),
    ('S10', 'shops and markets', ['grocery', 'clothing_store', 'hardware_store', 'online_orders', 'flea_market',
                                  'toy_shop']),
    ('S11', 'offices and services', ['call_centre', 'meetings', 'office_paper', 'filing_and_forms',
                                     'reception_visitors', 'printing_and_copying']),
    ('S12', 'factories and warehouses', ['assembly_line', 'packing', 'warehouse_stock', 'quality_control',
                                         'bottling_plant', 'textile_mill']),
    ('S13', 'health and clinics', ['clinic_patients', 'pharmacy', 'blood_bank', 'vaccination', 'hospital_beds',
                                   'fitness_steps']),
    ('S14', 'homes and repairs', ['household_chores', 'plumbing', 'electricity_meter', 'painting',
                                  'furniture_assembly', 'laundry']),
    ('S15', 'crafts and making', ['knitting', 'pottery', 'sewing', 'woodwork', 'weaving', 'candle_making']),
    ('S16', 'music, theatre and museums', ['concert_tickets', 'theatre_seats', 'museum_visitors', 'choir',
                                           'orchestra', 'film_screenings']),
    ('S17', 'animals and reserves', ['zoo', 'bird_count', 'aquarium', 'animal_shelter', 'wildlife_park',
                                     'insect_survey']),
    ('S18', 'fishing and the sea', ['fishing_boats', 'fish_market', 'coral_survey', 'lighthouse', 'sailing_club',
                                    'seaweed_farm']),
    ('S19', 'building and mining', ['construction_site', 'bricklaying', 'quarry', 'mine_output', 'road_building',
                                    'scaffolding']),
    ('S20', 'post and delivery', ['post_office', 'parcel_courier', 'stamps_and_letters', 'delivery_vans',
                                  'mail_sorting', 'drone_delivery']),
    ('S21', 'computing and telecoms', ['data_storage', 'downloads', 'phone_calls', 'servers', 'app_users',
                                       'text_messages']),
    ('S22', 'festivals, hotels and events', ['hotel_rooms', 'wedding_guests', 'festival_stalls', 'conference',
                                             'fireworks_show', 'parade']),
    ('S23', 'geography and population', ['city_population', 'mountain_heights', 'river_lengths', 'census',
                                         'depth_below_sea_level', 'islands']),
    ('S24', 'energy and water', ['reservoir', 'solar_panels', 'fuel_station', 'power_plant', 'water_meter',
                                 'wind_farm']),
]
N_ASSIGN = 2 * len(SLICES)                   # 48 half-slices


def unit_assignment(lang, k):
    """(slice id, slice title, half 0/1, [3 topics]) for writer unit k (1-based) of `lang`. Within one language the 32
    units of T3 take 32 DISTINCT half-slices of the 48, so no two units of a language share a topic; the offset 7*i
    (7 is coprime with 48) spreads the languages over the slices."""
    i = LANGS.index(lang)
    a = (k - 1 + 7 * i) % N_ASSIGN
    sid, title, topics = SLICES[a // 2]
    h = a % 2
    return sid, title, h, topics[3 * h:3 * h + 3]


POSITIONS = ('first', 'middle', 'last')


def t_first_positions(lang, k):
    """{'op/shape': position} -- where {T} must be written in facts_first, per cell, for writer unit k of `lang`.
    (k - 1 + language index + op index + shape index) mod 3: within a unit each position is used by exactly 4 of the
    12 cells, every shape sees all three positions over its 4 ops and every op over its 3 shapes, and each cell rotates
    through the three positions over consecutive units -- so the (op x shape x position) cells fill evenly by
    construction. facts_second is the writer's choice (the unit-level balance rule still applies)."""
    i = LANGS.index(lang) if lang in LANGS else 0
    return {'%s/%s' % (op, sh): POSITIONS[(k - 1 + i + a + b) % 3]
            for a, op in enumerate(OPS_ORDER) for b, sh in enumerate(SHAPES_ORDER)}


OPS_ORDER = ('add', 'sub', 'mul', 'div')
SHAPES_ORDER = ('list', 'other_time', 'diff_owner')

# ------------------------------------------------------------------ template schema
OPS = ('add', 'sub', 'mul', 'div')
OPNAME = {'add': 'addition', 'sub': 'subtraction', 'mul': 'product', 'div': 'division'}
WILD_OP = {'add': 'asum', 'sub': 'aspread', 'mul': 'aprod', 'div': 'aquot'}   # aquot is NEW in v5 (no reader knows it yet)
SHAPES = ('list', 'other_time', 'diff_owner')
RUNG_OF_SHAPE = {'list': 'L3_list', 'other_time': 'L2_time', 'diff_owner': 'L1_owner'}
RUNG_EX, RUNG_SEM = 'L0_kind', 'L1_owner_sent'
RUNGS = (RUNG_EX, RUNG_SEM, 'L1_owner', 'L2_time', 'L3_list')     # the similarity ladder, easiest first
VTIERS = ('V0_len', 'V1_same_len', 'V2_near')                     # value closeness of a distractor to an operand
ITEM_KEYS = ('id', 'op', 'shape', 'topic', 'quantity_kind', 'unit', 'verb',
             'facts_first', 'facts_second', 'base_first', 'base_second', 'question',
             'ex_sentence', 'sem_sentence', 't_mimics', 'signed', 'sign_convention', 'div_mode',
             'numeral_grammar', 'agreement_note', 'gloss_en', 'notes')
FILE_KEYS = ('writer_unit', 'language', 'language_code', 'unit', 'slice', 'topics', 'lead_in', 'attempt', 'items')
TEXT_KEYS = ('facts_first', 'facts_second', 'base_first', 'base_second', 'question', 'ex_sentence', 'sem_sentence')
GRAMMAR = ('invariant', 'number_dependent')
DIV_MODES = ('group_size', 'group_count')
MIMICS = ('M', 'S', 'both')
# per-unit quotas (12 templates)
Q_CELL = 1                                   # exactly 1 per (op x shape)
Q_SUB_SIGNED_MIN = 2                         # of the 3 sub templates at least 2 signed (negative answer natural)
Q_POS_MIN, Q_POS_MAX = 4, 12                 # T written first / middle / last: each in [4, 12] of the 24 facts texts
Q_SPLIT_MIN = 6                              # templates with a sentence boundary between {M} and {S} in BOTH bases
Q_KINDS_MIN = 8                              # distinct quantity_kind among 12
Q_VERB_MAX = 2                               # one verb lemma at most twice
Q_NUMDEP_MAX = 2                             # number_dependent templates at most 2 of 12
Q_TOPIC_MIN, Q_TOPIC_MAX = 3, 6              # each of the unit's 3 topics used 3..6 times
NEAR_DUP = 0.45                              # char-4-gram Jaccard at or above this = near duplicate
BASE_MIN_SIM = 0.25                          # base facts must share at least this much with its facts text

PH = re.compile(r'\{([A-Za-z]+)\}')
RUNS = re.compile(r'[0-9]+')
SENT_END = re.compile(r'[.!?。！？؟।]')       # the v4 generator's strong sentence enders (gen_signed_bank_ml.py line 140)
QMARKS = '?？؟;;'
TRAIL = "\"'”’»」』)）"
ARITH = '+×*/÷=%−∶'
EN_EXTRA_NUMBER_WORDS = ('first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth '
                         'once pair pairs couple').split()   # ordinals and pair words; 'quarter' left out (a period)
EN_DIV_BANNED = ('left over', 'leftover', 'remainder', 'remain', 'needed', 'at least', 'between', 'about',
                 'approximately', 'roughly', 'round up')


def placeholders(t):
    return PH.findall(t or '')


def strip_ph(t):
    return PH.sub(' ', t or '')


def slot_order(t, slots=('M', 'S', 'T')):
    """Slots present in t, in written order."""
    pos = sorted((t.find('{%s}' % s), s) for s in slots if ('{%s}' % s) in t)
    return [s for _, s in pos]


def norm(t):
    """Case-folded letters and marks only, every placeholder -> '#', runs of anything else -> one space."""
    t = PH.sub('#', t or '').casefold()
    t = ''.join(c if (unicodedata.category(c)[0] in 'LM' or c == '#') else ' ' for c in t)
    return re.sub(r'\s+', ' ', t).strip()


def shingles(t, n=4):
    t = norm(t)
    return frozenset(t[i:i + n] for i in range(max(1, len(t) - n + 1)))


def jaccard(a, b):
    return len(a & b) / float(len(a | b) or 1)


def dup_text(it):
    """The string two templates are compared on: first-order facts + question."""
    return (it.get('facts_first') or '') + ' ' + (it.get('question') or '')


def skeleton(t):
    return norm(t).replace(' ', '')


def split_points(tpl, a='{M}', b='{S}'):
    """v4's split_points (gen_signed_bank_ml.py lines 340-352) generalised to any two slot tokens: character offsets
    just after a strong sentence ender lying strictly between the two slots."""
    i, j = tpl.find(a), tpl.find(b)
    if i < 0 or j < 0:
        return []
    lo, hi = min(i, j) + len(a), max(i, j)
    out = []
    for m in SENT_END.finditer(tpl, lo, hi):
        k = m.end()
        while k < len(tpl) and tpl[k] in '  \t　':
            k += 1
        if lo < k < hi:
            out.append(k)
    return out


def selftest_dir():
    """A scratch directory for selftests INSIDE v5/ (the brief allows new files only here); removed by
    selftest_cleanup() at the end of every selftest."""
    import tempfile
    d = os.path.join(HERE, '_selftest_tmp')
    os.makedirs(d, exist_ok=True)
    return tempfile.mkdtemp(dir=d)


def selftest_cleanup():
    import shutil
    shutil.rmtree(os.path.join(HERE, '_selftest_tmp'), ignore_errors=True)


def md5_file(p):
    h = hashlib.md5()
    with open(p, 'rb') as fh:
        for b in iter(lambda: fh.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def load_json(p):
    with open(p, encoding='utf-8') as fh:
        return json.load(fh)


def dump_json(p, obj):
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
        fh.write('\n')


def seeded(*parts, seed=20260929):
    """v4's rng(): blake2b of the joined parts XOR the seed (gen_signed_bank_ml.py lines 162-166)."""
    h = hashlib.blake2b(('|'.join(str(p) for p in parts)).encode('utf-8'), digest_size=8).digest()
    return random.Random(int.from_bytes(h, 'big') ^ (seed & 0xFFFFFFFFFFFFFFFF))


def verified_lead_in(lang):
    """The v4 bank's lead_in for the language (signed/verified/<code>.verified.json), or None if absent."""
    p = os.path.join(SIGNED, 'verified', '%s.verified.json' % lang)
    if not os.path.exists(p):
        return None
    return load_json(p).get('lead_in')


def prior_corpus(lang, include_examples=True):
    """Existing templates a v5 template must not near-copy: the verified v2-v4 stories of the language, and for
    English also v4wild's 40 templates and the 24 English examples of BRIEF_v5_writer.md (the planted units).
    Returns [(source id, dup text)]."""
    out = []
    if lang == 'en' and include_examples:
        for k in (1, 2):
            for it in planted_unit(k)[0]['items']:
                out.append(('brief-example/%s' % it['id'], dup_text(it)))
    p = os.path.join(SIGNED, 'verified', '%s.verified.json' % lang)
    if os.path.exists(p):
        for it in load_json(p).get('items', []):
            out.append(('verified/%s#%s' % (lang, it.get('story_id')),
                        (it.get('facts_min_first') or '') + ' ' + (it.get('question') or '')))
    if lang == 'en':
        p = os.path.join(SIGNED, 'writers_wild', 'en_wild.json')
        if os.path.exists(p):
            for it in load_json(p).get('items', []):
                out.append(('writers_wild/en#%s' % it.get('story_id'),
                            (it.get('facts_min_first') or '') + ' ' + (it.get('question') or '')))
    return out


# ------------------------------------------------------------------ PLANTED ENGLISH UNITS (selftests only)
def _t(op, shape, topic, qk, verb, ff, fs, bf, bs, q, ex, sem, mim, signed=False, conv='', mode='', unit=''):
    return dict(op=op, shape=shape, topic=topic, quantity_kind=qk, unit=unit or qk, verb=verb,
                facts_first=ff, facts_second=fs, base_first=bf, base_second=bs, question=q,
                ex_sentence=ex, sem_sentence=sem, t_mimics=mim, signed=signed, sign_convention=conv,
                div_mode=mode, numeral_grammar='invariant',
                agreement_note='Every slot is followed by a plural noun or a unit; any whole number reads grammatically.',
                gloss_en=ff + ' ' + q, notes='planted selftest template')


_P1 = [
    _t('add', 'list', 'stock_and_packing', 'cartons', 'seal',
       'This morning the packing hall sealed {M} cartons of soap, {T} cartons of shampoo and {S} cartons of toothpaste.',
       'This morning the packing hall sealed {S} cartons of toothpaste, {T} cartons of shampoo and {M} cartons of soap.',
       'This morning the packing hall sealed {M} cartons of soap. It also sealed {S} cartons of toothpaste.',
       'This morning the packing hall sealed {S} cartons of toothpaste. It also sealed {M} cartons of soap.',
       'How many cartons of soap and toothpaste did the packing hall seal this morning?',
       'The packing hall is listed as building {D} on the site plan.',
       'A rival plant across the river sealed {D} cartons of soap this morning.', 'both'),
    _t('add', 'other_time', 'lines_and_plants', 'crates', 'fill',
       "During yesterday's shift the bottling line filled {T} crates of lemonade. During today's shift it filled {M} crates of lemonade and {S} crates of cola.",
       "During yesterday's shift the bottling line filled {T} crates of lemonade. During today's shift it filled {S} crates of cola and {M} crates of lemonade.",
       "During today's shift the bottling line filled {M} crates of lemonade and {S} crates of cola.",
       "During today's shift the bottling line filled {S} crates of cola and {M} crates of lemonade.",
       "How many crates of lemonade and cola did the bottling line fill during today's shift?",
       'The bottling line runs in hall {D}.',
       'The bottling line at a partner brewery filled {D} crates of cola today.', 'both'),
    _t('add', 'diff_owner', 'lines_and_plants', 'bicycles', 'assemble',
       'Line South assembled {T} bicycles on Monday. Line North assembled {M} bicycles on Monday and {S} bicycles on Tuesday.',
       'Line South assembled {T} bicycles on Monday. Line North assembled {S} bicycles on Tuesday and {M} bicycles on Monday.',
       'Line North assembled {M} bicycles on Monday. On Tuesday it assembled {S} bicycles.',
       'Line North assembled {S} bicycles on Tuesday. On Monday it had assembled {M} bicycles.',
       'How many bicycles did Line North assemble on Monday and Tuesday together?',
       "Line North's supervisor wears badge {D}.",
       'An independent repair shop assembled {D} bicycles on Monday.', 'both'),
    _t('sub', 'list', 'stock_and_packing', 'spare tyres', 'count',
       'At the end of March the store room counted {M} spare tyres, at the end of February {T}, and at the end of January {S}.',
       'At the end of January the store room counted {S} spare tyres, at the end of February {T}, and at the end of March {M}.',
       'At the end of March the store room counted {M} spare tyres. At the end of January it had counted {S}.',
       'At the end of January the store room counted {S} spare tyres. At the end of March it counted {M}.',
       'What was the change in the number of spare tyres in the store room from the end of January to the end of March?',
       'The store room is room {D} in the basement.',
       'A tyre dealer in town counted {D} spare tyres at the end of March.', 'both', True,
       'end of March minus end of January'),
    _t('sub', 'other_time', 'lines_and_plants', 'litres of syrup', 'receive',
       'This week the syrup tank received {M} litres and released {S} litres; last week it had received {T} litres.',
       'This week the syrup tank released {S} litres and received {M} litres; last week it had received {T} litres.',
       'This week the syrup tank received {M} litres. It released {S} litres.',
       'This week the syrup tank released {S} litres. It received {M} litres.',
       "What was the net change in the tank's contents this week, counting what came in minus what went out?",
       'The syrup tank carries the label tank {D} on the pipe diagram.',
       'The tank at the rival brewery received {D} litres this week.', 'both', True,
       'received minus released, this week', unit='litres'),
    _t('sub', 'diff_owner', 'stock_and_packing', 'pallets', 'hold',
       'The neighbouring warehouse holds {T} pallets of cement. Our warehouse held {M} pallets of cement until a lorry took away {S} of them.',
       'A lorry took away {S} pallets of cement from our warehouse, which had held {M} such pallets, while the neighbouring warehouse holds {T} pallets of cement.',
       'Our warehouse held {M} pallets of cement until a lorry took away {S} of them.',
       'A lorry took away {S} pallets of cement from our warehouse, which had held {M} such pallets.',
       'How many pallets of cement are still in our warehouse?',
       'Our warehouse stands on quay {D}.',
       "The port authority's yard holds {D} pallets of cement.", 'both'),
    _t('mul', 'list', 'stock_and_packing', 'jars', 'pack',
       'The team packed {M} large boxes; large boxes hold {S} jars each, and small boxes hold {T} jars each.',
       'Small boxes hold {T} jars each and large boxes hold {S} jars each; the team packed {M} large boxes.',
       'The team packed {M} large boxes. Each large box holds {S} jars.',
       'Each large box holds {S} jars. The team packed {M} large boxes.',
       'How many jars did the team pack?',
       'The team works at packing station {D}.',
       'At the other depot, each large box holds {D} jars.', 'S'),
    _t('mul', 'other_time', 'lines_and_plants', 'brackets', 'build',
       'This week the line built {M} shelving units, last week {T} shelving units, and every unit is fitted with {S} brackets.',
       'Every shelving unit is fitted with {S} brackets; last week the line built {T} of them and this week {M}.',
       'This week the line built {M} shelving units, each fitted with {S} brackets.',
       'Each shelving unit is fitted with {S} brackets, and this week the line built {M} of them.',
       'How many brackets did the line fit this week?',
       'The shelving line appears as line {D} in the catalogue.',
       'A furniture shop in town built {D} shelving units this week.', 'M'),
    _t('mul', 'diff_owner', 'inspection_and_textiles', 'microchips', 'check',
       'Inspector Rana checked {M} trays with {S} microchips on each tray, and Inspector Bose checked {T} trays.',
       'Each tray holds {S} microchips. Inspector Bose checked {T} trays and Inspector Rana checked {M} trays.',
       'Inspector Rana checked {M} trays. Each tray holds {S} microchips.',
       'Each tray holds {S} microchips. Inspector Rana checked {M} trays.',
       'How many microchips did Inspector Rana check?',
       'Inspector Rana keeps her tools in locker {D}.',
       'An external auditor checked {D} trays of the same microchips.', 'M'),
    _t('div', 'list', 'lines_and_plants', 'bottles', 'produce',
       'Today the juice plant produced {M} bottles. Its crates hold {S} bottles each, and its gift boxes hold {T} bottles each.',
       'At the juice plant, crates hold {S} bottles each and gift boxes hold {T} bottles each. Today the plant produced {M} bottles.',
       'Today the juice plant produced {M} bottles. Its crates hold {S} bottles each.',
       'At the juice plant, crates hold {S} bottles each. Today the plant produced {M} bottles.',
       "If all of today's bottles went into crates, how many crates did the plant fill?",
       "The juice plant is supplier {D} on the retailer's list.",
       'The co-operative down the road produced {D} bottles today.', 'S', mode='group_size'),
    _t('div', 'other_time', 'inspection_and_textiles', 'metres of silk', 'dye',
       'This month the mill dyed {M} metres of silk and cut all of it into lengths of {S} metres; last month it had dyed {T} metres of silk.',
       'The mill cuts its silk into lengths of {S} metres. This month it dyed {M} metres; last month it had dyed {T} metres.',
       'This month the mill dyed {M} metres of silk and cut all of it into lengths of {S} metres.',
       'The mill cuts its silk into lengths of {S} metres. This month it dyed {M} metres of silk.',
       "How many lengths of silk did this month's dyeing give?",
       'The dye house is shed {D} of the mill.',
       'A tailoring school dyed {D} metres of silk this month.', 'M', mode='group_size'),
    _t('div', 'diff_owner', 'inspection_and_textiles', 'sample batches', 'test',
       'The Riverside team tested {T} sample batches. The Hilltop team tested {M} sample batches and divided them equally among its {S} inspectors.',
       'The Hilltop team has {S} inspectors, and it divided the {M} sample batches it tested equally among them; the Riverside team tested {T} sample batches.',
       'The Hilltop team tested {M} sample batches. It divided them equally among its {S} inspectors.',
       'The Hilltop team has {S} inspectors. It divided the {M} sample batches it tested equally among them.',
       'How many sample batches did each Hilltop inspector receive?',
       'The Hilltop team works in lab {D}.',
       'An external laboratory tested {D} sample batches.', 'M', mode='group_count'),
]

_P2 = [
    _t('add', 'list', 'stock_and_packing', 'drums', 'keep',
       'In the warehouse the north row keeps {T} drums of thinner, the middle row keeps {M} drums of varnish and the south row keeps {S} drums of primer.',
       'In the warehouse the north row keeps {T} drums of thinner, the south row keeps {S} drums of primer and the middle row keeps {M} drums of varnish.',
       'In the warehouse the middle row keeps {M} drums of varnish. The south row keeps {S} drums of primer.',
       'In the warehouse the south row keeps {S} drums of primer. The middle row keeps {M} drums of varnish.',
       'How many drums of varnish and primer do the middle and south rows keep together?',
       "The warehouse's loading bay is door {D}.",
       'The depot next door stores {D} drums of varnish.', 'both'),
    _t('add', 'other_time', 'inspection_and_textiles', 'bolts of cloth', 'weave',
       'This winter the mill has woven {M} bolts of linen; last winter it wove {T} bolts of linen; this winter it has also woven {S} bolts of wool.',
       'This winter the mill has woven {S} bolts of wool; last winter it wove {T} bolts of linen; this winter it has also woven {M} bolts of linen.',
       'This winter the mill has woven {M} bolts of linen and {S} bolts of wool.',
       'This winter the mill has woven {S} bolts of wool and {M} bolts of linen.',
       'How many bolts of linen and wool has the mill woven this winter?',
       'The mill stands on plot {D} of the industrial estate.',
       'A family workshop in the valley has woven {D} bolts of wool this winter.', 'both'),
    _t('add', 'diff_owner', 'inspection_and_textiles', 'engines', 'pass',
       'The day inspectors in hall East passed {M} engines, the inspectors in hall West passed {T} engines, and the night crew in hall East passed {S} engines.',
       'The night crew in hall East passed {S} engines, the inspectors in hall West passed {T} engines, and the day inspectors in hall East passed {M} engines.',
       'The day inspectors in hall East passed {M} engines. The night crew in hall East passed {S} engines.',
       'The night crew in hall East passed {S} engines. The day inspectors in hall East passed {M} engines.',
       'How many engines were passed in hall East over the day and night together?',
       'Hall East has its entrance at gate {D}.',
       'An outside testing lab passed {D} engines for the same client.', 'both'),
    _t('sub', 'list', 'stock_and_packing', 'parcels', 'wrap',
       'At the packing benches, the window bench wrapped {M} parcels, the door bench wrapped {S} parcels and the corner bench wrapped {T} parcels.',
       'At the packing benches, the door bench wrapped {S} parcels, the window bench wrapped {M} parcels and the corner bench wrapped {T} parcels.',
       'At the packing benches, the window bench wrapped {M} parcels. The door bench wrapped {S} parcels.',
       'At the packing benches, the door bench wrapped {S} parcels. The window bench wrapped {M} parcels.',
       'How many more parcels did the window bench wrap than the door bench?',
       'The window bench carries asset tag {D}.',
       'A courier depot nearby wrapped {D} parcels the same day.', 'both'),
    _t('sub', 'other_time', 'lines_and_plants', 'tractors', 'make',
       'This quarter the plant made {M} tractors against a plan of {S} tractors; last quarter it had made {T} tractors.',
       "This quarter the plant's plan was {S} tractors and it made {M} tractors; last quarter it had made {T} tractors.",
       'This quarter the plant made {M} tractors. Its plan for the quarter was {S} tractors.',
       "This quarter the plant's plan was {S} tractors. It made {M} tractors.",
       "By how many tractors did this quarter's output differ from this quarter's plan, output minus plan?",
       "The plant's tractor model is sold as series {D}.",
       'A competitor abroad made {D} tractors this quarter.', 'both', True, 'output minus plan, this quarter'),
    _t('sub', 'diff_owner', 'inspection_and_textiles', 'points', 'score',
       'This month the Elm Street workshop scored {T} points on quality. The Oak Street workshop scored {M} points against a target of {S} points.',
       'This month the Elm Street workshop scored {T} points on quality. The Oak Street workshop had a target of {S} points and scored {M} points.',
       'This month the Oak Street workshop scored {M} points on quality. Its target was {S} points.',
       'This month the Oak Street workshop had a quality target of {S} points. It scored {M} points.',
       "How far was the Oak Street workshop's score from its own target this month, score minus target?",
       'The Oak Street workshop is unit {D} on the estate.',
       'The regional average quality score this month is {D} points.', 'both', True, 'score minus target'),
    _t('mul', 'list', 'lines_and_plants', 'bottles', 'load',
       'On Monday the plant loaded {M} pallets, on Tuesday {T} pallets, and every pallet carries {S} bottles.',
       'Every pallet carries {S} bottles; the plant loaded {T} pallets on Tuesday and {M} pallets on Monday.',
       'On Monday the plant loaded {M} pallets. Every pallet carries {S} bottles.',
       'Every pallet carries {S} bottles. On Monday the plant loaded {M} pallets.',
       'How many bottles did the plant load on Monday?',
       'The pallets leave through dock {D}.',
       'The rival bottler loaded {D} pallets on Monday.', 'M'),
    _t('mul', 'other_time', 'inspection_and_textiles', 'kilograms of cotton', 'buy',
       'Last season each bale of cotton weighed {T} kilograms. This season the mill bought {M} bales, and each weighs {S} kilograms.',
       'Last season each bale of cotton weighed {T} kilograms. This season each bale weighs {S} kilograms, and the mill bought {M} bales.',
       'This season the mill bought {M} bales of cotton, and each weighs {S} kilograms.',
       'This season each bale of cotton weighs {S} kilograms, and the mill bought {M} bales.',
       'How many kilograms of cotton did the mill buy this season?',
       'The cotton arrives on truck route {D}.',
       'A spinning mill abroad bought bales of {D} kilograms this season.', 'S', unit='kilograms'),
    _t('mul', 'diff_owner', 'stock_and_packing', 'crates', 'take',
       'The new depot has {M} shelves, and each shelf takes {S} crates; at the old depot a shelf takes {T} crates.',
       'At the new depot each shelf takes {S} crates, and there are {M} shelves; at the old depot a shelf takes {T} crates.',
       'The new depot has {M} shelves. Each shelf takes {S} crates.',
       'At the new depot each shelf takes {S} crates. There are {M} shelves.',
       "How many crates can the new depot's shelves take in all?",
       'The new depot is unit {D} on the business park.',
       'A rented unit next door has shelves that take {D} crates each.', 'S'),
    _t('div', 'list', 'stock_and_packing', 'vases', 'share',
       'The packers received {T} ceramic bowls and {M} glass vases, and they shared the vases equally among {S} shipping cartons.',
       'The packers had {S} shipping cartons. They received {T} ceramic bowls and {M} glass vases, and shared the vases equally among the cartons.',
       'The packers received {M} glass vases and shared them equally among {S} shipping cartons.',
       'The packers had {S} shipping cartons. They received {M} glass vases and shared them equally among the cartons.',
       'How many vases went into each carton?',
       "The packers' order is filed as ticket {D}.",
       'Another packing firm received {D} glass vases this week.', 'M', mode='group_count'),
    _t('div', 'other_time', 'stock_and_packing', 'sacks', 'spread',
       'Last year the warehouse spread its stock over {T} loading bays. This year it has {M} sacks of rice, spread equally over {S} loading bays.',
       'Last year the warehouse spread its stock over {T} loading bays. This year it spreads its rice equally over {S} loading bays, and it has {M} sacks of rice.',
       'This year the warehouse has {M} sacks of rice. It spreads them equally over {S} loading bays.',
       'This year the warehouse spreads its rice equally over {S} loading bays. It has {M} sacks of rice.',
       'How many sacks of rice are in each loading bay this year?',
       'The rice is shipped under lot code {D}.',
       'A grain store in the next town has {D} sacks of rice this year.', 'S', mode='group_count'),
    _t('div', 'diff_owner', 'lines_and_plants', 'screws', 'pack',
       'Workshop Birch has {M} screws to pack in bags of {S} screws, and Workshop Cedar packs its screws in bags of {T}.',
       'Workshop Birch packs screws in bags of {S}; Workshop Cedar packs them in bags of {T}. Workshop Birch has {M} screws to pack.',
       'Workshop Birch has {M} screws to pack in bags of {S} screws.',
       'Workshop Birch packs screws in bags of {S}. It has {M} screws to pack.',
       'How many bags does Workshop Birch fill with its screws?',
       'Workshop Birch is on corridor {D}.',
       'A hardware wholesaler packs its screws in bags of {D}.', 'S', mode='group_size'),
]
PLANT_TOPICS = ['stock_and_packing', 'lines_and_plants', 'inspection_and_textiles']


def planted_unit(k=1, lang='en', attempt=0):
    """A complete, valid English writer unit (k = 1 or 2) for the selftests, with the unit record it belongs to."""
    import copy
    items = copy.deepcopy(_P1 if k % 2 == 1 else _P2)
    uid = writer_uid(lang, k)
    for j, it in enumerate(items):
        it['id'] = '%s-%02d' % (uid, j + 1)
    ordered = [{key: it[key] for key in ITEM_KEYS} for it in items]
    doc = dict(writer_unit=uid, language=LANG_NAMES[lang], language_code=lang, unit=k, slice='SELFTEST',
               topics=list(PLANT_TOPICS), lead_in='The answer is', attempt=attempt, items=ordered)
    unit = dict(uid=uid, lang=lang, unit=k, slice='SELFTEST', slice_title='selftest', half=0,
                topics=list(PLANT_TOPICS), lead_in='The answer is', tier=unit_tier(k),
                t_first_position=fixture_positions(doc))
    return doc, unit


def fixture_positions(doc):
    """The facts_first {T} positions a (planted) unit actually has, in the manifest's per-cell form."""
    out = {}
    for it in doc['items']:
        o = slot_order(it['facts_first'])
        if sorted(o) == ['M', 'S', 'T']:
            out['%s/%s' % (it['op'], it['shape'])] = POSITIONS[o.index('T')]
    return out
