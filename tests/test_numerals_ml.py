#!/usr/bin/env python3
"""CPU tests for exact_block/numerals_ml.py. Standard library only: no torch, no model.

    python tests/test_numerals_ml.py          (or)      python -m pytest -q tests/test_numerals_ml.py

One test per digit system, one per separator convention, the refusals, and the agreement
between the chain rule and the regex on randomised strings.
"""
from __future__ import annotations

import os
import random
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exact_block import numerals_ml as N  # noqa: E402

# Every language that a bank ships. The table in numerals_ml must cover each of them.
SHIPPED = ("am ar bg bn bo cs de el en es eu fa fi fr gu ha he hi hu hy id is it ja ka kk km "
           "kn ko la lt ml mn mr ms my ne nl pa pl pt ro ru si sk sq sr sv sw ta te th tl tr "
           "uk ur uz vi yo zh zu").split()


def native(lang: str, ascii_number: str) -> str:
    """Spell an ASCII digit string in `lang`'s own digits."""
    d = N.native_digits(lang)
    return "".join(d[int(c)] if c.isdigit() else c for c in ascii_number)


# ------------------------------------------------------------------ the tables
def test_every_shipped_language_has_rules():
    assert sorted(N.LANGS) == sorted(SHIPPED), set(N.LANGS) ^ set(SHIPPED)
    for code in SHIPPED:
        assert N.decimal_sep(code) in (",", "."), code
        assert N.decimal_sep(code) not in N.group_seps(code), code      # rule R3
    assert len(N.coverage_table()) == len(SHIPPED)
    print(f"  tables: {len(SHIPPED)} languages, decimal mark and group set for each")


def test_locale_and_declarations_disagree_only_where_listed():
    # The one known disagreement is listed, and LOCALE wins for parsing.
    assert N.DECLARATION_CONFLICTS == {"sw": (".", ",")}, N.DECLARATION_CONFLICTS
    assert N.decimal_sep("sw") == "."
    assert N.parse_number("2.5", "sw") == Decimal("2.5")
    print("  tables: LOCALE vs writer declarations differ only on sw (listed, LOCALE wins)")


# ------------------------------------------------------------------ digit systems
DIGIT_SYSTEMS = {
    # block name -> a language that uses it
    "ARABIC-INDIC": "ar", "EXTENDED ARABIC-INDIC": "fa", "DEVANAGARI": "hi",
    "BENGALI": "bn", "GURMUKHI": "pa", "GUJARATI": "gu", "TAMIL": "ta", "TELUGU": "te",
    "KANNADA": "kn", "MALAYALAM": "ml", "SINHALA LITH": "si", "THAI": "th",
    "TIBETAN": "bo", "MYANMAR": "my", "KHMER": "km", "MONGOLIAN": "mn", "FULLWIDTH": "ja",
}


def test_each_native_digit_system_reads_as_ascii():
    for blk, lang in DIGIT_SYSTEMS.items():
        assert N.LANGS[lang][2] == blk, (lang, blk)
        s = native(lang, "9085")
        assert s != "9085" and len(s) == 4, (lang, s)
        assert N.to_ascii_digits(s) == "9085", (lang, s)
        assert N.parse_int(s, lang) == 9085, lang
        text = f"x {s} y {native(lang, '17')} z"
        got = [(v, surf) for _, _, surf, v in N.find_numbers(text, lang)]
        assert got == [(9085, s), (17, native(lang, "17"))], (lang, got)
        assert N.non_ascii_digits(text) and N.digit_chars(text), lang
    print(f"  digits: {len(DIGIT_SYSTEMS)} native digit systems read digit for digit")


def test_every_language_sharing_a_block_agrees():
    # hi / mr / ne share Devanagari, fa / ur share Extended Arabic-Indic, ja / zh / ko fullwidth
    for group in (("hi", "mr", "ne"), ("fa", "ur"), ("ja", "zh", "ko")):
        spellings = {native(l, "4096") for l in group}
        assert len(spellings) == 1, group
        for l in group:
            assert N.parse_int(native(l, "4096"), l) == 4096
    print("  digits: languages sharing a digit block spell and read it identically")


def test_bengali_distractor_case():
    # A writer once wrote a distractor in Bengali digits: the text-level check sees it,
    # the ASCII locator would not. non_ascii_digits is the check that catches it.
    text = "দোকানে 350 টি আম ছিল, দোকানটি ১৯৭৫ সালে খোলা হয়।"
    assert N.non_ascii_digits(text) == list("১৯৭৫")
    assert [v for *_, v in N.find_numbers(text, "bn")] == [350, 1975]
    print("  digits: a native-digit distractor is found and flagged")


def test_ascii_languages_have_no_native_block():
    for code in SHIPPED:
        if N.LANGS[code][2] is None:
            assert N.native_digits(code) == ""
            assert N.parse_int("1234", code) == 1234
    print("  digits: ASCII-only languages parse plain runs")


def test_non_positional_numerals_are_refused():
    for bad in ("፩፪",            # Ethiopic numerals one, two (additive, not positional)
                "5²",                 # superscript two
                "½",                  # vulgar fraction one half
                "Ⅻ"):                 # Roman numeral twelve
        assert N.digit_chars(bad), bad
        try:
            N.to_ascii_digits(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad!r} should be refused")
    # a template with no digits of any kind passes the check
    assert N.digit_chars("Il termometro segnava {M} °C alle sette?") == []
    print("  digits: No/Nl number signs are refused, never converted")


# ------------------------------------------------------------------ grouping conventions
def vals(text, lang, decimals=False):
    return [v for *_, v in N.find_numbers(text, lang, decimals=decimals)]


def test_comma_groups_en_ja_zh_sw():
    for lang in ("en", "ja", "zh", "sw"):
        assert vals("250,000 and 12,345,678", lang) == [250000, 12345678], lang
        assert vals("250.000", lang) == [250, 0], lang              # "." does not group here
        assert vals("2019, 200", lang) == [2019, 200], lang         # a list, two characters
        assert vals("2019,200", lang) == [2019, 200], lang          # R2: 4-digit head
        assert vals("1,2345", lang) == [1, 2345], lang              # R1: 4-digit tail
    print("  groups: comma in en/ja/zh/sw, with both refusals")


def test_dot_groups_de_es_nl():
    for lang in ("de", "es", "nl"):
        assert vals("250.000 und 3.141", lang) == [250000, 3141], lang
        assert vals("250,000", lang) == [250, 0], lang              # "," is the decimal mark
        assert vals("536.7", lang) == [536, 7], lang                # R1: 1-digit tail
    print("  groups: dot in de/es/nl")


def test_space_groups_ru_fr_kk_and_it_pt():
    for lang in ("ru", "fr", "kk"):
        assert vals("2 500 000", lang) == [2500000], lang
        assert vals("2.500", lang) == [2, 500], lang
    for lang in ("it", "pt"):
        assert vals("1.836.000 e 1 507 695", lang) == [1836000, 1507695], lang
        assert vals("1.234 567", lang) == [1234567], lang           # mixed, accepted
    assert vals("2 500 000", "en") == [2, 500, 0]                   # ASCII space never groups in en
    assert vals("in 2019 100 people", "fr") == [2019, 100]          # R2 still holds
    print("  groups: space in ru/fr/kk, dot and space in it/pt, never in en")


def test_special_spaces_group_everywhere():
    for lang in SHIPPED:
        for sep in (N.NBSP, N.NARROW_NBSP, N.THIN_SPACE, N.FIGURE_SPACE, N.ARABIC_THOUSANDS):
            assert vals(f"7{sep}500", lang) == [7500], (lang, hex(ord(sep)))
    assert vals("7 500", "") == [7, 500]                       # no language: no merge
    print(f"  groups: NBSP / narrow NBSP / thin / figure space / U+066C in all {len(SHIPPED)}")


def test_languages_without_a_rule_do_not_borrow_one():
    for lang in ("hi", "ar", "pl", "tr", "vi", "th"):
        assert vals("250,000", lang) == [250, 0], lang
        assert vals("250.000", lang) == [250, 0], lang
        assert vals("250 000", lang) == [250, 0], lang
    print("  groups: a language with no declared rule never inherits another's")


def test_apostrophe_groups_nowhere():
    for lang in SHIPPED:
        assert vals("1'048'576", lang) == [1, 48, 576], lang
    print("  groups: the apostrophe is not a group separator in any language")


# ------------------------------------------------------------------ decimals
def test_decimal_marks_per_language():
    for code in SHIPPED:
        mark = N.decimal_sep(code)
        assert N.parse_number(f"12{mark}75", code) == Decimal("12.75"), code
    assert N.parse_number("1,941.88", "en") == Decimal("1941.88")
    assert N.parse_number("1.941,88", "de") == Decimal("1941.88")
    assert N.parse_number("2 500,5", "fr") == Decimal("2500.5")
    assert N.parse_number("0,1", "de") == Decimal("0.1")
    assert N.parse_number("3٫5", "ar") == Decimal("3.5")            # Arabic decimal separator
    assert N.parse_number(native("ar", "3") + "٫" + native("ar", "25"), "ar") == Decimal("3.25")
    assert isinstance(N.parse_number("250,000", "en"), int)
    print(f"  decimals: the declared mark in all {len(SHIPPED)} languages, exact Decimal values")


def test_decimals_are_opt_in():
    assert vals("3.64 ERA", "en") == [3, 64]                        # integers only by default
    assert vals("3.64 ERA", "en", decimals=True) == [Decimal("3.64")]
    assert vals("3,5 kg und 3.141", "de", decimals=True) == [Decimal("3.5"), 3141]
    assert vals("100, 200, 300", "de", decimals=True) == [100, 200, 300]
    print("  decimals: read only when asked; a comma list stays a list")


# ------------------------------------------------------------------ token level
def test_token_chains():
    toks = ["2", "5", "0", ",", "0", "0", "0", " ", "k", "m"]
    runs = [[0, 1, 2], [4, 5, 6]]
    assert N.token_chains(toks, runs, "en") == [[0, 1, 2, 4, 5, 6]]
    assert N.token_chains(toks, runs, "de") == runs                 # "," is de's decimal mark
    assert N.token_chains(toks, runs, "") == runs                   # no language: identity
    toks2 = ["5", " ", "0", "0", "0"]
    assert N.token_chains(toks2, [[0], [2, 3, 4]], "hi") == [[0, 2, 3, 4]]
    print("  tokens: chains merge across one separator token and leave it out")


# ------------------------------------------------------------------ agreement
def test_chain_rule_equals_regex_randomised():
    rnd = random.Random(20260929)
    pieces = ["0", "7", "12", "123", "1234", "12345", "000", "048", "576"]
    joiners = [",", ".", " ", " ", " ", "٬", ", ", " x ", "-", "/", "'"]
    bad = 0
    langs = list(N.LOCALE) + ["hi", "ar", "th", ""]
    for lang in langs:
        for _ in range(2000):
            s = "".join((rnd.choice(joiners) if t else "") + rnd.choice(pieces)
                        for t in range(rnd.randint(1, 6)))
            if N._values_by_chain(s, lang) != N._values_by_regex(s, lang):
                bad += 1
    assert bad == 0, bad
    print(f"  agreement: chain rule == regex on {2000 * len(langs)} random strings")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"running {len(tests)} numeral tests (standard library only)")
    for t in tests:
        print(f"- {t.__name__}")
        t()
    print(f"all {len(tests)} numeral tests pass")


if __name__ == "__main__":
    main()
