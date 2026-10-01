#!/usr/bin/env python3
"""v5x_lang.py -- the 36 languages of BANK v5x (v3_61 minus v4/v5): scripts, punctuation, number words, file-level
language separation, per-language writer notes, and the in-process patch that teaches the PINNED v5 tools about them
(stdlib only).

    python3 v5x_lang.py --calibrate     # every table against the 36 verified v3_61 corpora (signed/verified/<l>.verified.json)
    python3 v5x_lang.py --selftest

Nothing pinned is edited. `patch()` (called once by v5x.py at import) changes MODULE GLOBALS of the imported, pinned
modules for this process only:
  * validate_single (md5 df1c37d9): SCRIPTS / SCRIPT_MIN_FRAC gain the 36 languages (script_problem did SCRIPTS[lang]
    -> KeyError on 34 of them); number_words_in dispatches the 34 new languages to number_words_x (the pinned regex
    boundary (?![\\w'']) treats a combining vowel sign as a word boundary, so a Gujarati list word would match inside
    every word that carries a vowel sign; fi and hu keep the pinned lists and matcher); file_script_problems gains the
    FILE_CHECKS below.
  * v5_common (pinned): SENT_END gains the native full stops of am (U+1362), hy (U+0589), ur (U+06D4), bo (U+0F0D,
    U+0F0E), my (U+104B), km (U+17D4, U+17D5) and the Ethiopic question mark (U+1367), so the pinned sentence-final check,
    split_points (the >= 6 sentence-break quota) and gen_v5.real_splits (mid placement) see those sentence breaks.
The pinned [question] check (question must end in ? / ？ / ؟) is NOT patched: v5x.py drops that one line and applies
question_end_ok() per language and per question form instead.

DIGITS. All 36 languages are filled with ASCII digits, no grouping, as v3_61 did: 0 rows with a non-ASCII digit in
every language of v3_61/signed_A_int.jsonl (counts in V3_61_A_INT_ROWS, scanned 2026-09-30 18:0x; recompute with
`v5x.py digitscan`). Writers write no digit at all (the pinned [digit] check refuses Nd / No / Nl in any script, so
native digits and Ethiopic numerals are refused too).
"""
import sys
sys.dont_write_bytecode = True
import json
import os
import re
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
SIGNED = os.path.dirname(HERE)
ROLE = os.path.dirname(SIGNED)
V5 = os.path.join(SIGNED, 'v5')
sys.path.insert(0, V5)
import v5_common as C  # noqa: E402  (pinned; its import puts ../../singlestep on sys.path and imports validate_single)
VS = C.VS

# ------------------------------------------------------------------ languages, in chunk order (index i = position)
CHUNKS = (
    ('C1', 'Central Europe and the Balkans (Slavic, Hungarian, Romanian; Latin + Cyrillic)', ('bg', 'cs', 'hu', 'ro', 'sk', 'sr')),
    ('C2', 'Northern Europe, the Baltic, Latin and Basque', ('eu', 'fi', 'is', 'la', 'lt', 'sv')),
    ('C3', 'Indian languages in Brahmic scripts (Indo-Aryan + Dravidian)', ('gu', 'kn', 'ml', 'mr', 'pa', 'te')),
    ('C4', 'Caucasus and Central Asia, plus Albanian (hy + sq: the single-language branches of Indo-European)',
     ('hy', 'ka', 'kk', 'mn', 'sq', 'uz')),
    ('C5', 'South Asia (Nepali, Urdu), Austronesian (Malay, Tagalog), Africa (Hausa, Zulu)', ('ha', 'ms', 'ne', 'tl', 'ur', 'zu')),
    ('C6', 'FLAGGED: low-resource or unusual scripts (Ethiopic, Tibetan, Khmer, Myanmar, Sinhala; Yoruba tone marks)',
     ('am', 'bo', 'km', 'my', 'si', 'yo')),
)
LANGS = tuple(l for _, _, ls in CHUNKS for l in ls)
FLAGGED = ('am', 'bo', 'km', 'my', 'si', 'yo')
LANG_NAMES = {'am': 'Amharic', 'bg': 'Bulgarian', 'bo': 'Tibetan', 'cs': 'Czech', 'eu': 'Basque', 'fi': 'Finnish',
              'gu': 'Gujarati', 'ha': 'Hausa', 'hu': 'Hungarian', 'hy': 'Armenian', 'is': 'Icelandic', 'ka': 'Georgian',
              'kk': 'Kazakh', 'km': 'Khmer', 'kn': 'Kannada', 'la': 'Latin', 'lt': 'Lithuanian', 'ml': 'Malayalam',
              'mn': 'Mongolian', 'mr': 'Marathi', 'ms': 'Malay', 'my': 'Burmese', 'ne': 'Nepali', 'pa': 'Punjabi',
              'ro': 'Romanian', 'si': 'Sinhala', 'sk': 'Slovak', 'sq': 'Albanian', 'sr': 'Serbian', 'sv': 'Swedish',
              'te': 'Telugu', 'tl': 'Filipino (Tagalog)', 'ur': 'Urdu', 'uz': 'Uzbek', 'yo': 'Yoruba', 'zu': 'Zulu'}
# rows of v3_61/signed_A_int.jsonl per language; a non-ASCII digit in 0 of them in every language (scan 2026-09-30)
V3_61_A_INT_ROWS = {'am': 1536, 'bg': 2048, 'bo': 896, 'cs': 1664, 'eu': 1472, 'fi': 2048, 'gu': 1280, 'ha': 2048,
                    'hu': 1536, 'hy': 2048, 'is': 1664, 'ka': 1408, 'kk': 896, 'km': 1216, 'kn': 1152, 'la': 1152,
                    'lt': 1664, 'ml': 1408, 'mn': 1024, 'mr': 1408, 'ms': 1856, 'my': 1664, 'ne': 1536, 'pa': 1344,
                    'ro': 1792, 'si': 2048, 'sk': 1408, 'sq': 1664, 'sr': 1728, 'sv': 1792, 'te': 2048, 'tl': 1920,
                    'ur': 2048, 'uz': 1536, 'yo': 1664, 'zu': 1280}

# ------------------------------------------------------------------ scripts
LATIN = ('cs', 'eu', 'fi', 'ha', 'hu', 'is', 'la', 'lt', 'ms', 'ro', 'sk', 'sq', 'sv', 'tl', 'uz', 'yo', 'zu')
SCRIPTS = {l: ('LATIN',) for l in LATIN}
SCRIPTS.update({'bg': ('CYRILLIC',), 'sr': ('CYRILLIC',), 'kk': ('CYRILLIC',), 'mn': ('CYRILLIC',),
                'am': ('ETHIOPIC',), 'bo': ('TIBETAN',), 'my': ('MYANMAR',), 'km': ('KHMER',), 'si': ('SINHALA',),
                'ka': ('GEORGIAN',), 'hy': ('ARMENIAN',), 'gu': ('GUJARATI',), 'pa': ('GURMUKHI',),
                'kn': ('KANNADA',), 'ml': ('MALAYALAM',), 'te': ('TELUGU',), 'mr': ('DEVANAGARI',),
                'ne': ('DEVANAGARI',), 'ur': ('ARABIC',)})
MIN_FRAC = {l: 0.95 for l in LATIN}          # the pinned rule for Latin-script languages; others keep the 0.80 default

# ------------------------------------------------------------------ punctuation
EXTRA_ENDERS = '።፧։۔།༎။។៕'   # ። ፧ ։ ۔ ། ༎ ။ ។ ៕
SENT_END_X = re.compile('[.!?。！？؟।%s]' % EXTRA_ENDERS)
QEND_DEFAULT = '?？؟'
QEND = {'am': QEND_DEFAULT + '፧',                     # ፧
        'hy': QEND_DEFAULT + '՞',                     # ՞ (also accepted when it stands inside the question word)
        'my': QEND_DEFAULT + '။',                     # Burmese questions end in a particle + ။
        'bo': QEND_DEFAULT + '།༎',               # Tibetan questions end in a particle + ། / ༎
        'km': QEND_DEFAULT + '។'}                     # Khmer: ? or ។ after a question word
QUESTION_BY_FULL_STOP = ('my', 'bo', 'km')                 # a question may end with the full stop: F2 cannot be told apart
STATEMENT_END = '.!።։۔།༎။។៕।'   # . ! ። ։ ۔ ། ༎ ။ ។ ៕ ।
TRAIL = C.TRAIL
LABEL_COLONS = ':：፦'                                  # : ： ፦ (Ethiopic preface colon)


def _last(t):
    return (t or '').rstrip().rstrip(TRAIL).rstrip()[-1:]


def question_end_ok(lang, t):
    """True when t ends as a question in `lang` (Armenian: a ՞ inside the question also counts, with ։ / . at the end)."""
    e = _last(t)
    if not e:
        return False
    if e in QEND.get(lang, QEND_DEFAULT):
        return True
    return lang == 'hy' and '՞' in t and e in '։.'


def statement_end_ok(lang, t):
    e = _last(t)
    return bool(e) and e in STATEMENT_END


# ------------------------------------------------------------------ number words (conservative; homographs left out)
# The pinned lists cover fi and hu. For the 34 others: cardinals 2-10, hundred / thousand, half, double, dozen, twice,
# only where the word has no common second meaning. LEFT OUT on purpose (homographs): sr сто (table), пола; ro nouă
# (new), mie (to me); lt pusė (side); kk жүз (face, swim); mn тав (comfort), зуу; uz uch (tip), yuz (face); ne छ (is);
# ur دو (give), سو (sleep), نو (new); pa ਦਸ (tell); kn ಆರು ಏಳು ಹತ್ತು (dry / rise / climb); ml ആറ് (river); te ఆరు ఏడు;
# gu છ નવ; tl pito (whistle); ha tara (gather); zu isithupha (thumb). No list for bo, km, my: their words are not
# space-separated and every short numeral there is also a common word (my နှစ် year, ငါး fish, သုံး use ...); the blind
# verifier's hidden_operand flag covers them.
NUMBER_WORDS = {
    'am': 'ሁለት ሦስት ሶስት አራት አምስት ስድስት ሰባት ስምንት ዘጠኝ አስር አሥር መቶ ሺህ ግማሽ',
    'bg': 'два две три четири пет шест седем осем девет десет сто хиляда хиляди половин половина двойно дузина',
    'cs': 'dva dvě tři čtyři pět šest sedm osm devět deset sto tisíc polovina dvakrát tucet',
    'sk': 'dva dve tri štyri päť šesť sedem osem deväť desať sto tisíc polovica dvakrát tucet',
    'sr': 'два две три четири пет шест седам осам девет десет хиљаду хиљада половина дупло туце',
    'ro': 'doi două trei patru cinci șase şase șapte şapte opt zece sută jumătate dublu',
    'eu': 'bi hiru lau bost sei zazpi zortzi bederatzi hamar ehun mila',
    'is': 'tveir tvær tvö þrír þrjár þrjú fjórir fjórar fjögur fimm sex sjö átta níu tíu hundrað þúsund helmingur tvöfalt',
    'la': 'duo duae tres tria quattuor quinque sex septem octo novem decem centum mille dimidium duplex bis ter',
    'lt': 'du dvi trys keturi keturios penki penkios šeši šešios septyni aštuoni devyni dešimt šimtas tūkstantis dvigubai',
    'sv': 'två tre fyra fem sex sju åtta nio tio hundra tusen hälften dubbelt dussin',
    'gu': 'બે ત્રણ ચાર પાંચ સાત આઠ દસ સો હજાર અડધું અડધો અડધી અડધા બમણું',
    'kn': 'ಎರಡು ಮೂರು ನಾಲ್ಕು ಐದು ಎಂಟು ಒಂಬತ್ತು ನೂರು ಸಾವಿರ ಅರ್ಧ',
    'ml': 'രണ്ട് മൂന്ന് നാല് അഞ്ച് ഏഴ് എട്ട് ഒൻപത് പത്ത് നൂറ് ആയിരം പകുതി',
    'mr': 'दोन तीन चार पाच सहा सात आठ नऊ दहा शंभर हजार अर्धा अर्धे अर्धी दुप्पट',
    'pa': 'ਦੋ ਤਿੰਨ ਚਾਰ ਪੰਜ ਛੇ ਸੱਤ ਅੱਠ ਨੌਂ ਸੌ ਹਜ਼ਾਰ ਅੱਧਾ ਅੱਧੀ ਦੁੱਗਣਾ',
    'te': 'రెండు మూడు నాలుగు ఐదు ఎనిమిది తొమ్మిది పది వంద వెయ్యి సగం',
    'hy': 'երկու երեք չորս հինգ վեց յոթ յոթը ութ ինը տասը տաս հարյուր հազար կես կրկնակի',
    'ka': 'ორი სამი ოთხი ხუთი ექვსი შვიდი რვა ცხრა ათი ასი ათასი ნახევარი ორმაგი',
    'kk': 'екі үш төрт бес алты жеті сегіз тоғыз он мың жарты',
    'mn': 'хоёр гурав дөрөв зургаа долоо найм ес арав мянга хагас',
    'sq': 'dy tre katër pesë gjashtë shtatë tetë nëntë dhjetë njëqind mijë gjysmë dyfish',
    'uz': "ikki to'rt besh olti yetti sakkiz to'qqiz o'n ming yarim",
    'ha': 'biyu uku huɗu hudu biyar shida bakwai takwas goma ɗari dari dubu rabi',
    'ms': 'dua tiga empat lima enam tujuh lapan sembilan sepuluh seratus seribu setengah separuh',
    'ne': 'दुई तीन चार पाँच सात आठ नौ दस सय हजार आधा दोब्बर',
    'tl': 'dalawa dalawang tatlo tatlong apat lima limang anim siyam walo sampu sampung isandaan sandaan libo kalahati doble',
    'ur': 'تین چار پانچ چھ سات آٹھ دس ہزار آدھا آدھی دگنا',
    'si': 'දෙක තුන හතර පහ හය හත අට දහය සියය දහස',
    'yo': 'méjì mẹ́ta mẹ́rin márùn mẹ́fà méje mẹ́jọ mẹ́sàn mẹ́wàá ọgọ́rùn ẹgbẹ̀rún ìdajì',
    'zu': 'kabili kathathu ishumi ikhulu inkulungwane uhhafu amabili amathathu ezimbili ezintathu',
    # fi / hu: validate_single's pinned lists MINUS their homographs (hu hét = week, as in the verified hu#3 question
    # "a hét eleje óta"; hu hat = to affect; fi kuusi = spruce) PLUS hu két (the attributive two), száz, ezer
    'fi': 'kaksi kolme neljä viisi seitsemän kahdeksan yhdeksän kymmenen puolet tusina sata tuhat',
    'hu': 'kettő két három négy öt nyolc kilenc tíz fele tucat száz ezer',
    'bo': '', 'km': '', 'my': '',
}
PINNED_NUMBER_WORDS = ()                      # every v5x language goes through number_words_x
TONE_STRIP = ('yo',)                          # compare with every combining mark removed (tone marks vary)
APOS = {'ʻ': "'", '‘': "'", '’': "'", '`': "'", 'ʼ': "'"}


def _norm_word(w, lang):
    w = unicodedata.normalize('NFC', w).casefold()
    for a, b in APOS.items():
        w = w.replace(a, b)
    if lang in TONE_STRIP:
        w = ''.join(c for c in unicodedata.normalize('NFD', w) if not unicodedata.category(c).startswith('M'))
    return w


def _is_word_char(c):
    cat = unicodedata.category(c)
    return cat[0] in 'LMN' or c in "'’ʻ‘ʼ\u200c\u200d"


def words(t, lang):
    """Word tokens: maximal runs of letters, marks, digits, apostrophes and ZWJ / ZWNJ (a vowel sign never splits)."""
    out, cur = [], []
    for c in t or '':
        if _is_word_char(c):
            cur.append(c)
        else:
            if cur:
                out.append(''.join(cur)); cur = []
    if cur:
        out.append(''.join(cur))
    return [_norm_word(w, lang) for w in out]


_LISTS = {}


def number_list(lang):
    if lang not in _LISTS:
        _LISTS[lang] = [(_norm_word(w, lang), w) for w in NUMBER_WORDS.get(lang, '').split()]
    return _LISTS[lang]


def number_words_x(lang, text):
    """Listed number words present in text as WHOLE words (mark-aware tokens)."""
    ws = set(words(text, lang))
    return [orig for n, orig in number_list(lang) if n in ws]


# ------------------------------------------------------------------ file-level language separation (a 12-template file)
FILE_CHECKS = {
    'bg': (('need', 'ъ', 'no ъ anywhere: reads as Serbian or Russian, not Bulgarian'),
           ('forbid', 'ыэјђћљњџіїєґё', 'letters of Russian / Serbian / Ukrainian in a Bulgarian file')),
    'sr': (('need', 'ј', 'no ј anywhere: reads as Bulgarian or Russian, not Serbian (write Serbian in Cyrillic)'),
           ('forbid', 'ыэъщіїєґё', 'letters of Russian / Bulgarian / Ukrainian in a Serbian file')),
    'kk': (('need', 'әғқңұһі', 'no Kazakh letters (ә ғ қ ң ұ һ і): reads as Russian or Mongolian'),),
    'mn': (('need', 'өү', 'no ө / ү anywhere: reads as Russian, not Mongolian'),
           ('forbid', 'әғқңұһі', 'Kazakh letters in a Mongolian file')),
    'cs': (('need', 'ěřů', 'no ě / ř / ů anywhere: reads as Slovak, not Czech'),
           ('forbid', 'ôľĺŕä', 'Slovak letters (ô ľ ĺ ŕ ä) in a Czech file')),
    'sk': (('need', 'ôľĺŕä', 'no ô / ľ / ĺ / ŕ / ä anywhere: reads as Czech, not Slovak'),
           ('forbid', 'ěřů', 'Czech letters (ě ř ů) in a Slovak file')),
    'ro': (('need', 'ăâîșțşţ', 'no Romanian letters (ă â î ș ț)'),),
    'is': (('need', 'þðæ', 'no þ / ð / æ anywhere: not Icelandic'),),
    'sv': (('need', 'åäö', 'no å / ä / ö anywhere: not Swedish'), ('forbid', 'æøþð', 'Danish / Norwegian / Icelandic letters in a Swedish file')),
    'fi': (('need', 'äö', 'no ä / ö anywhere: not Finnish'),),
    'lt': (('need', 'ąčęėįšųūž', 'no Lithuanian letters (ą č ę ė į š ų ū ž)'),),
    'sq': (('need', 'ëç', 'no ë / ç anywhere: not Albanian'),),
    'ur': (('need', 'ےٹڈڑںھ', 'no Urdu letters (ے ٹ ڈ ڑ ں ھ): reads as Arabic or Persian'),),
    'uz': (('needstr', ("o'", "g'", 'oʻ', 'gʻ', 'o‘', 'g‘', 'o’', 'g’'), "no oʻ / gʻ anywhere: not Uzbek (Latin)"),),
    'yo': (('needmark', '̣', 'no dot-below letter (ẹ ọ ṣ) anywhere: write Yoruba with its full orthography'),),
}


def file_problems_x(lang, texts):
    joined = unicodedata.normalize('NFC', ' '.join(texts)).casefold()
    probs = []
    for rule in FILE_CHECKS.get(lang, ()):
        kind, arg, msg = rule
        if kind == 'need' and not any(c in joined for c in arg):
            probs.append(msg)
        elif kind == 'forbid' and any(c in joined for c in arg):
            probs.append(msg + ' (%s)' % ''.join(sorted(set(c for c in arg if c in joined))))
        elif kind == 'needstr' and not any(s in joined for s in arg):
            probs.append(msg)
        elif kind == 'needmark' and arg not in unicodedata.normalize('NFD', joined):
            probs.append(msg)
    return probs


# ------------------------------------------------------------------ forbidden characters (all languages, all texts)
ZWSP_OK = ('km', 'my', 'bo')                 # U+200B is a customary (optional) word-break hint in these scripts


def char_problems(t, lang=None):
    """Emoji / pictographs, variation selectors, format (bidi) characters other than ZWNJ / ZWJ (and ZWSP in km / my /
    bo), private use. Calibrated: 0 hits on the 36 verified corpora (which carry ZWNJ in kn / te and ZWJ in si)."""
    bad = []
    for c in t or '':
        o = ord(c)
        cat = unicodedata.category(c)
        if (0x1F000 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF or 0xFE00 <= o <= 0xFE0F
                or o == 0x20E3):
            bad.append('emoji or pictograph U+%04X' % o)
        elif cat == 'Cf' and o not in (0x200C, 0x200D) and not (o == 0x200B and lang in ZWSP_OK):
            bad.append('format / bidi character U+%04X' % o)
        elif cat in ('Co', 'Cs', 'Cn'):
            bad.append('private-use or unassigned character U+%04X' % o)
    return sorted(set(bad))


# ------------------------------------------------------------------ writer notes (printed into every writer spec)
PUNCT_NOTE = {
    'am': 'End statements with ። (U+1362) and questions with ? or ፧; use ፣ as the comma.',
    'hy': 'End statements with the Armenian full stop ։ (U+0589; not the ASCII colon) and questions with ? (or put ՞ on the '
          'question word and end with ։).',
    'ur': 'End statements with ۔ (U+06D4) and questions with ؟.',
    'bo': 'End every sentence with ། (shad) and a question with its question particle + །. A shad also closes clauses, and '
          'the generator may insert a sentence after ANY shad between {M} and {S}: put a shad between them only at a real '
          'sentence end.',
    'my': 'End every sentence with ။ and a question with its question particle (နည်း / လဲ ...) + ။; use ၊ as the comma.',
    'km': 'End statements with ។ and questions with ? (or a question word + ។).',
    'si': 'End statements with . and questions with ?.',
    'ne': 'End statements with । (or .) and questions with ?.',
    'mr': 'End statements with . and questions with ?.',
    'pa': 'End statements with । (or .) and questions with ?.',
}
AGREEMENT_NOTE = {
    'bg': 'Masculine nouns take the count form after a numeral (5 стола) but the singular after 1: prefer a unit '
          'abbreviation (кг, л, лв.), a label and a colon, or declare number_dependent.',
    'cs': '1 takes the nominative singular, 2-4 the nominative plural, 5+ the genitive plural: prefer a unit abbreviation '
          '(kg, l, Kč, ks.), a label and a colon, or declare number_dependent. Never a roundabout "v počtu ...".',
    'sk': '1 takes the nominative singular, 2-4 the nominative plural, 5+ the genitive plural: prefer a unit abbreviation '
          '(kg, l, €, ks), a label and a colon, or declare number_dependent. Never a roundabout "v počte ...".',
    'sr': 'As in Russian: 1 / 21 ... singular, 2-4 paucal, 5+ genitive plural: prefer a unit abbreviation (кг, л, дин.), a '
          'label and a colon, or declare number_dependent. Never "у количини од ...".',
    'lt': '1 (21, 31 ... not 11) singular, 2-9 plural, 10-20 and round tens genitive plural: prefer a unit abbreviation '
          '(kg, l, €, vnt.), a label and a colon, or declare number_dependent.',
    'ro': 'Numbers whose last two digits are 00 or 20-99 need "de" before a noun (25 de mere, 105 mere, 120 de mere; '
          'also 25 de lei): a noun or currency right after a slot is number_dependent. Prefer a unit abbreviation (kg, l, '
          'km) or a label and a colon.',
    'la': 'Nouns after a numeral agree (1 singular, else plural; thousands take the genitive): prefer "numerus X est {M}" '
          'style labels, unit abbreviations, or declare number_dependent. Keep scenes that a Latin writer can say '
          'without neologisms; F5 casual = the informal register of a letter.',
    'is': '1 / 21 ... (not 11) agree in the singular, everything else plural: prefer a unit abbreviation (kg, l, kr.), a '
          'label and a colon, or declare number_dependent.',
    'sq': 'A noun after 1 is singular, after any other number plural: prefer a unit abbreviation (kg, l, lekë) or a label '
          'and a colon, or declare number_dependent.',
    'fi': 'After 1 the nominative singular, after every other number the partitive singular (viisi omenaa): prefer a unit '
          'abbreviation (kg, l, €, kpl) or a label and a colon, or declare number_dependent.',
    'tl': 'The linker -ng / na after a spoken numeral depends on the number: write "{M} kilo ng ..." / "{M} piraso ng ..." '
          'with no linker attached to the slot, or declare number_dependent.',
    'zu': 'Concord prefixes attach to the numeral with a hyphen (ngu-{M}, as in v3_61); if the prefix form would change '
          'with the number, declare number_dependent.',
    'hu': 'A noun after a numeral is always singular (öt alma): invariant.',
    'hy': 'A noun after a numeral stays singular: invariant.',
    'ka': 'A noun after a numeral stays singular: invariant.',
    'kk': 'A noun after a numeral stays singular: invariant.',
    'uz': 'A noun after a numeral stays singular: invariant.',
    'mn': 'A noun after a numeral stays singular: invariant.',
    'ms': 'Numerals do not inflect; a classifier (orang, buah, ekor) is optional: invariant.',
    'ha': 'The numeral follows the noun (kwai {M}): invariant.',
    'yo': 'The numeral follows the noun (ẹyin {M}): invariant.',
    'my': 'Noun + {M} + classifier: invariant.', 'km': 'Noun + {M} + classifier: invariant.',
    'bo': 'Noun + {M}: invariant.', 'am': 'Numeral + noun (plural or singular both accepted): invariant.',
    'si': 'Noun + {M} + a suffix such as -ක් written onto the numeral is invariant.',
}
DEFAULT_AGREEMENT = ('A noun after a numeral is singular after 1 and plural otherwise in many of these languages: prefer a '
                     'unit abbreviation, a counter or a label and a colon, or declare number_dependent (at most 2 of 12).')


def language_notes(lang):
    return dict(
        script='/'.join(SCRIPTS[lang]).title() + (' (write Serbian in Cyrillic, never Latin)' if lang == 'sr' else ''),
        digits=('ASCII digits are filled into every slot, with no grouping, as in v3_61 (%d/%d of its %s rows used ASCII '
                'digits only). You write no digit at all, of any script.' % (V3_61_A_INT_ROWS[lang], V3_61_A_INT_ROWS[lang], lang)),
        punctuation=PUNCT_NOTE.get(lang, 'End statements with . and questions with ? (the usual %s punctuation).' % LANG_NAMES[lang]),
        agreement=AGREEMENT_NOTE.get(lang, DEFAULT_AGREEMENT),
        number_words=('the validator lists: %s' % NUMBER_WORDS[lang]) if NUMBER_WORDS.get(lang) else
        ('the validator has no list for %s; the blind verifier flags any number word, ordinal, date or clock time' % lang)
        if lang not in PINNED_NUMBER_WORDS else 'the validator uses the pinned %s list' % lang,
        file_check=[m for _, _, m in FILE_CHECKS.get(lang, ())],
        flagged=lang in FLAGGED)


# ------------------------------------------------------------------ the patch
_PATCHED = []


def patch():
    """Teach the pinned modules the 36 languages (this process only). Idempotent."""
    if _PATCHED:
        return
    VS.SCRIPTS.update({l: SCRIPTS[l] for l in LANGS if l not in VS.SCRIPTS})
    VS.SCRIPT_MIN_FRAC.update({l: MIN_FRAC[l] for l in LANGS if l in MIN_FRAC and l not in VS.SCRIPT_MIN_FRAC})
    orig_nw, orig_fs = VS.number_words_in, VS.file_script_problems

    def number_words_in(lang, text):
        if lang in LANGS and lang not in PINNED_NUMBER_WORDS:
            return number_words_x(lang, text)
        return orig_nw(lang, text)

    def file_script_problems(lang, texts):
        return orig_fs(lang, texts) + (file_problems_x(lang, texts) if lang in LANGS else [])

    VS.number_words_in = number_words_in
    VS.file_script_problems = file_script_problems
    C.SENT_END = SENT_END_X
    _PATCHED.append((orig_nw, orig_fs))


# ------------------------------------------------------------------ calibration on the verified v3_61 corpora
def verified_texts(lang):
    p = os.path.join(SIGNED, 'verified', '%s.verified.json' % lang)
    d = C.load_json(p)
    out = []
    for it in d.get('items', []):
        for k in ('facts_min_first', 'facts_sub_first', 'question', 'distractor_sentence'):
            if it.get(k):
                out.append(('%s#%s.%s' % (lang, it.get('story_id'), k), k, it[k]))
    return d, out


# number-word hits on the verified corpora that are REAL hidden numbers (the verified story itself carries one), so the
# list word is right and the calibration expects the hit: (lang, story id, key, word)
# (all nine are the word "two" / "second" / "half-night" / "hundred" used as a hidden number in a v3_61 story, which the
# v5 rules forbid: the lists are right to find them)
KNOWN_TRUE_HITS = {
    ('ro', '4', 'question', 'două'),                    # "între cele două citiri" = between the two readings
    ('te', '4', 'question', 'రెండు'), ('te', '6', 'question', 'రెండు'),    # "between the two checks"
    ('hy', '4', 'question', 'երկու'), ('hy', '7', 'question', 'երկու'),    # "between the two measurements"
    ('uz', '14', 'facts_min_first', 'yarim'), ('uz', '14', 'facts_sub_first', 'yarim'),   # "yarim tun" = midnight
    ('ha', '7', 'facts_min_first', 'biyu'), ('ha', '7', 'facts_sub_first', 'biyu'), ('ha', '7', 'question', 'biyu'),
    # ("na biyu" = the second checkpoint: an ordinal)
    ('zu', '5', 'question', 'ezimbili'),                 # "phakathi kwalezi zikhathi ezimbili" = between these two times
    ('yo', '2', 'distractor_sentence', 'ọgọ́rùn'), ('yo', '3', 'distractor_sentence', 'ọgọ́rùn'),
    ('yo', '19', 'facts_min_first', 'ọgọ́rùn'), ('yo', '19', 'facts_sub_first', 'ọgọ́rùn'),
    ('yo', '19', 'question', 'ọgọ́rùn'),                 # "ọgọ́rùn-ún" = a hundred; "ìdá ọgọ́rùn-ún" = per cent
}


def calibrate(verbose=True):
    """-> {lang: dict(texts, script_fail, digit_fail, nw_hits, file_ok, sibling)}; prints a table."""
    patch()
    res = {}
    for lang in LANGS:
        d, txts = verified_texts(lang)
        sf, df, hits, cf = [], [], [], []
        for where, k, t in txts:
            plain = C.strip_ph(t)
            if VS.script_problem(lang, plain):
                sf.append((where, VS.script_problem(lang, plain)))
            if VS.digit_chars(plain):
                df.append(where)
            if char_problems(t, lang):
                cf.append((where, char_problems(t, lang)))
            for w in number_words_x(lang, plain) if lang not in PINNED_NUMBER_WORDS else VS.number_words_in(lang, plain):
                hits.append((where, w))
        fp = file_problems_x(lang, [C.strip_ph(t) for _, _, t in txts])
        res[lang] = dict(texts=len(txts), stories=len(d.get('items', [])), lead_in=d.get('lead_in'), script_fail=sf,
                         digit_fail=df, nw_hits=hits, file_problems=fp, char_fail=cf)
    # siblings: a sibling's corpus must FAIL this language's file checks
    sib = {'bg': 'sr', 'sr': 'bg', 'cs': 'sk', 'sk': 'cs', 'kk': 'mn', 'mn': 'kk', 'sv': 'is', 'is': 'sv'}
    for lang, other in sib.items():
        _, txts = verified_texts(other)
        res[lang]['sibling'] = (other, bool(file_problems_x(lang, [C.strip_ph(t) for _, _, t in txts])))
    if verbose:
        print('%-3s %6s %5s  %-11s %-10s %-9s %-8s %s' % ('lg', 'texts', 'story', 'script_fail', 'digit_fail', 'nw_hits', 'file_ok', 'sibling fails'))
        for lang in LANGS:
            r = res[lang]
            print('%-3s %6d %5d  %-11d %-10d %-9d %-8s %s' % (lang, r['texts'], r['stories'], len(r['script_fail']),
                                                             len(r['digit_fail']), len(r['nw_hits']),
                                                             'yes' if not r['file_problems'] else 'NO',
                                                             ('%s:%s' % r['sibling']) if 'sibling' in r else ''))
            for x in r['script_fail'][:3] + [(w, 'number word %s' % n) for w, n in r['nw_hits']] + \
                    [(lang, p) for p in r['file_problems']]:
                print('      %s  %s' % x)
    return res


def selftest():
    ok = True

    def chk(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print('  %s  %s' % ('ok  ' if cond else 'FAIL', name))

    patch(); patch()
    chk('36 languages in 6 chunks of 6, no repeats', len(LANGS) == 36 == len(set(LANGS)) and all(len(c[2]) == 6 for c in CHUNKS))
    chk('every language has a script, a name, a v3_61 row count, a number-word entry and a verified lead_in',
        all(l in SCRIPTS and l in LANG_NAMES and l in V3_61_A_INT_ROWS and l in NUMBER_WORDS and C.verified_lead_in(l)
            for l in LANGS))
    chk('no v5x language is a v5 language', not set(LANGS) & set(C.LANGS))
    chk('pinned script_problem works for all 36 after the patch', all(VS.script_problem(l, 'x') is None or True for l in LANGS))
    res = calibrate(verbose=False)
    sf = {l: len(r['script_fail']) for l, r in res.items() if r['script_fail']}
    chk('verified corpora: 0 script fails in every language %s' % (sf or ''), not sf)
    dfail = {l: len(r['digit_fail']) for l, r in res.items() if r['digit_fail']}
    chk('verified corpora: 0 digit characters outside the slots %s' % (dfail or ''), not dfail)
    unexpected = {l: [(w, n) for w, n in r['nw_hits'] if (l,) + tuple(w.split('#', 1)[1].split('.')) + (n,) not in KNOWN_TRUE_HITS]
                  for l, r in res.items()}
    unexpected = {l: v for l, v in unexpected.items() if v}
    chk('verified corpora: no number-word hit outside the known true hits %s' % (unexpected or ''), not unexpected)
    cfl = {l: len(r['char_fail']) for l, r in res.items() if r['char_fail']}
    chk('verified corpora: 0 [char] problems in every language (they carry ZWNJ in kn / te and ZWJ in si) %s' % (cfl or ''), not cfl)
    fp = {l: r['file_problems'] for l, r in res.items() if r['file_problems']}
    chk('verified corpora: every language passes its own file-level checks %s' % (fp or ''), not fp)
    sibs = {l: r['sibling'] for l, r in res.items() if 'sibling' in r and not r['sibling'][1]}
    chk('sibling corpora FAIL the file checks (bg/sr, cs/sk, kk/mn, sv/is) %s' % (sibs or ''), not sibs)
    miss = [(l, w) for l in LANGS if l not in PINNED_NUMBER_WORDS for n, w in number_list(l)
            if w not in number_words_x(l, 'x %s y' % w)]
    chk('every listed number word is found as a word (%d words)' % sum(len(number_list(l)) for l in LANGS), not miss)
    chk('a vowel sign never splits a word: mr चार found, चारी not; gu ચાર found, ચારે not',
        number_words_x('mr', 'चार किलो') == ['चार'] and not number_words_x('mr', 'चारी')
        and number_words_x('gu', 'ચાર') and not number_words_x('gu', 'ચારે'))
    chk('pinned boundary really fails here (the reason for the patch): pinned regex finds गु-style word inside a longer word',
        re.search(r"(?<![\w'’])%s(?![\w'’])" % re.escape('चार'), 'चारी') is not None)
    chk('yo matched with tone marks stripped (méjì / meji / mèjì)', number_words_x('yo', 'ẹyin meji') and number_words_x('yo', 'ẹyin mèjì'))
    chk('uz apostrophe variants (o‘n, oʻn, o\'n)', all(number_words_x('uz', 'x %s y' % v) for v in ('o‘n', 'oʻn', "o'n")))
    chk('patched SENT_END splits am ። / hy ։ / ur ۔ / my ။ / km ។ / bo །',
        all(C.split_points('a {M} b%s c {S} d' % e) for e in ('።', '։', '۔', '။', '។', '།')))
    chk('question ends: am ፧ ok, hy ՞ inside + ։ ok, my ။ ok, bo ། ok, en-style ? ok; "." is not a question in sv',
        question_end_ok('am', 'x፧') and question_end_ok('hy', 'Որքա՞ն է։') and question_end_ok('my', 'ဘယ်လောက်လဲ။')
        and question_end_ok('bo', 'ག་ཚོད་ཡོད་དམ།') and question_end_ok('sv', 'Hur många?') and not question_end_ok('sv', 'Hur många.'))
    chk('char problems: emoji, bidi override refused; ZWJ (Sinhala), degree sign kept; ZWSP only in km / my / bo',
        char_problems('ok 😀') and char_problems('a\u202eb') and not char_problems('ද්\u200dය 7°C', 'si')
        and not char_problems('ក\u200bខ', 'km') and char_problems('a\u200bb', 'sv'))
    chk('language_notes for every language', all(language_notes(l)['digits'].startswith('ASCII') for l in LANGS))
    print('SELFTEST v5x_lang: %s' % ('0 fail' if ok else 'FAIL'))
    return ok


if __name__ == '__main__':
    if '--calibrate' in sys.argv:
        calibrate()
    elif '--selftest' in sys.argv:
        sys.exit(0 if selftest() else 1)
    else:
        print(__doc__)
