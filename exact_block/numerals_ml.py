"""Per-language numeral parsing for the multilingual banks. Standard library only; opt in.

Nothing in the rest of this repo imports this file. `numerals.py` stays exactly what it
was (maximal runs of ASCII digit tokens), `data.py` still writes the same English corpus
byte for byte, and a caller that wants per-language behaviour asks for it by name.

WHAT THE MULTILINGUAL BANKS PROMISE, AND WHY THIS FILE STILL EXISTS
The bank generator writes every numeral as plain ASCII digits, with no thousands separator
and no decimal mark on the integer rows. So on the banks themselves the old locator is
already correct. This file is for everything around the banks:
  * checking a template (no digit of ANY script may appear in a template's words);
  * reading text that did not come from the generator: a native-digit numeral ("৩৫০"),
    a grouped one ("250,000", "250.000", "250 000"), a decimal ("3,5" in German);
  * saying, for each language, which of those conventions applies.

THE THREE LAYERS
  1. DIGITS. Every Unicode decimal digit (category Nd) maps to exactly one ASCII digit,
     with no judgement involved: U+09EB BENGALI DIGIT FIVE is 5. `to_ascii_digits` does
     that mapping and nothing else. Characters that LOOK numeric but are not positional
     decimal digits (Ethiopic numerals, superscripts, vulgar fractions, Roman numeral
     letters: Unicode categories No and Nl) are refused, not converted.
  2. GROUPING. Which character may separate groups of three digits depends on the
     language. The table covers the twelve languages where a grouping rule was actually
     established on real text (LOCALE below). For every other language NO grouping rule is
     declared, and this file does not invent one: numerals are read as plain digit runs.
  3. DECIMALS. Each language's decimal mark: from LOCALE where it has an entry, otherwise
     from the declaration the template writer made for that language (LANGS below).
     Decimals are only read when a caller asks (`decimals=True`), because the block and
     the integer banks never use them.

THE THREE GROUPING RULES (they are what keeps "3.64" and "2019 100" from becoming
thousands)
  R1  every group after the first has exactly three digits;
  R2  the first group has one to three digits;
  R3  the separator is ONE character from the language's group set, and that set never
      contains the language's decimal mark.
So "3.141" is 3141 in German (where "." groups) and is NOT a grouped numeral in English
(where "." is the decimal mark). The language decides; the parser does not guess.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

# ------------------------------------------------------------------------------------
# Separators that group thousands in EVERY language. They exist for exactly this job and
# are a decimal mark nowhere. They are invisible in most editors, so their code points are
# asserted: one of them silently replaced by an ASCII space would make "in 2019 100
# people" read as 2019100 in English.
# ------------------------------------------------------------------------------------
NBSP, NARROW_NBSP, THIN_SPACE, FIGURE_SPACE = " ", " ", " ", " "
GROUP_SEPS_ALWAYS = NBSP + NARROW_NBSP + THIN_SPACE + FIGURE_SPACE
assert [ord(c) for c in GROUP_SEPS_ALWAYS] == [0x00A0, 0x202F, 0x2009, 0x2007]

# The Arabic-script separators. U+066C is used only to group thousands and U+066B only as
# a decimal mark, so like the four above they are unambiguous in every language. (This
# pair is an addition made for this module; the rest of the tables are ported unchanged.)
ARABIC_THOUSANDS, ARABIC_DECIMAL = "٬", "٫"

# ------------------------------------------------------------------------------------
# LOCALE: the languages with an established grouping rule. `group` lists every character
# that may separate thousands ("" = none); `decimal` is the decimal mark.
#   * "," groups in en/ja/zh/sw and is the decimal mark in the continental languages;
#   * "." groups in de/es/it/pt/nl and is the decimal mark in en/ja/zh/sw;
#   * a plain ASCII space groups in ru/fr/kk, and also in it/pt (seen in real Italian and
#     Portuguese prose), but NOT in English, where "in 2019 100 people" is two numbers;
#   * the apostrophe (Swiss "1'048'576") groups in no entry, on purpose.
# ------------------------------------------------------------------------------------
LOCALE = {
    "en": {"group": ",", "decimal": "."},
    "ja": {"group": ",", "decimal": "."},
    "zh": {"group": ",", "decimal": "."},
    "sw": {"group": ",", "decimal": "."},
    "de": {"group": ".", "decimal": ","},
    "es": {"group": ".", "decimal": ","},
    "nl": {"group": ".", "decimal": ","},
    "it": {"group": ". ", "decimal": ","},
    "pt": {"group": ". ", "decimal": ","},
    "ru": {"group": " ", "decimal": ","},
    "fr": {"group": " ", "decimal": ","},
    "kk": {"group": " ", "decimal": ","},
}

# ------------------------------------------------------------------------------------
# LANGS: every language shipped in a bank, with
#   name      the language's English name
#   decimal   the decimal mark the template writer declared for the language
#   digits    the name of the language's own decimal digit block, or None when the
#             language writes ASCII digits (the banks always write ASCII; this column
#             says which native digits a checker must be ready to see)
# ------------------------------------------------------------------------------------
_ARABIC_INDIC, _EXT_ARABIC_INDIC = "ARABIC-INDIC", "EXTENDED ARABIC-INDIC"
LANGS = {
    "am": ("Amharic", ".", None),            # Ethiopic numerals are not positional: refused
    "ar": ("Arabic", ".", _ARABIC_INDIC),
    "bg": ("Bulgarian", ",", None),
    "bn": ("Bengali", ".", "BENGALI"),
    "bo": ("Tibetan", ".", "TIBETAN"),
    "cs": ("Czech", ",", None),
    "de": ("German", ",", None),
    "el": ("Greek", ",", None),
    "en": ("English", ".", None),
    "es": ("Spanish", ",", None),
    "eu": ("Basque", ",", None),
    "fa": ("Persian", ".", _EXT_ARABIC_INDIC),
    "fi": ("Finnish", ",", None),
    "fr": ("French", ",", None),
    "gu": ("Gujarati", ".", "GUJARATI"),
    "ha": ("Hausa", ".", None),
    "he": ("Hebrew", ".", None),
    "hi": ("Hindi", ".", "DEVANAGARI"),
    "hu": ("Hungarian", ",", None),
    "hy": ("Armenian", ",", None),
    "id": ("Indonesian", ",", None),
    "is": ("Icelandic", ",", None),
    "it": ("Italian", ",", None),
    "ja": ("Japanese", ".", "FULLWIDTH"),
    "ka": ("Georgian", ",", None),
    "kk": ("Kazakh", ",", None),
    "km": ("Khmer", ".", "KHMER"),
    "kn": ("Kannada", ".", "KANNADA"),
    "ko": ("Korean", ".", "FULLWIDTH"),
    "la": ("Latin", ",", None),              # ASCII digits, never Roman numerals
    "lt": ("Lithuanian", ",", None),
    "ml": ("Malayalam", ".", "MALAYALAM"),
    "mn": ("Mongolian", ",", "MONGOLIAN"),   # Cyrillic Mongolian writes ASCII; the block is for the traditional script
    "mr": ("Marathi", ".", "DEVANAGARI"),
    "ms": ("Malay", ".", None),
    "my": ("Burmese", ".", "MYANMAR"),
    "ne": ("Nepali", ".", "DEVANAGARI"),
    "nl": ("Dutch", ",", None),
    "pa": ("Punjabi", ".", "GURMUKHI"),
    "pl": ("Polish", ",", None),
    "pt": ("Portuguese", ",", None),
    "ro": ("Romanian", ",", None),
    "ru": ("Russian", ",", None),
    "si": ("Sinhala", ".", "SINHALA LITH"),
    "sk": ("Slovak", ",", None),
    "sq": ("Albanian", ",", None),
    "sr": ("Serbian", ",", None),
    "sv": ("Swedish", ",", None),
    "sw": ("Swahili", ",", None),            # LOCALE says "." -- see DECLARATION_CONFLICTS
    "ta": ("Tamil", ".", "TAMIL"),
    "te": ("Telugu", ".", "TELUGU"),
    "th": ("Thai", ".", "THAI"),
    "tl": ("Filipino", ".", None),
    "tr": ("Turkish", ",", None),
    "uk": ("Ukrainian", ",", None),
    "ur": ("Urdu", ".", _EXT_ARABIC_INDIC),
    "uz": ("Uzbek", ",", None),
    "vi": ("Vietnamese", ",", None),
    "yo": ("Yoruba", ".", None),
    "zh": ("Chinese", ".", "FULLWIDTH"),
    "zu": ("Zulu", ",", None),
}

# Where the two sources disagree, LOCALE wins for parsing (it was established on real
# text, the writer's field only says which decimal fills sound natural). Listed here so a
# reader can see the disagreement instead of discovering it. No shipped row is affected:
# the generator writes decimal rows only for languages that declared ".", and Swahili
# declared ",", so the banks contain no Swahili decimal at all.
DECLARATION_CONFLICTS = {
    code: (LOCALE[code]["decimal"], LANGS[code][1])
    for code in sorted(LOCALE) if LOCALE[code]["decimal"] != LANGS[code][1]
}

# Unicode names the first character of each digit block by "<BLOCK> DIGIT ZERO".
_BLOCK_ZERO = {
    "ARABIC-INDIC": 0x0660, "EXTENDED ARABIC-INDIC": 0x06F0, "DEVANAGARI": 0x0966,
    "BENGALI": 0x09E6, "GURMUKHI": 0x0A66, "GUJARATI": 0x0AE6, "TAMIL": 0x0BE6,
    "TELUGU": 0x0C66, "KANNADA": 0x0CE6, "MALAYALAM": 0x0D66, "SINHALA LITH": 0x0DE6,
    "THAI": 0x0E50, "TIBETAN": 0x0F20, "MYANMAR": 0x1040, "KHMER": 0x17E0,
    "MONGOLIAN": 0x1810, "FULLWIDTH": 0xFF10,
}
for _blk, _cp in _BLOCK_ZERO.items():
    _want = _blk + " DIGIT ZERO"
    assert unicodedata.name(chr(_cp)) == _want, (hex(_cp), unicodedata.name(chr(_cp)), _want)
    assert all(unicodedata.decimal(chr(_cp + k)) == k for k in range(10)), _blk
del _blk, _cp, _want


def native_digits(lang: str) -> str:
    """The ten native digits of `lang` in order 0-9, or "" for an ASCII-digit language."""
    blk = LANGS[lang][2]
    return "" if blk is None else "".join(chr(_BLOCK_ZERO[blk] + k) for k in range(10))


def group_seps(lang: str | None) -> str:
    """Every character that may separate thousands in `lang`.

    "" for no language at all (lang "" or None): then nothing ever merges, which is the
    plain-ASCII-runs behaviour of numerals.py. A known language without a LOCALE entry
    gets only the always-separators; it never inherits another language's rule.
    """
    if not lang:
        return ""
    return GROUP_SEPS_ALWAYS + ARABIC_THOUSANDS + LOCALE.get(lang, {}).get("group", "")


def decimal_sep(lang: str) -> str:
    """The decimal mark of `lang`: LOCALE first, then the writer's declaration."""
    if lang in LOCALE:
        return LOCALE[lang]["decimal"]
    if lang in LANGS:
        return LANGS[lang][1]
    raise KeyError(f"no numeral rules for language {lang!r}")


for _code in LANGS:
    # R3 must hold everywhere: a decimal mark that also grouped would make every grouped
    # numeral ambiguous.
    assert decimal_sep(_code) not in group_seps(_code), _code
del _code


# ------------------------------------------------------------------------------------
# Layer 1: digits.
# ------------------------------------------------------------------------------------
def digit_chars(text: str) -> list[str]:
    """Every character in `text` that is a digit or a number sign of any script (Nd/No/Nl).

    This is the template check: a template's words must return [] here, because the
    generator adds the numerals itself and a stray digit would be an extra numeral.
    """
    return [c for c in text if unicodedata.category(c) in ("Nd", "No", "Nl")]


def non_ascii_digits(text: str) -> list[str]:
    """Decimal digits (Nd) that are not ASCII 0-9. A bank row must return []."""
    return [c for c in text if unicodedata.category(c) == "Nd" and not ("0" <= c <= "9")]


def to_ascii_digits(text: str) -> str:
    """Replace every Unicode decimal digit by its ASCII digit. Nothing else changes.

    One code point in, one code point out, so every character offset is preserved. Refuses
    text holding a No/Nl number sign (an Ethiopic numeral, a superscript, a fraction),
    because those have no digit-for-digit ASCII spelling.
    """
    bad = [c for c in text if unicodedata.category(c) in ("No", "Nl")]
    if bad:
        raise ValueError(
            "not positional decimal digits, refusing to convert: "
            + ", ".join(f"{c!r} ({unicodedata.name(c, '?')})" for c in bad))
    return "".join(str(unicodedata.decimal(c)) if unicodedata.category(c) == "Nd" else c
                   for c in text)


# ------------------------------------------------------------------------------------
# Layer 2: grouping. One rule, two spellings (a chain rule over digit runs and a regex),
# which are checked against each other at import time and in the tests.
# ------------------------------------------------------------------------------------
def merge_chains(groups: list[str], seps: list[str | None], lang: str | None) -> list[list[int]]:
    """Which consecutive digit runs form one grouped numeral.

    groups[i] is the digit string of the i-th maximal digit run, in text order; seps[i] is
    the text strictly between run i and run i+1 (None where the caller cannot tell).
    Returns a partition of range(len(groups)) into chains, left to right, greedy.
    """
    gs = group_seps(lang)
    n = len(groups)
    if len(seps) != max(0, n - 1):
        raise ValueError(f"{n} groups need {max(0, n - 1)} separators, got {len(seps)}")
    out, i = [], 0
    while i < n:
        chain = [i]
        while gs and chain[-1] + 1 < n:
            j = chain[-1]
            s = seps[j]
            head_ok = len(groups[chain[0]]) <= 3                       # R2
            sep_ok = s is not None and len(s) == 1 and s in gs          # R3
            tail_ok = len(groups[j + 1]) == 3                           # R1
            if not (head_ok and sep_ok and tail_ok):
                break
            chain.append(j + 1)
        out.append(chain)
        i = chain[-1] + 1
    return out


def _run_pattern(lang: str | None, decimals: bool) -> re.Pattern:
    gs = group_seps(lang)
    grouped = ""
    if gs:
        cls = "[" + "".join(re.escape(c) for c in gs) + "]"
        grouped = r"[0-9]{1,3}(?:" + cls + r"[0-9]{3})+|"
    frac = ""
    if decimals:
        marks = decimal_sep(lang) + ARABIC_DECIMAL
        frac = r"(?:[" + "".join(re.escape(c) for c in marks) + r"](?P<frac>[0-9]+))?"
    # The grouped alternative is tried first, so "1,836" is preferred to "1" at the same
    # start: that is what makes the regex agree with merge_chains' greedy chaining.
    return re.compile(r"(?<![0-9])(?P<int>" + grouped + r"[0-9]+)" + frac + r"(?![0-9])")


_PATTERNS: dict = {}


def run_regex(lang: str | None, decimals: bool = False) -> re.Pattern:
    key = (lang, decimals)
    if key not in _PATTERNS:
        _PATTERNS[key] = _run_pattern(lang, decimals)
    return _PATTERNS[key]


def locatable_surface(surface: str, lang: str | None) -> bool:
    """Is `surface` one integer numeral under `lang`'s grouping rule (ASCII digits only)?"""
    if not surface:
        return False
    gs = set(group_seps(lang))
    if any(c not in "0123456789" and c not in gs for c in surface):
        return False
    if not gs:
        return True
    parts = re.split("[" + "".join(re.escape(c) for c in gs) + "]", surface)
    if len(parts) == 1:
        return True
    return 1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:])


def parse_int(surface: str, lang: str | None) -> int:
    """The integer an integer numeral denotes. Native digits are accepted."""
    s = to_ascii_digits(surface)
    if not locatable_surface(s, lang):
        raise ValueError(f"{surface!r} is not an integer numeral in {lang!r}")
    return int(re.sub(r"[^0-9]", "", s))


def parse_number(surface: str, lang: str) -> int | Decimal:
    """An integer or decimal numeral in `lang`, native digits accepted.

    Returns an int when there is no decimal part and a Decimal (exact, never a float) when
    there is one, so "0,1" in German is Decimal("0.1") and not 0.1000000000000000055.
    """
    s = to_ascii_digits(surface)
    m = run_regex(lang, decimals=True).fullmatch(s)
    if not m:
        raise ValueError(f"{surface!r} is not a numeral in {lang!r}")
    whole = parse_int(m.group("int"), lang)
    if m.group("frac") is None:
        return whole
    return Decimal(f"{whole}.{m.group('frac')}")


def find_numbers(text: str, lang: str, decimals: bool = False) -> list[tuple[int, int, str, int | Decimal]]:
    """Every numeral in `text`: [(start, end, surface, value), ...] in text order.

    Native digits are read (the offsets are those of the original text, because the digit
    mapping is one code point for one). Grouping follows `lang`; decimals are read only
    when asked for.
    """
    ascii_text = to_ascii_digits(text)
    out = []
    for m in run_regex(lang, decimals).finditer(ascii_text):
        surf = text[m.start():m.end()]
        val = parse_number(m.group(0), lang) if decimals else parse_int(m.group(0), lang)
        out.append((m.start(), m.end(), surf, val))
    return out


def token_chains(toks: list[str], runs: list[list[int]], lang: str | None,
                 sep_text=None) -> list[list[int]]:
    """Merge digit-token runs into grouped numerals; separator tokens are left out.

    `toks[j]` is the decoded text of token j and `runs` the maximal digit-token runs (as
    numerals.digit_runs returns them). With a byte-level tokenizer pass
    `sep_text=lambda a, b: tok.decode(ids[a:b])`: a three-byte separator such as THIN SPACE
    is split over several tokens whose one-at-a-time decodes do not join back into the
    character.
    """
    groups = ["".join(toks[i] for i in r) for r in runs]
    if sep_text is None:
        def sep_text(a, b):
            return "".join(toks[j] for j in range(a, b))
    seps = [sep_text(runs[k][-1] + 1, runs[k + 1][0]) for k in range(len(runs) - 1)]
    return [[p for k in chain for p in runs[k]] for chain in merge_chains(groups, seps, lang)]


def coverage_table() -> list[tuple[str, str, str, str, str]]:
    """(code, name, digit system, decimal mark, group separators) for every language."""
    rows = []
    for code, (name, _, blk) in sorted(LANGS.items()):
        grp = LOCALE.get(code, {}).get("group")
        grp_txt = ("special spaces only" if grp is None
                   else " and ".join({",": "comma", ".": "dot", " ": "space"}[c] for c in grp)
                   + " (+ special spaces)")
        rows.append((code, name, blk or "ASCII", {",": "comma", ".": "dot"}[decimal_sep(code)],
                     grp_txt))
    return rows


# ------------------------------------------------------------------------------------
# Import-time agreement check: the chain rule and the regex are the same grammar.
# ------------------------------------------------------------------------------------
def _values_by_chain(s: str, lang: str | None) -> list[int]:
    spans = [m.span() for m in re.finditer(r"[0-9]+", s)]
    groups = [s[a:b] for a, b in spans]
    seps = [s[spans[k][1]:spans[k + 1][0]] for k in range(len(spans) - 1)]
    return [int("".join(groups[k] for k in ch)) for ch in merge_chains(groups, seps, lang)]


def _values_by_regex(s: str, lang: str | None) -> list[int]:
    return [int(re.sub(r"[^0-9]", "", m.group(0))) for m in run_regex(lang).finditer(s)]


_BATTERY = ("250,000", "250.000", "250 000", "4 096 000", "3.64", "536.7", "1,941.88",
            "1.941,88", "2019, 200", "2019 100", "12,345,678", "12,345,6789", "1,2345",
            "100, 200, 300", "1.234 567", "7 500", "1 048 576",
            "9٬000", "1'048'576", "16-17", "0")
for _lang in list(LOCALE) + ["hi", "ar", "", None]:
    for _s in _BATTERY:
        assert _values_by_chain(_s, _lang) == _values_by_regex(_s, _lang), (_s, _lang)
del _lang, _s


if __name__ == "__main__":
    print(f"{'code':<5} {'language':<12} {'digits':<22} {'decimal':<8} group")
    for row in coverage_table():
        print(f"{row[0]:<5} {row[1]:<12} {row[2]:<22} {row[3]:<8} {row[4]}")
    print(f"\n{len(LANGS)} languages; grouping rules for {len(LOCALE)}; "
          f"declaration conflicts: {DECLARATION_CONFLICTS or 'none'}")
