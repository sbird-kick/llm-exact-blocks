#!/usr/bin/env python3
"""Gate for one single-step role-template writer file (stdlib only).

    python3 validate_single.py <writers/SNN_xx.json>

Exits 0 and prints 'VALIDATE ok <n>' when every check passes. Otherwise prints one
'FAIL <item id | file> [<check>] <message>' line per problem, then
'VALIDATE FAIL <k> problem(s)', and exits 1.

What it enforces (see BRIEF.md for the why):
  file     : keys, writer id SNN, known lang code, basename SNN_<lang>.json, exactly 40 items,
             ids SNN-01..SNN-40, one cue shared by every item, file-level script sanity
             (ru vs uk, ar vs fa, zh has no kana)
  per item : exact key set; op / form / program vocab; program consistent with op; roles
             consistent with program; neg_ok is a bool and true only on sub;
             text has exactly one {A} and one {B}, {A} first, words between them, no other braces;
             no digit characters (Unicode categories Nd/No/Nl) in text or cue; no arithmetic symbols;
             no listed number words; no newline/tab; no stray outer whitespace; length bounds;
             story ends in a question mark (Thai exempt); script sanity for the language
  quotas   : add 6, mul 6, sub 14 (7 'A - B' + 7 'B - A'), div 6 (3+3), mod 4 (2+2),
             cmp_more 4 (2+2); >= 10 of the 14 sub items neg_ok;
             forms story >= 12, imperative >= 8, wordformula >= 8
  duplicates: no two texts equal after dropping case, spaces, punctuation and placeholder names
"""
import json
import os
import re
import sys
import unicodedata
from collections import Counter

N_ITEMS = 40
OPS = ("add", "mul", "sub", "div", "mod", "cmp_more")
FORMS = ("story", "imperative", "wordformula")
ITEM_KEYS = {"id", "op", "form", "text", "cue", "program", "roles", "neg_ok", "notes"}
FILE_KEYS_REQUIRED = {"writer", "lang", "items"}
FILE_KEYS_ALLOWED = FILE_KEYS_REQUIRED | {"notes"}

# op -> allowed programs
PROGRAMS = {
    "add": ("answer = A + B",),
    "mul": ("answer = A * B",),
    "sub": ("answer = A - B", "answer = B - A"),
    "cmp_more": ("answer = A - B", "answer = B - A"),
    "div": ("answer = A // B", "answer = B // A"),
    "mod": ("answer = A % B", "answer = B % A"),
}
# program -> roles it implies (for sub/cmp_more the minus programs; div/mod share dividend/divisor)
ROLES = {
    ("add", "answer = A + B"): {"A": "addend", "B": "addend"},
    ("mul", "answer = A * B"): {"A": "factor", "B": "factor"},
}
for _op in ("sub", "cmp_more"):
    ROLES[(_op, "answer = A - B")] = {"A": "minuend", "B": "subtrahend"}
    ROLES[(_op, "answer = B - A")] = {"A": "subtrahend", "B": "minuend"}
ROLES[("div", "answer = A // B")] = {"A": "dividend", "B": "divisor"}
ROLES[("div", "answer = B // A")] = {"A": "divisor", "B": "dividend"}
ROLES[("mod", "answer = A % B")] = {"A": "dividend", "B": "divisor"}
ROLES[("mod", "answer = B % A")] = {"A": "divisor", "B": "dividend"}

# exact per-op totals, and per-op split by program
QUOTA_OP = {"add": 6, "mul": 6, "sub": 14, "div": 6, "mod": 4, "cmp_more": 4}
QUOTA_PROG = {
    ("sub", "answer = A - B"): 7, ("sub", "answer = B - A"): 7,
    ("div", "answer = A // B"): 3, ("div", "answer = B // A"): 3,
    ("mod", "answer = A % B"): 2, ("mod", "answer = B % A"): 2,
    ("cmp_more", "answer = A - B"): 2, ("cmp_more", "answer = B - A"): 2,
}
MIN_SUB_NEG = 10
MIN_FORM = {"story": 12, "imperative": 8, "wordformula": 8}

LATIN_LANGS = ("en", "de", "fr", "es", "it", "pt", "nl", "pl", "tr", "id", "vi", "sw", "fi", "hu")
SCRIPTS = {l: ("LATIN",) for l in LATIN_LANGS}
SCRIPTS.update({
    "ru": ("CYRILLIC",), "uk": ("CYRILLIC",), "el": ("GREEK",),
    "ar": ("ARABIC",), "fa": ("ARABIC",), "he": ("HEBREW",),
    "hi": ("DEVANAGARI",), "bn": ("BENGALI",), "ta": ("TAMIL",), "th": ("THAI",),
    "zh": ("CJK", "IDEOGRAPHIC"), "ja": ("CJK", "IDEOGRAPHIC", "HIRAGANA", "KATAKANA"), "ko": ("HANGUL",),
})
LANGS = tuple(sorted(SCRIPTS))
SCRIPT_MIN_FRAC = {l: 0.95 for l in LATIN_LANGS}  # others default 0.80
SUBSTRING_LANGS = ("zh", "ja", "th", "ko")  # number words matched as substrings (no spaces, or attached particles)

# Short lists of number words / multiplicative words that would smuggle in a hidden operand.
# Deliberately conservative (homographs such as it 'sei', hi 'दो', fa 'نه', bn 'নয়', th 'สาม' left out).
NUMBER_WORDS = {
    "en": "two three four five six seven eight nine ten eleven twelve twenty thirty forty fifty hundred "
          "thousand million dozen dozens twice thrice double doubled triple tripled half halves",
    "de": "zwei drei vier fünf sechs sieben neun zehn elf zwölf zwanzig hundert tausend dutzend "
          "doppelt doppelte doppelten hälfte halb halbe halben zweimal dreimal",
    "fr": "deux trois quatre cinq sept huit neuf dix onze douze vingt cent mille douzaine "
          "double triple moitié demi demie",
    "es": "dos tres cuatro cinco seis siete ocho nueve diez once doce veinte cien ciento mil docena "
          "doble triple mitad",
    "it": "due tre quattro cinque sette otto nove dieci dodici venti cento mille dozzina doppio "
          "triplo metà",
    "pt": "dois duas três quatro cinco seis sete oito nove dez doze vinte cem mil dúzia dobro triplo metade",
    "nl": "twee drie vier vijf zes zeven negen tien twaalf twintig honderd duizend dozijn dubbel "
          "helft tweemaal",
    "pl": "dwa dwie trzy cztery pięć sześć siedem osiem dziewięć dziesięć tysiąc tuzin połowa "
          "podwójnie dwukrotnie",
    "tr": "iki üç dört beş yedi sekiz dokuz yarım yarısı düzine",
    "fi": "kaksi kolme neljä viisi kuusi seitsemän kahdeksan yhdeksän kymmenen puolet tusina",
    "hu": "kettő három négy öt hat hét nyolc kilenc tíz fele tucat",
    "id": "dua tiga empat lima enam tujuh delapan sembilan sepuluh seratus seribu setengah separuh lusin",
    "sw": "mbili tatu nne tano saba nane tisa kumi elfu nusu",
    "ru": "два две три четыре пять шесть семь восемь девять десять сто тысяча дюжина дважды вдвое "
          "втрое половина половину",
    "uk": "два дві три чотири п'ять шість сім вісім дев'ять десять сто тисяча дюжина двічі вдвічі "
          "втричі половина половину",
    "el": "δύο τρία τρεις τέσσερα πέντε έξι επτά εφτά οκτώ οχτώ εννέα εννιά δέκα εκατό χίλια "
          "διπλάσιο διπλάσια μισό μισή",
    "ar": "اثنان اثنين اثنتان ثلاثة ثلاث أربعة أربع خمسة خمس ستة سبعة ثمانية تسعة عشرة نصف ضعف",
    "fa": "دو سه چهار پنج شش هفت هشت ده صد هزار نصف نیم",
    "he": "שתיים שניים שתי שני שלושה שלוש ארבעה ארבע חמישה חמש שישה שש שבעה שבע שמונה תשעה עשרה "
          "חצי כפול",
    "hi": "तीन चार पांच पाँच छह सात आठ नौ दस सौ हज़ार हजार आधा आधी दुगना दोगुना",
    "bn": "দুই তিন চার পাঁচ ছয় সাত আট দশ একশো হাজার অর্ধেক দ্বিগুণ",
    "ta": "இரண்டு மூன்று நான்கு ஐந்து ஏழு எட்டு ஒன்பது பத்து நூறு ஆயிரம் பாதி இருமடங்கு",
    "ko": "다섯 여섯 일곱 여덟 아홉 절반 두 배 세 배",
    "zh": "两 二 三 四 五 六 七 八 九 十 百 千 万 半 双倍",
    "ja": "二 三 四 五 六 七 八 九 十 百 千 万 半",
    "th": "สอง เจ็ด แปด ครึ่ง",
}
MULTIWORD_SPLIT = {"ko": ("두 배", "세 배")}

ARITH_SYMBOLS = "+×*/÷=%−∶"
QMARKS = "?？؟;;"
TRAIL_QUOTES = "\"'”’»」』)）"
KANA = ("HIRAGANA", "KATAKANA")


def _number_word_list(lang):
    raw = NUMBER_WORDS.get(lang, "")
    keep = []
    for mw in MULTIWORD_SPLIT.get(lang, ()):
        keep.append(mw)
        raw = raw.replace(mw, " ")
    keep.extend(raw.split())
    return keep


def number_words_in(lang, text):
    """Return the listed number words found in text (whole-word match, substring for zh/ja/th/ko)."""
    hits = []
    low = text.casefold()
    for w in _number_word_list(lang):
        wl = w.casefold()
        if lang in SUBSTRING_LANGS or " " in wl:
            if wl in low:
                hits.append(w)
        elif re.search(r"(?<![\w'’])" + re.escape(wl) + r"(?![\w'’])", low):
            hits.append(w)
    return hits


def digit_chars(s):
    return [c for c in s if c.isdigit() or unicodedata.category(c) in ("Nd", "No", "Nl")]


def _letter_scripts(s):
    """Script prefix of every letter/mark character, placeholders removed."""
    s = s.replace("{A}", " ").replace("{B}", " ")
    out = []
    for c in s:
        if unicodedata.category(c)[0] in ("L", "M"):
            name = unicodedata.name(c, "")
            if name.startswith("COMBINING"):
                continue  # script-neutral diacritics (e.g. decomposed Vietnamese)
            out.append(name.split(" ")[0].split("-")[0])
    return out


def script_problem(lang, s):
    """None if s is plausibly in lang's script, else a message."""
    want = SCRIPTS[lang]
    scr = _letter_scripts(s)
    if not scr:
        return "no letters at all"
    frac = sum(1 for x in scr if x in want) / len(scr)
    need = SCRIPT_MIN_FRAC.get(lang, 0.80)
    if frac < need:
        return "only %.0f%% of letters are %s (need %.0f%%)" % (100 * frac, "/".join(want), 100 * need)
    if lang == "ja" and not any(x in KANA for x in scr):
        return "Japanese text with no kana at all (reads as Chinese)"
    if lang == "zh" and any(x in KANA for x in scr):
        return "Chinese text contains kana"
    return None


def file_script_problems(lang, texts):
    """File-level sanity that separates near-neighbour languages."""
    joined = " ".join(texts)
    probs = []
    if lang == "uk" and not re.search("[іїєґІЇЄҐ]", joined):
        probs.append("no і/ї/є/ґ anywhere: reads as Russian, not Ukrainian")
    if lang == "ru" and re.search("[іїєґІЇЄҐ]", joined):
        probs.append("contains і/ї/є/ґ: Ukrainian letters in a Russian file")
    if lang == "fa" and not re.search("[یکپچژگ]", joined):
        probs.append("no Persian letters (ی ک پ چ ژ گ): reads as Arabic, not Persian")
    if lang == "ar" and re.search("[پچژگ]", joined):
        probs.append("contains پ/چ/ژ/گ: Persian letters in an Arabic file")
    return probs


def skeleton(text):
    """Text with case, whitespace, punctuation and placeholder names removed."""
    t = text.replace("{A}", "\x00").replace("{B}", "\x00").casefold()
    return "".join(c for c in t if c == "\x00" or unicodedata.category(c)[0] in ("L", "M"))


def check_text(lang, form, text):
    """List of (tag, message) problems for one template text."""
    p = []
    if not isinstance(text, str) or not text:
        return [("text", "text must be a non-empty string")]
    if text != text.strip():
        p.append(("whitespace", "leading/trailing whitespace"))
    if any(c in text for c in "\n\r\t"):
        p.append(("whitespace", "newline or tab inside text"))
    if not (8 <= len(text) <= 400):
        p.append(("length", "text length %d outside 8..400" % len(text)))
    na, nb = text.count("{A}"), text.count("{B}")
    if na != 1 or nb != 1:
        p.append(("placeholder", "need exactly one {A} and one {B}; found %d and %d" % (na, nb)))
    rest = text.replace("{A}", "").replace("{B}", "")
    if any(c in rest for c in "{}｛｝"):
        p.append(("braces", "braces other than the two placeholders"))
    if na == 1 and nb == 1:
        ia, ib = text.index("{A}"), text.index("{B}")
        if ia > ib:
            p.append(("order", "{B} appears before {A}; placeholders are named by order of appearance"))
        else:
            between = text[ia + 3:ib]
            if not any(unicodedata.category(c)[0] == "L" for c in between):
                p.append(("adjacent", "no word between {A} and {B}"))
    d = digit_chars(text)
    if d:
        p.append(("digit", "digit characters in text: %r" % "".join(sorted(set(d)))))
    sym = sorted(set(c for c in text if c in ARITH_SYMBOLS))
    if sym:
        p.append(("symbol", "arithmetic symbols in text: %r (write operations in words)" % "".join(sym)))
    if re.search(r"\{[AB]\}\s*-\s*\{[AB]\}|\s-\s*\{[AB]\}|\{[AB]\}\s*-\s", text):
        p.append(("symbol", "a minus sign next to a placeholder (write 'minus' in words)"))
    nw = number_words_in(lang, text)
    if nw:
        p.append(("numberword", "number words give hidden operands: %s" % ", ".join(nw)))
    if form == "story" and lang != "th":
        end = text.rstrip().rstrip(TRAIL_QUOTES).rstrip()
        if not end or end[-1] not in QMARKS:
            p.append(("question", "a story must end with a question (question mark)"))
    sp = script_problem(lang, text)
    if sp:
        p.append(("script", sp))
    return p


def validate(obj, path=None):
    """Return a list of failure strings 'FAIL <where> [<tag>] <msg>' (empty = ok)."""
    fails = []

    def F(where, tag, msg):
        fails.append("FAIL %s [%s] %s" % (where, tag, msg))

    if not isinstance(obj, dict):
        F("file", "schema", "top level must be a JSON object")
        return fails
    missing = FILE_KEYS_REQUIRED - set(obj)
    extra = set(obj) - FILE_KEYS_ALLOWED
    if missing:
        F("file", "schema", "missing top-level keys %s" % sorted(missing))
    if extra:
        F("file", "schema", "unknown top-level keys %s" % sorted(extra))
    writer = obj.get("writer")
    lang = obj.get("lang")
    if not (isinstance(writer, str) and re.fullmatch(r"S\d\d", writer)):
        F("file", "writer", "writer must look like 'S03', got %r" % (writer,))
        writer = None
    if lang not in SCRIPTS:
        F("file", "lang", "lang %r not one of %s" % (lang, " ".join(LANGS)))
        lang = None
    if path is not None and writer and lang:
        want = "%s_%s.json" % (writer, lang)
        if os.path.basename(path) != want:
            F("file", "filename", "file must be named %s (got %s)" % (want, os.path.basename(path)))
    items = obj.get("items")
    if not isinstance(items, list):
        F("file", "schema", "items must be a list")
        return fails
    if len(items) != N_ITEMS:
        F("file", "count", "need exactly %d items, found %d" % (N_ITEMS, len(items)))

    ids_seen = Counter()
    cues = Counter()
    good = []  # (id, op, program, form, neg_ok, text) for items whose core fields parsed
    for k, it in enumerate(items):
        where = "item#%d" % (k + 1)
        if not isinstance(it, dict):
            F(where, "schema", "item is not an object")
            continue
        iid = it.get("id")
        if isinstance(iid, str) and iid:
            where = iid
        ids_seen[iid] += 1
        if set(it) != ITEM_KEYS:
            if ITEM_KEYS - set(it):
                F(where, "schema", "missing keys %s" % sorted(ITEM_KEYS - set(it)))
            if set(it) - ITEM_KEYS:
                F(where, "schema", "unknown keys %s" % sorted(set(it) - ITEM_KEYS))
        if writer:
            want_id = "%s-%02d" % (writer, k + 1)
            if iid != want_id:
                F(where, "id", "item %d must have id %s (ids run %s-01..%s-%02d in order)"
                  % (k + 1, want_id, writer, writer, N_ITEMS))
        op, form, prog = it.get("op"), it.get("form"), it.get("program")
        ok_core = True
        if op not in OPS:
            F(where, "op", "op %r not one of %s" % (op, " ".join(OPS)))
            ok_core = False
        if form not in FORMS:
            F(where, "form", "form %r not one of %s" % (form, " ".join(FORMS)))
            ok_core = False
        if op in OPS:
            if prog not in PROGRAMS[op]:
                F(where, "program", "program %r not allowed for op %s; allowed: %s"
                  % (prog, op, " | ".join(PROGRAMS[op])))
                ok_core = False
            else:
                want_roles = ROLES[(op, prog)]
                if it.get("roles") != want_roles:
                    F(where, "roles", "roles %r do not match %s (%s) -> must be %r"
                      % (it.get("roles"), prog, op, want_roles))
        neg = it.get("neg_ok")
        if not isinstance(neg, bool):
            F(where, "neg_ok", "neg_ok must be true or false")
        elif neg and op != "sub":
            F(where, "neg_ok", "neg_ok may be true only on op sub (this is %s)" % op)
        notes = it.get("notes", "")
        if not isinstance(notes, str):
            F(where, "schema", "notes must be a string (may be empty)")
        cue = it.get("cue")
        if not isinstance(cue, str) or not cue.strip():
            F(where, "cue", "cue must be a non-empty string")
        else:
            cues[cue] += 1
            if cue != cue.strip() or any(c in cue for c in "\n\r\t"):
                F(where, "cue", "cue has outer whitespace or a newline/tab")
            if len(cue) > 40:
                F(where, "cue", "cue longer than 40 characters")
            if any(c in cue for c in "{}｛｝"):
                F(where, "cue", "braces in cue")
            dc = digit_chars(cue)
            if dc:
                F(where, "digit", "digit characters in cue: %r" % "".join(sorted(set(dc))))
            if lang:
                sp = script_problem(lang, cue)
                if sp:
                    F(where, "script", "cue: " + sp)
        text = it.get("text")
        if lang:
            for tag, msg in check_text(lang, form, text):
                F(where, tag, msg)
        elif not isinstance(text, str):
            F(where, "text", "text must be a string")
        if ok_core and isinstance(text, str):
            good.append((where, op, prog, form, neg is True, text))

    for iid, n in ids_seen.items():
        if n > 1:
            F("file", "id", "id %r used %d times" % (iid, n))
    if len(cues) > 1:
        F("file", "cue", "every item must carry the same cue; found %d different: %s"
          % (len(cues), " | ".join(repr(c) for c in cues)))

    # duplicates
    by_skel = {}
    for where, op, prog, form, neg, text in good:
        by_skel.setdefault(skeleton(text), []).append(where)
    for sk, wh in by_skel.items():
        if len(wh) > 1:
            F(",".join(wh), "duplicate", "texts identical up to case, spacing, punctuation and placeholder names")

    # quotas
    op_n = Counter(g[1] for g in good)
    prog_n = Counter((g[1], g[2]) for g in good)
    form_n = Counter(g[3] for g in good)
    sub_neg = sum(1 for g in good if g[1] == "sub" and g[4])
    for op, n in QUOTA_OP.items():
        if op_n[op] != n:
            F("file", "quota", "op %s: need exactly %d items, found %d" % (op, n, op_n[op]))
    for (op, prog), n in QUOTA_PROG.items():
        if prog_n[(op, prog)] != n:
            F("file", "quota", "op %s with '%s': need exactly %d, found %d" % (op, prog, n, prog_n[(op, prog)]))
    if sub_neg < MIN_SUB_NEG:
        F("file", "quota", "neg_ok true on %d/%d sub items; need at least %d"
          % (sub_neg, op_n["sub"], MIN_SUB_NEG))
    for form, n in MIN_FORM.items():
        if form_n[form] < n:
            F("file", "quota", "form %s: need at least %d, found %d" % (form, n, form_n[form]))

    if lang:
        for msg in file_script_problems(lang, [g[5] for g in good]):
            F("file", "script", msg)
    return fails


def load(path):
    """(obj, [fail strings]) -- a JSON error is reported as a failure, not raised."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), []
    except (OSError, ValueError) as e:
        return None, ["FAIL file [json] cannot read %s: %s" % (path, e)]


def validate_file(path):
    obj, fails = load(path)
    if fails:
        return obj, fails
    return obj, validate(obj, path)


def main(argv):
    if len(argv) != 2:
        print("usage: python3 validate_single.py <writers/SNN_xx.json>")
        return 2
    obj, fails = validate_file(argv[1])
    if fails:
        for f in fails:
            print(f)
        print("VALIDATE FAIL %d problem(s) in %s" % (len(fails), argv[1]))
        return 1
    print("VALIDATE ok %d" % len(obj["items"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
