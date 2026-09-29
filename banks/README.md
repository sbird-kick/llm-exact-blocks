# banks/ -- the multilingual signed word-problem banks

This folder regenerates three banks of one-step word problems in up to 61 languages, byte
for byte, from their verified templates. The generated files are 330 MB together, so they
are never committed: you regenerate them with one command and `SHIP.md5` proves you got
the real thing.

| bank | languages | rows (bank A + bank B, integer fills) | what it adds |
|---|---|---|---|
| `v3_61` | 61 (bank A), 36 of them also bank B | 99,712 + 10,560 | one distractor per row, four hardness arms (easy, matched, sem1, sem2) |
| `v4` | 25 | 58,160 + 5,274 | v3's rows for those 25 languages plus rows with 4-5 numerals (multi2, multi3) |
| `v4wild` | English only, 40 templates | 2,544 | a third same-kind quantity inside the facts ("a list of three"); addition and product as well as subtraction |

`v3_61` also writes decimal fills (`signed_A_dec.jsonl` 4,016 rows in 26 languages,
`signed_B_dec.jsonl` 352 rows in 11) and `v4` writes them for its 25 languages (1,664 + 64).
The block in this repo cannot read decimals (the locator sees "7.5" as two numbers), so
`data_gen/bank_to_corpus.py` skips them.

The 61 languages: Amharic, Arabic, Bulgarian, Bengali, Tibetan, Czech, German, Greek,
English, Spanish, Basque, Persian, Finnish, French, Gujarati, Hausa, Hebrew, Hindi,
Hungarian, Armenian, Indonesian, Icelandic, Italian, Japanese, Georgian, Kazakh, Khmer,
Kannada, Korean, Latin, Lithuanian, Malayalam, Mongolian, Marathi, Malay, Burmese, Nepali,
Dutch, Punjabi, Polish, Portuguese, Romanian, Russian, Sinhala, Slovak, Albanian, Serbian,
Swedish, Swahili, Tamil, Telugu, Thai, Filipino, Turkish, Ukrainian, Urdu, Uzbek,
Vietnamese, Yoruba, Chinese, Zulu. The 25 of `v4` (and of the coming `v5`): ar bn de el en
es fa fr he hi id it ja ko nl pl pt ru sw ta th tr uk vi zh.

## What has to be in this folder

`make_banks.py` needs the generator and the template files it reads, laid out exactly as
they are in the project's signed-bank folder (`_role/signed/` in the project tree, the same
folder the earlier student export contained):

```
banks/
  gen_signed_bank_ml.py            the generator (standard library only)
  verified/<code>.verified.json    61 files: the blind-verified story templates
  distfact/<code>.json             61 files: the first same-kind distractor sentence per story
  distfact2/<code>.json            61 files: the second one, owner of a different kind
  writers_wild/en_wild.json        the 40 English wild-shaped templates
```

That is 185 files, about 2.2 MB. Once they are in place:

```bash
python banks/make_banks.py            # regenerates banks/v3_61, banks/v4, banks/v4wild; checks 14 md5s
python banks/make_banks.py --check-only
```

The last line must read `md5 check: 14/14 files match SHIP.md5`. If a single md5 moves,
something in the templates or the generator changed, and the bank you have is not the one
every number was measured on.

Optional checks that live beside the generator in the project folder and can be placed here
too: `audit_bank.py` (minimal pairs complete, no row-level violations, the chance lines of
the shortcut rules), `audit_bank_v4.py` (the same, operator-aware, for v4 and v4wild),
`validate_distfact.py` and `validate_wild.py` (the distractor-sentence and wild-template
gates).

## The row format, in one paragraph

One JSON object per line. The fields you will use most: `text` (the prompt, ending with
the language's own "The answer is"), `lang`, `a` and `b` (for subtraction the minuend and
the subtrahend, fixed by the story's meaning, not by size), `ans`, `op`, `kind` (`pos`:
minuend larger; `neg`: minuend smaller, answer negative), `variant` (`min_first` /
`sub_first`: which operand is written first), `pair_key` (the two halves of a minimal pair
share it and are word-identical), `dist_hardness` (none / easy / matched / sem1 / sem2 /
multi2 / multi3 / wildT), `ds` (the distractor values), `story_id`. Because every story is
filled both ways round and in both orders, "the bigger number is the minuend" is right on
exactly half the rows and "the first number is the minuend" on exactly half; anything
better than a half has to come from reading the words.

## Until the template files arrive

The template files and the generator are added to this folder separately from the code on
this branch. Until they are, `make_banks.py` stops and lists the files it is missing. The
md5s in `SHIP.md5` were checked by regenerating all three banks from the project's own
copies of exactly these files: 14 of 14 matched.
