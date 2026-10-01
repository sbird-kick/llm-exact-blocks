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
Vietnamese, Yoruba, Chinese, Zulu. The 25 of `v4` (and of `v5`): ar bn de el en
es fa fr he hi id it ja ko nl pl pt ru sw ta th tr uk vi zh.

## What is in this folder

`make_banks.py` reads the generator and the template files, laid out exactly as they are in
the project's signed-bank folder:

```
banks/
  gen_signed_bank_ml.py            the generator (standard library only)
  verified/<code>.verified.json    61 files: the blind-verified story templates
  distfact/<code>.json             61 files: the first same-kind distractor sentence per story
  distfact2/<code>.json            61 files: the second one, owner of a different kind
  writers_wild/en_wild.json        the 40 English wild-shaped templates
  INPUTS.md5                       the md5 of each of those 185 files
  SHIP.md5                         the md5 of each of the 14 files they generate
```

The 185 input files are about 2.2 MB. To regenerate:

```bash
python banks/make_banks.py            # checks 185 inputs, regenerates banks/v3_61, banks/v4, banks/v4wild, checks 14 md5s
python banks/make_banks.py --check-only
```

It first prints `input check: 185/185 inputs match INPUTS.md5`, and the last line must read
`md5 check: 14/14 files match SHIP.md5` (about half a minute on a laptop). If a single md5
moves, something in the templates or the generator changed, and the bank you have is not
the one every number was measured on. If you change a template on purpose, the input check
names the file and stops; `--skip-input-check` generates anyway, and SHIP.md5 then tells you
whether the rows moved.

Two inputs differ from the project's own copies in a comment only: two docstring passages
of the generator and the `source_note` of `en_wild.json` were reworded so that neither names
a test set or quotes a number measured on one. Neither text reaches a row, and all 14 bank md5s are the project's (the old md5s
are recorded at the top of `INPUTS.md5`).

Four optional checks live beside the generator in the project folder and are not included
here: `audit_bank.py` (minimal pairs complete, no row-level violations, the chance lines of
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

## Bank v5

The v5 bank (25 languages, add / sub / mul / div, 4,352 verified templates, 24 rows each)
lives in [`v5/`](v5/): its clean templates (one file per language in `v5/clean/r1-16/`), the tools that made it, and
`python banks/make_v5.py`, which regenerates it and checks its md5s. See
[`data_gen/V5_TOOLS.md`](../data_gen/V5_TOOLS.md).

## Role banks (English): the operand's role is fixed by the words

In ordinary prose the minuend of a subtraction is usually the larger number and is usually
written first, so a reader can often name it from size or from order alone. The role banks
make both shortcuts useless at once. Each template has two slots, `{M}` (the minuend or the dividend) and `{S}`
(the subtrahend or the divisor), fixed by the template's words, and two written orders,
`first` (M before S) and `second` (S before M). Each number pair X > Y is filled four
ways: both written orders, crossed with M = X (a > b) and M = Y (a < b, a negative
difference or a proper fraction). So on every bank the size rule names the role on
exactly 0 of the a<b rows and the first-written rule on exactly 0 of the `second` rows.
Every row carries `fold` (template-grouped, 0-4; near-duplicate templates share a fold, so
a held-out template never has a near-twin in training), `half` (`a>b` / `a<b`),
`written_order` (`F` / `S`) and `prov.gold_run_idx` (the minuend run, then the subtrahend
run, in written-run order).

```bash
python banks/make_role_banks.py          # checks each bank's CODE.md5, runs its gen, checks its SHIP md5s (a few seconds)
```

### `subrole/`: subtraction, minuend smaller in half the rows and written second in half

190 kept templates (blind-verified, all four filled texts of a template had to pass), 8
number pairs each (2..99), 6,080 rows (`bank/dump/SUBROLE.jsonl`, 6.2 MB, not committed):

| source | kept | rows |
|---|---|---|
| written (12 directed-change frames F01-F12: temperature, money in/out, height then descent, points won/lost, stock in/out, actual vs target, count over time, profit, forward/back, weight over time, water level, votes for/against) | 168/192 | 5,376 |
| `v5` (the English signed v5 subtraction templates, re-verified under the same blind check) | 22/30 | 704 |

Kept per frame: F01 14, F02 16, F03 9, F04 13, F05 16, F06 14, F07 16, F08 16, F09 14, F10 12,
F11 12, F12 16, v5 22. The question must read naturally with a negative answer: undirected
or positive-only questions ("difference", "how many more", "left", "by how much", "gap",
"total") are refused by the validator. `clean/P1.json`, `G1.json`, `G2.json` are the three
chunks (kept and dropped, with the verifier's reasons); `seeds/v5_signed_sub_en.json` is the
30 v5 candidates. `subrole.py selftest` (52 checks) runs here once
`python banks/make_v5.py --join-only` has rebuilt the joined v5 clean file it reads.

### `subrole_g3/`: a held-out top-up of `subrole/`

33 more kept templates (33/36 written, three new units on 36 topics no `subrole/` unit
used, two or three per frame F01-F12), blind-verified exactly like `subrole/`, 23 number
pairs each: 3,036 rows (`bank/dump/SUBROLE_G3.jsonl`, 3.2 MB, not committed), every one
with `fold = -2` and `template_source = written_g3`. It is meant to be scored by a reader
fitted on `subrole/` and never fitted on. `subrole_g3.py` reads `../subrole/` (md5-pinned)
and refuses any template that is a near-twin of a `subrole/` one in either written order.
Its selftest runs here (71 checks).

### `divrole2/`: division, dividend smaller in half the rows and written second in half

`{M}` is the dividend and `{S}` the divisor; the answer is always M / S as an exact
fraction, so on the a<b rows it is a proper fraction (`ans` is then not an integer).
184 kept templates, 8 number pairs each, 5,888 rows (`bank/dump/DIVROLE2.jsonl`, 7.2 MB,
not committed):

| source | kept | fold | rows |
|---|---|---|---|
| written (12 division frames D01-D12: money split among people, food or material shared, amounts poured into containers, a length cut into pieces, distance per time, amount per time, cost per unit, distance per litre of fuel, a mixture or spread, a total over several days, pay per hour, an ingredient per serving) | 164/192 | 0-4 | 5,248 |
| `drrole`, **reference**: the 20 templates of an earlier, smaller division role bank, re-verified blind here | 20/20 | -1 | 640 |
| `v5` (the English v5 division templates, re-verified blind as a calibration) | 0/36 | | 0 |

The reference templates are kept out of the folds on purpose: fit on folds 0-4 and score
the frozen reader on fold -1. Kept written templates per frame: D01 8, D02 11, D03 14,
D04 14, D05 14, D06 15, D07 15, D08 16, D09 14, D10 15, D11 13, D12 15. The selftest of
`divrole2.py` needs the earlier bank's candidate files, which are not shipped; `gen` does
not.
