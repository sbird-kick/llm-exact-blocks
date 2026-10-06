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
number pairs each (2..99), 6,080 rows (`bank/dump/SUBROLE.jsonl`, 6.2 MB; shipped as `data/banks/subrole/SUBROLE.jsonl`):

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
184 kept templates, 8 number pairs each, 5,888 rows (`bank/dump/DIVROLE2.jsonl`, 7.2 MB; the
5,248 rows of folds 0-4 are shipped as `data/banks/divrole2/DIVROLE2_folds0-4.jsonl`):

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

## Bank v5x: v5 in 36 more languages, with question forms (all six chunks)

Bank v5x is v5 (same row schema, wild-shaped distractors, add / sub / mul / div, 24 rows
per template) for the 36 languages of `v3_61` that v5 lacks, plus a question-form axis:
every template is asked in one of eight forms: F0 plain (facts, then the question), F1 question
first, F2 an instruction ("Work out how many ..."), F3 conditional ("If ..., how many ...?"),
F4 indirect ("Tell me how many ..."), F5 casual chat, F6 a statement ending in a blank ___,
F7 a dialogue (one speaker gives the facts, another asks). It was written in six chunks of
six languages; every chunk was blind-verified and passed all eight of its go / no-go bars
(for C6, after Tibetan was rewritten once):

| chunk | languages (kept / 48 each) | kept | dropped | rows |
|---|---|---:|---:|---:|
| C1 | bg 45, cs 47, hu 46, ro 42, sk 47, sr 47 | 274 | 14 | 6,576 |
| C2 | eu 48, fi 48, is 48, la 45, lt 47, sv 47 | 283 | 5 | 6,792 |
| C3 | gu 47, kn 48, ml 48, mr 47, pa 48, te 48 | 286 | 2 | 6,864 |
| C4 | hy 46, ka 47, kk 46, mn 47, sq 45, uz 46 | 277 | 11 | 6,648 |
| C5 | ha 48, ms 46, ne 48, tl 48, ur 48, zu 38 | 276 | 12 | 6,624 |
| C6 | am 48, bo 47, km 47, my 45, si 48, yo 44 | 279 | 9 | 6,696 |
| **all** | **36 languages** | **1,675** | **53** | **40,200** |

```bash
python banks/make_v5x.py              # per chunk: joins v5x/clean/<C>/<lang>.json, runs v5x.py gen -> banks/v5x/bank/<C>/, checks 6 md5s
python banks/make_v5x.py C4           # one chunk only
```

Each chunk is generated on its own (`signed_A_int.jsonl`, 18.6-22.7 MB per chunk; md5s in
`v5x/SHIP_V5X_<C>.md5`). The rows are also shipped ready to use in `data/banks/v5x/<C>.jsonl`
(see below). The clean templates are one file per language in `v5x/clean/<C>/` plus
`index.json`; `banks/clean_split.py` joins them byte for byte into the clean file `v5x.py`
reads (md5s in `make_v5x.py`) and splits a clean file of your own the same way.
`v5x/manifest/` holds the 144 writer-unit specs of all six chunks (`gen` reads their forms and
story ids). `v5x.py selftest` runs here (76 checks).

## Bank v5div (25 languages): division with the dividend smaller in half the rows

In ordinary prose the dividend of a division is almost always the larger number, so "divide
the big number by the small one" is nearly always right, and a reader can name the
dividend without reading the words. Bank v5div makes that shortcut useless in v5's 25
languages. Every template is a division story whose dividend `{M}` and divisor `{S}` are
fixed by the words, and every number pair is filled four ways: dividend larger or smaller,
crossed with dividend written first or second. On the rows where the dividend is smaller
the answer is a fraction ("what fraction of ...": 3/8) or a percentage below 100, and the
templates were written and verified so that such an answer reads naturally. Four kinds of
division, about a quarter of the rows each: `share` (an amount split equally: litres per
vat), `rate` (an amount per hour, per kilometre ...), `ratio` (what fraction of ...) and
`pct` (what percent of ...), each in three shapes, with v5's distractor arms (`base`, `T`,
`ex`, `sem`, `T+s`, `T+ex+sem`).

851 kept templates (31-36 per language), 24 rows each: 20,424 rows (66.6 MB). They are the
pilot P1 and chunks R1-R3, all blind-verified; each chunk passed its go / no-go bars (R1
after four languages rewrote their dropped templates, R2 after an Arabic noun-form fix). The
bank's last chunk (R4) is the project's fresh test set for it and is not shipped. On the
shipped rows, "the dividend is the larger written number" is right on exactly 10,212 of
20,424 and "the dividend is written first" on exactly 10,212 of 20,424.

```bash
python banks/make_v5div.py            # checks v5div/CODE.md5, runs v5div.py gen (about 10 s), checks the project's 6 md5s
python banks/make_v5div.py --out DIR  # the same, keeping the bank in DIR
```

`v5div/v5div.py` is the project's tool (writer validator, blind close, report, clean, gen,
selftest: `python3 v5div.py selftest`, 111 checks, runs here); it imports the v5 tools in
`v5/`. For Arabic it carries a counted-noun markup, `{X|dual|3-10|11-99|100}`: the
generator picks the noun form that agrees with the filled number. `v5div/clean/` holds the
four clean files (kept and dropped templates, with the verifier's reasons). The rows are
shipped in three parts in `data/banks/v5div/`.

## Bank v6ms (20 languages): multi-step problems with every intermediate stored

Bank v6ms holds two- and three-step word problems written natively in 20 languages (ar bn
de el en es fa he hi id ja ko pl ru sw ta th tr vi zh). Each template is a small program over
named slots, fixed by a manifest cell, which the generator executes exactly; every row
stores the program, the value of every step and which written number feeds which step (its
def-use structure), so a reader can be fitted on the whole computation and not just on the
answer. A round is one stratum in all 20 languages (20 writer units of 8 templates), blind
verified by executing the formula the verifier wrote (a text matches only when the formula
gives the gold answer on 8 different fills). Only the 9 closed rounds (of 17 planned) are
shipped:

| round | stratum | programs | templates kept | rows |
|---|---|---|---:|---:|
| G1r01-G1r04 | SL | straight-line chains, `(A o1 B) o2 C`, `((A o1 B) o2 C) o3 D`, `(A o1 B) o2 (C o3 D)`; signed | 603 | 19,208 |
| G2r01 | CB | conditionals: `t = A o1 B; IF t cmp C THEN t o2 D ELSE ...` | 147 | 4,676 |
| G2r02 | SEL | `max/min(A, B) o C`, `max/min(A o1 B, C o1 D)` | 145 | 4,592 |
| G2r03 | INT | `ceil((A o1 B) / C)`, `floor(...)`, `(A o1 B) mod C`, `ceil(A / B) o2 C` | 153 | 4,896 |
| G3r01 | INV | unknown start `(C o1 A) o2 B`, unknown group size `(C - B) / A` | 127 | 4,064 |
| G3r02 | CMQ | "how many more": `(A o1 B) - C`, always positive | 151 | 4,832 |
| **all** | | | **1,326** (of 1,440 written) | **42,268** |

32 rows per template (4 distractor arms x 2 draws x 2 twins x 2 written orders), minus 164
fills the generator refused. Each round writes `rows_le5.jsonl` (at most 5 written numerals,
31,716 rows) and `rows_n6.jsonl` (more than 5, 10,552 rows). Rows carry three fold columns:
`v6.lang_fold` (5 folds of 4 languages, for leave-language-out), `v6.script_fold` (latin,
greek_cyrillic, abjad, brahmic, cjk) and `v6.tmpl_fold` (1 + md5(template id) mod 5; all
rows of a template share it). `v6.program`, `v6.steps` and `v6.leaf_run_idx` hold the
program, every step's value and which written number is which leaf.

```bash
python banks/make_v6ms.py             # checks v6ms/CODE.md5 (402 inputs), regenerates the 9 rounds (about 5 min), checks 18 md5s
python banks/make_v6ms.py G3r01       # one round (about 35 s)
```

`v6ms/v6ms.py` is the project's tool (shapes, exact execution, validator, manifest, close,
report, clean, gen, selftest: `python3 v6ms.py selftest`, 2,556 checks, runs here). Its
templates are in the writer files: `v6ms/writers/<lang>/<unit>.json` (the 180 accepted
units, all their templates), `v6ms/accept/` (which file each unit accepted), and
`v6ms/clean/` (the verifier's verdict per template; gen uses only the kept ones). The rows
are shipped in `data/banks/v6ms/<round>_le5.jsonl` and `<round>_n6.jsonl`.

## The generated rows, ready to train on: `data/banks/`

The training banks' rows are also shipped as plain JSON-lines files, so you can train on
them without running anything. Every file is under 25 MB and listed with its md5 in
`data/banks/ROWS.md5`; [`data/DATA_banks.md`](../data/DATA_banks.md) has one line per file
(bank, languages, rows, bytes, md5, the command that made it).

| folder | bank | rows | files |
|---|---|---:|---|
| `data/banks/subrole/` | subrole | 6,080 | `SUBROLE.jsonl` |
| `data/banks/divrole2/` | divrole2, folds 0-4 only | 5,248 | `DIVROLE2_folds0-4.jsonl` |
| `data/banks/v5x/` | v5x, 36 languages | 40,200 | `C1.jsonl` ... `C6.jsonl` |
| `data/banks/v5div/` | v5div, 25 languages | 20,424 | `part_000.jsonl` ... `part_002.jsonl` (`cat` them for the generator's file) |
| `data/banks/v6ms/` | v6ms, 20 languages | 42,268 | `<round>_le5.jsonl`, `<round>_n6.jsonl` for 9 rounds |

```bash
python banks/make_bank_data.py               # md5 of every shipped row file (a couple of seconds)
python banks/make_bank_data.py --rebuild     # regenerate every bank and compare (about 7 minutes)
```

Not shipped as rows: `v3_61`, `v4`, `v4wild` and `v5` (regenerate them byte for byte with
`make_banks.py` and `make_v5.py`); `subrole_g3` and divrole2's 640 reference rows (fold -1),
which are meant for scoring a reader, never for fitting it; the abstain banks AB1 and ABX
(their filling tool is not shipped); and the audience demo bank (`gen_audience_v2.py`
writes it in a second).

## Abstain bank AB1 (English): questions the block must NOT answer, each with an in-set twin

`abstainbank/clean/` holds 503 blind-verified English templates (8 clean files). Each
template is one scene with two questions over the same facts: `question_abs`, which is NOT
one + - x / of two written numbers (a percent, a square root, a remainder, a two-step sum,
a yes/no ...), and `question_pos`, an ordinary one-step twin (`pos_op` add / sub / mul / div
on `{M}` and `{S}`) in the same register, so that a gate cannot learn "unusual wording =>
abstain". Both questions come in two fact orders (`facts_first`: `{M}` before `{S}`;
`facts_second`: `{S}` first), and a template was kept only if all four texts passed the
blind verifier. `abs_prog` is the abstain answer as a program over the slots (exact
fractions: `+ - * / %`, `pct pctof avg sq cube pow sqrt floor ceil round gcd lcm fact comb
digitsum ndigits rev digitprod incl posts tri max min abs`, `word(...)` for a name, `text`
for a word answer, `none` for not answerable; `c` is the hidden constant `hidden_c`, e.g. 10
in "rounded to the nearest ten").

| file | what | kept | dropped |
|---|---|---:|---:|
| `clean_abstainbank_C1.json` | percent 23, power_root 16, inexact_div 20, noninteger 18, underspecified 5 | 82 | 23 |
| `clean_abstainbank_C2.json` | average 25, hidden_const 25, two_step 15, number_theory 9, compare 11 | 85 | 20 |
| `clean_abstainbank_C3.json` | counting 20, ratio 23, multi_step 18, digits 12, lookup 13 | 86 | 19 |
| `clean_abstainbank_C4.json` | rounding 19, estimate 21, date_time 14, nonnumeric 13, no_arith 17 | 84 | 21 |
| `clean_abstainbank_R1.json` | re-pilot: underspecified | 28 | 2 |
| `clean_abstainbank_R2.json` | re-pilot: number_theory | 24 | 6 |
| `clean_abstainbank_R345.json` | re-pilots R3 + R4 + R5 merged: nonnumeric (13 + 19 + 29) | 61 | (not kept in the merge) |
| `clean_abstainbank_R6.json` | re-pilot: nonnumeric, rewritten so the wording does not give the class away | 53 | 7 |
| **all** | 20 classes | **503** | |

Twins: add 138, sub 145, mul 127, div 93; registers: story 382, quiz 121; twin styles: plain
239, near_miss 139 (in-set wording that sounds out-of-set: "how far apart", "split equally",
"times as many"), unusual 63, signed 62 (an a<b subtraction with a negative answer). Tags:
`alt_single` (82: a near-miss text where the verifier said a hasty reader might answer with
one operation; kept, tagged) and `fill_level` (7).

**The nonnumeric class: read this before you use it.** Its answer is a word (yes / no, a
named option, odd / even). In C4's 13 nonnumeric templates and the 61 of R345 the question
type shows in the wording: a bag-of-words classifier on the question alone tells the
abstain question from its twin on 23/26 (C4) and 121/122 (R345) held-out texts. So a
result on those 74 templates says nothing beyond "it read the question's words". R6's 53
were rewritten so that the twins borrow the abstain side's words and the reverse; the same
classifier gets 99/106 (93.4%) there. Report the three groups on separate lines.

**Rows are not generated here.** The project's tool that fills these templates
(`abstainbank.py`) imports its earlier abstain tool and pinned copies of the v5 tools, so it
does not run on its own in this repository and is not shipped. The templates are complete:
to make rows, fill `{M}`, `{S}` (and `{T}`, `{U}` where present) with numbers, compute the
abstain answer with `abs_prog` and the twin's with `pos_op`, and keep a fill only if no
single + - x / of any two written numbers equals the abstain answer (otherwise the block
would be right to fire; for `compare` and `lookup` the answer is one of the written numbers
itself). The project's bank used about 8 rows per template (small, mid and
huge numbers where the operation makes sense).

## Abstain bank ABX (PARTIAL: rounds 1-5 of chunk X01): AB1 in other languages, with question forms

ABX is AB1 (same classes, same `abs_prog` language, same in-set twins and keep rule) written
natively in the 60 non-English languages of `v3_61`, 96 templates per language when
finished, and every template (abstain question and twin alike) is asked in one of the eight
v5x question forms F0-F7 (`template.form`). A template was kept only if all four of its
texts passed the blind verifier AND the verifier judged each text to be in its form. **Only
rounds 1-5 of the pilot chunk X01 are cleaned so far**: 6 languages, five rounds of 16
templates per language, 390 of 480 kept (round 2 was written after a drop analysis of round
1 and fixed its brief; German went from 6/16 to 13/16). Round 6 of X01 and the next chunk
(X02) have been verified in the project but not cleaned yet, so they are not here.

| lang | r1 | r2 | r3 | r4 | r5 | kept | dropped |
|---|---:|---:|---:|---:|---:|---:|---:|
| de German | 6/16 | 13/16 | 16/16 | 13/16 | 13/16 | 61 | 19 |
| es Spanish | 13/16 | 14/16 | 13/16 | 12/16 | 14/16 | 66 | 14 |
| fr French | 13/16 | 13/16 | 13/16 | 12/16 | 14/16 | 65 | 15 |
| it Italian | 11/16 | 14/16 | 13/16 | 14/16 | 16/16 | 68 | 12 |
| nl Dutch | 15/16 | 14/16 | 14/16 | 11/16 | 13/16 | 67 | 13 |
| pt Portuguese | 10/16 | 12/16 | 14/16 | 11/16 | 16/16 | 63 | 17 |
| **X01 r1-r5** | **68/96** | **80/96** | **83/96** | **73/96** | **86/96** | **390** | **90** |

Kept per class: average 26, compare 14, counting 24, date_time 6, digits 15, estimate 25,
hidden_const 28, inexact_div 23, lookup 13, multi_step 16, no_arith 7, noninteger 27,
nonnumeric 17, number_theory 14, percent 24, power_root 24, ratio 29, rounding 22, two_step
25, underspecified 11. Per form: F0 54, F1 47, F2 53, F3 46, F4 50, F5 47, F6 51, F7 42.
Twins: add 102, sub 101, mul 101, div 86. The AB1 warning about the nonnumeric class applies
here too (no text-classifier check has been run on ABX's 17). Each template also carries
`gloss_en` (an English gloss), `hidden_word_en` and `twin_cue_en`. The clean files are one per
language and round, in `abstainbank_x/clean/X01r1/` ... `X01r5/`, each with `index.json`;
`python banks/clean_split.py join banks/abstainbank_x/clean/X01r3 <out.json>` (or any other
round) rebuilds the project's single file of that round byte for byte. As for AB1, the
filling tool is not shipped (it builds on AB1's) and no rows are shipped; the AB1 notes on
filling apply unchanged.

## The audience demo bank (English, DEMO-GRADE)

`audience/` is a small bank written for a live demonstration: the kinds of prompt an
audience types when it is handed the model. It is **demo-grade**: not pre-registered, never
used as a result, and filled from code templates written by four writers (`writers/W1-W4.json`:
`text` with `{A}`, `{B}`, `{C}` slots, slot ranges, `constraints`, the `answer` as a Python
expression, the `operands`). 200 templates in five categories:

| category | templates | what | example |
|---|---:|---|---|
| `single` | 90 | one in-set step (add 20, sub 25, mul 22, div 23) | "{A} plus {B} equals what?" |
| `multi` | 40 | two or three steps | "... picked up {B} more ..., then {C} passengers got off. How many remain?" |
| `oos` | 35 | an operation outside the four (percent, average, remainder, square, rounding ...) | "What number is {A} percent of {B}?" |
| `noarith` | 20 | no arithmetic: restate a number, the answer already given, a trick question | "Tom's jersey number is {A}. What is Tom's jersey number?" |
| `lookalike` | 15 | looks like one step and is not quite (an absolute gap, a sum of three, a chain) | "What is the age gap between them?" |

A Sonnet audit (`audit.json`) dropped 1 template (ambiguous), leaving 199. `gen_audience.py`
fills each up to 16 times (bank v1, 3,163 rows); `gen_audience_v2.py` imports it unchanged and
fixes two fill problems that a later blind verification found ("1 goals"; a filled number
equal to another numeral, so a second pair answers): bank v2, 3,161 rows, 2.2 MB, not
committed. Bank v2 then passed the blind verification: answer confirmed 199/199, label
agreement 191/192, blocking flags 1/199, unnatural 7/199; `verified_templates_v2.json` lists
the 197 templates that passed everything.

```bash
cd banks/audience
python3 gen_audience_v2.py --final --audit audit.json     # -> bank_v2/; the md5 lines of bank_v2/BANK_v2.md5 must be those of SHIP_AUDIENCE_V2.md5
python3 gen_audience.py --final --audit audit.json        # v1 -> bank/ (md5s in SHIP_AUDIENCE_V1.md5); then:
python3 gen_audience_v2.py --selftest                     # v2 against v1, 13 checks
```

The prose OTHER bank that was blind-verified with it is not shipped: its generator also
builds a held-out test file and quotes a test-set result, so it needs more than a comment
rewording first.
