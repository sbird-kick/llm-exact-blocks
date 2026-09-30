# BANK v5 -- wild-shaped distractors in 25 languages, add / sub / mul / div: design

Written 2026-09-29, before any template was written; the bank it describes is now finished (4,352 templates kept
of 4,800, `clean/clean_v5_r1-16.json`). **This is an edited copy for this repository**: citations of the project's
own logs are removed, results measured on real-problem test sets are described in words only, and the closing list
of open decisions is left out (the finished bank is tier T2, 16 units per language; number-dependent templates are
kept and tagged `numdep`).
`REPORT` is the project's report on bank v4 (not shipped); its numbers are measured on the synthetic banks.

## 1. Why

- On real single-step word problems (a test set, never opened for this design), a pair reader fitted on our
  synthetic banks picks the right two numerals much less often than on the synthetic banks, and less often than the
  same reader fitted on real problems.
- Every such transfer miss keeps one gold operand and swaps the other for a look-alike, most often the
  middle item of a list; and the fitted weights are subtraction-specific (they do poorly on products).
- v4 added 4-5-numeral rows in 25 languages, but every v4 row is subtraction (`v4/gen_v4.log`: `op {'subtraction':
  58160}`); the wild shapes and add / product exist only in English, 40 templates (REPORT:15, :31), where the fitted
  reader got addition 281/640 (REPORT:105) and the gold pair is the outer two numerals on 1,088/2,544 rows (REPORT:86).
- The host itself separates easy distractors almost perfectly and same-kind ones much less: selection by attribution
  1,922/1,923 (99.9%) dpre/easy and 1,628/1,685 (96.6%) dpre/matched against 974/1,202 (81.0%) dpre/sem1 and 717/827
  (86.7%) dsuf/sem2; pos 5,611/5,916 (94.8%) vs neg 3,980/4,447 (89.5%) (REPORT:140-149). One or two extra same-kind
  numerals cost it about ten points of exact answers, 3,717/16,778 (22.2%) vs 13,820/42,816 (32.3%) (REPORT:170).
  So difficulty is graded, and v5 makes the grade an explicit, balanced axis (section 4).
- The subtraction-order lie must not recur: when every subtraction row has minuend >= subtrahend a role read has
  nothing to prove (on the real test set every subtraction row has the minuend larger).
- The scope as decided: the 25 v4 languages, operations add / sub / mul / div, many more templates than before, the
  host model's ceiling on distractors to be located, and the work run in chunks across usage-limit resets.

## 2. What a template is

One scene per template, written by a native-quality writer in the language (brief `BRIEF_v5_writer.md`):

| slot | meaning |
|---|---|
| `{M}` `{S}` | the two operands. sub: minuend / subtrahend; div: dividend / divisor (exact); add, mul: the two operands |
| `{T}` | the look-alike, inline in the facts: same kind and unit as an operand, never used by the question |
| `{D}` | once in each of two extra sentences: `ex_sentence` (a role-free number of a different kind) and `sem_sentence` (same kind and unit, an owner absent from the facts) |

Seven strings per template: `facts_first` ({M} before {S}), `facts_second` ({S} before {M}, the phrases moved with
their nouns), `base_first` / `base_second` (the same facts without {T}), `question`, `ex_sentence`, `sem_sentence`.
Metadata: `op`, `shape` (list / other_time / diff_owner), `t_mimics` (M / S / both), `signed` (sub: a negative answer
natural), `sign_convention`, `div_mode` (group_size / group_count), `numeral_grammar` (invariant / number_dependent,
declared as in SUBVAR / DIVMOD), `topic`, `quantity_kind`, `verb`, glosses. Every numeral is a placeholder; which
slots are operands is the slot name; nothing else in any string may be a number (digits of any script, number words,
ordinals: `validate_v5.py`).

**The similarity ladder** (easiest first), carried per distractor on every row as `d_rungs`:

| rung | distractor | source |
|---|---|---|
| `L0_kind` | different owner AND different kind (a room or route number) | `ex_sentence` (v2 continuity) |
| `L1_owner_sent` | same kind and unit, another owner, its own sentence | `sem_sentence` (v3 continuity) |
| `L1_owner` | same kind and unit, another owner, inside the facts | `{T}`, shape diff_owner |
| `L2_time` | the same owner at another time | `{T}`, shape other_time |
| `L3_list` | a same-kind list; the question picks two (add/sub) or one plus the other operand (mul/div) | `{T}`, shape list |

**Division.** The dividend is filled as an exact multiple. With distinct whole numbers an exact quotient is smaller
than its dividend, so on div rows the size rule "the dividend is the larger" is right by construction (the selftest
prints 144/144); v5 breaks the WRITTEN-ORDER confound for div (dividend first 50%), not the size confound. Only sub
separates role from size. The question must mark the dividend in words and never mention leftovers or ask how many are
"needed" (the lessons of an earlier division bank: in Japanese only 15/30 exact-division texts were kept after a
forced-exactness frame, and formula texts whose words do not mark the dividend were dropped).

**Subtraction.** At least 2 of every 3 sub templates are `signed`: filled both ways (kind pos M larger / kind neg M
smaller, negative answer), so the size rule is right on at most 2/3 x 1/2 + 1/3 = 66.7% of sub rows (selftest 96/144).
Unsigned sub ("how many more", "left") is filled M-larger only, its twin a distractor redraw.

## 3. Units, slices and tiers

- **Writer unit** = 12 templates, exactly 1 per (op x shape), one language, one HALF-SLICE of 3 scenario topics. 24
  slices x 6 topics (`v5_common.SLICES`), 48 half-slices; unit k of language i takes half-slice (k - 1 + 7i) mod 48, so
  the 32 units of a language never share a topic and the languages spread evenly (selftest: T1 uses all 48 half-slices,
  3-5 times each). Size choice: 12 templates x 7 strings = 84 strings, the load of a DIVMOD step-1 writer (90 texts).
- **Verifier unit** = one group of 5 languages x one unit number = the 5 writer units of that number, 240 blind texts
  (12 x 4 x 5); an Opus-medium verifier per 4-5 languages (the size that worked in earlier verification passes).
- `{T}` position: the manifest fixes, per unit and cell, where `{T}` goes in `facts_first` (rotating first / middle /
  last so every (op, shape, position) cell fills evenly; each unit uses each position 4 times); `facts_second` is the
  writer's choice within the unit balance rule.

| tier | units / language | writer units | templates | verifier units | blind texts | rows (24 / template) |
|---|---|---|---|---|---|---|
| T1 | 8 | 200 | 2,400 | 40 | 9,600 | 57,600 |
| **T2 (recommended)** | 16 | 400 | 4,800 | 80 | 19,200 | 115,200 |
| T3 | 32 | 800 | 9,600 | 160 | 38,400 | 230,400 |

For scale: v4wild has 40 English templates (REPORT:15); v3's per-language 3-numeral rows run 256 (sw) to 1,792 (en)
(counted from `v4/signed_A_int.jsonl`, 20,928 total); at T2 every language gets 16 x 12 x 8 = 1,536 T-arm rows plus
16 x 12 x 4 = 768 ex/sem rows with 3 numerals.

## 4. Rows per template and the difficulty cells

`gen_v5.py`, 24 rows per template, 12 in each written order, every row one half of a minimal pair:

| arm | numerals | text | rows |
|---|---|---|---|
| base | 2 | base facts only (the no-distractor control) | 2 orders x 2 twins = 4 |
| T | 3 | facts with `{T}` | 2 orders x 2 twins x 2 value tiers = 8 (one tier asks the question first) |
| ex | 3 | base + ex sentence | 1 order x 2 twins = 2 |
| sem | 3 | base + sem sentence | the other order x 2 twins = 2 |
| T+s | 4 | facts with `{T}` + one sentence (ex on even templates, sem on odd) | 2 x 2 = 4 |
| T+ex+sem | 5 | facts with `{T}` + both sentences | 2 x 2 = 4 |

Twins: signed sub value swap (pos / neg); unsigned sub distractor redraw; add, mul slot swap; div divisor swap (same
dividend f1*f2, divisor f1 or f2). Per row and per distractor: `d_rungs`, `d_positions` (before / between / after the
operands, from the filled text), `d_tiers` (V0_len: a digit length no operand has; V1_same_len; V2_near: within
max(2, x/10) of an operand) with the planned tier in `d_tiers_intended`, `n_numerals_written`, `variant` (written
order), `qorder`, plus `attr_pairs` / `attr_collision` (section 5). Sentences go before, after, or between `{M}` and
`{S}` at a sentence break (at least 6 of 12 templates per unit must have one in both bases; placement mid on half the
draws there).

**Per-cell minimum** (pooled over the 25 languages, planned arithmetic at T2; T1 is half, T3 double):

| cell (3 numerals unless stated) | rows at T2 |
|---|---|
| op x inline rung (L1_owner, L2_time, L3_list) | 400 templates x 8 = 3,200 each |
| op x sentence rung (L0_kind, L1_owner_sent) | 1,200 x 2 = 2,400 each |
| op x rung x planned value tier | inline 400 x 2/3 x 4 = 1,067; sentence 1,200 / 3 x 2 = 800 |
| op x rung x written order | inline 1,600; sentence 1,200 |
| op x inline rung x `{T}` position | facts_first alone 400 / 3 x 4 = 533 guaranteed (plus writer-chosen facts_second rows) |
| op x sentence rung x position | between >= 1/2 x 1/2 x 2,400 = 600; before and after the rest |
| op x inline rung x 4 and x 5 numerals | 400 x 4 = 1,600 each |

**Stated minimum: every designed 3-numeral cell (op x rung x one of tier / order / position) >= 500 rows at T2
(>= 250 at T1, >= 1,000 at T3), and every (op x rung) cell >= 96 rows per language at T2.** `gen_v5.py --min-cell 500`
refuses a T2 bank that misses it (tiers are checked on the planned tier; the drawn tier is reported beside it). In a
scale test on 1,200 relabelled planted templates (a quarter of T2) the planned-tier cells were balanced and the drawn
tier fell back from V1 / V2 to V0 on 153 of 38,400 placed values, all in the single-digit categories (V1 is
infeasible there); that run is not kept.

## 5. Numbers

- Categories: sub and add reuse v4's eight (`gen_signed_bank_ml.py` lines 183-215, reimplemented verbatim in effect);
  mul and div have eight new ones (1x1 digits up to 2x4 digits; div 99 x 2,999 at most), drawn by seeded rejection
  sampling. Each template rotates 7 of the 8 categories over its arms. v4's blake2b keying (`v5_common.seeded`);
  nothing shared by a minimal pair is keyed on the twin (the redraw twin's distractors excepted).
- Distractor values come from the OPERAND VALUE UNIVERSE (value memorisation 0/768 values in the selftest, 0/38,400
  in the scale test), rank-balanced over low / mid / high, distinct, digit-substring-free with every operand and answer.
- **One-pair-only, strict form** (`host_attr_v5.gold_unique_anyop`): the gold pair is the only pair of the row's
  numerals that gives |answer| under ANY of the four operators, and only under its own (so 3, 4, 9 with 3 + 9 = 12 is
  refused because 3 x 4 = 12; 4, 2 is refused for sub because 4 / 2 = 2). The looser v4 rule (own operator only,
  `audit_bank_v4.py` lines 72-74) is reported beside it.
- **Attribution for every op** (`host_attr_v5.py`, orchestrator update 2): per row the result every candidate pair
  gives under the row's op (both orders for sub and div, exact quotients only) and a collision flag when two pairs
  share a result; the draw PREFERS values with no collision at all and flags the fallback. host_selection.py covers
  subtraction with 3 numerals only (REPORT section 3d: 0 right, 4 spurious wrong on 1,264 add/product rows). Selftest: 0/576
  rows with a collision; the scale test 31/28,800.

## 6. Cost, chunking, verification

Anchors (earlier passes of the project): DIVMOD step-1 writers 20 agents, 1,873,842 tokens, 17.3 min, 90 texts each i.e. 93,692 per
writer; step-13 writers 40 agents, 3,287,815 tokens, 35.5 min, 60 short templates each; v3 semantic pass
22 agents, 1.28M tokens, 9.6 min; Opus verification 455,426 tokens for 1,800 texts in 5.9 min (253
per text) and 504,381 for 2,400 texts in 7.9 min (210 per text). A v5 blind text is a 3-numeral story
plus question, estimated 2-3 times a DIVMOD text: 420-760 Opus tokens per text.

| | one unit | one ROUND = 25 writer units + 5 verifier units (300 templates) | T1 (8 rounds) | T2 (16) | T3 (32) |
|---|---|---|---|---|---|
| writers, Sonnet tokens | 90k-125k | 2.25M-3.13M | 18.0M-25.0M | 36.0M-50.0M | 72.0M-100.0M |
| verifiers, Opus tokens (full: 4 texts / template) | 101k-182k | 0.51M-0.91M | 4.0M-7.3M | 8.1M-14.6M | 16.2M-29.1M |
| verifiers, Opus, orders + 25% bases | 63k-114k | 0.32M-0.57M | 2.5M-4.6M | 5.1M-9.1M | 10.1M-18.2M |
| wall, one round in parallel | writers ~17-35 min (DIVMOD 20 / 40 agents), verifiers ~6-8 min | | | | |

A chunk of N writer units costs N x 90k-125k Sonnet tokens; a chunk of N verifier units N x 101k-182k Opus tokens.
A round (one unit per language, then one verifier unit per group) is the natural chunk to fit a quota window: its
writer half is between DIVMOD step 1 and step 13 in size.

**On "verification will dominate".** In raw tokens it does not, on these ledger lines: at T2 the writers take
36-50M Sonnet tokens against 8.1-14.6M Opus tokens for full verification. Verification dominates the plan's quota only
if one Opus token costs it more than about 2.5-6 Sonnet tokens; no ledger line gives that ratio. The bigger levers are
therefore the tier and the writer unit size (fewer, larger units read the brief fewer times; not measured).

**Verification sampling** (`make_blind_v5.py --base-sample F`): both order texts of EVERY template are always
verified (they carry the operand and role labels); the two base composites (base + ex, base + sem) are verified for a
seeded fraction F. At F = 0.25 the Opus cost falls to 62.5%. Risk: for 75% of templates the base facts and both extra
sentences are never read blind, and they feed 16 of the template's 24 rows (base 4, ex 2, sem 2, T+s 4, T+ex+sem 4).
The DIVMOD per-text drop rates were 141/1,800 = 7.8% (`singlestep/divmod/CLEAN_NOTES_div.md:26`) and 341/2,400 =
14.2% (`CLEAN_NOTES_fix.md:26`); defects of that order would enter those rows (an unnatural sentence, a sem sentence
the question does not exclude, a base whose M and S were swapped). Such templates are tagged `bases_unverified` on
every row, so quoted numbers can exclude them.

**Workflow** (all state recomputed from files; nothing appended, nothing overwritten):
1. `status_v5.py --write-manifest` (done: `manifest_v5.json`, 800 writer units, 160 verifier units).
2. `status_v5.py --next 25 --tier T2` -> the next writer units, round-robin over languages; launch one Sonnet writer
   per unit with `BRIEF_v5_writer.md` (it writes `writers/<lang>/<uid>.json` and loops on `validate_v5.py`).
3. `status_v5.py --accept`: each validated unit against everything accepted for its language (char-4-gram Jaccard
   >= 0.45); a duplicate is re-queued by `--next` as attempt K+1 with the duplicated template ids; one stamp per
   attempt in `accept/`.
4. `status_v5.py --next 5 --kind verifier` -> ready verifier units (their 5 writer units accepted; verification of a
   finished round starts while later rounds are written); `make_blind_v5.py <unit>`; one Opus-medium verifier per unit
   with `VERIFY_v5.md` (`check_v5.py --format` until OK).
5. `check_v5.py --report`, then `check_v5.py --clean --out clean/clean_v5.json` (D1 label mismatch drop, D2 flag drop,
   numdep keep+tag, signed-read-unnatural demote), then `gen_v5.py --clean ... --out-dir bank --min-cell 500`.
6. Stop at any moment: every unit's state is on disk; `--next` resumes where it stopped.

**Near-duplicate threshold 0.45** (`validate_v5.py --calibrate`): pairwise char-4-gram Jaccard among existing,
distinct templates has p95 0.10-0.21 and max 0.21-0.37 in en / ru / hi / ko / th verified stories and 0.295 in
v4wild; a noun-swapped copy scores 0.595 and a light rephrase 0.481. The verified zh / ja / ar / de sets have maxima
0.54-0.65: same-frame story pairs (e.g. the zh train / flight arrival frames), exactly what v5 is meant to avoid.

## 7. Compatibility with the existing tools

- Row format: every key of a v4 and a v4wild row is present on every v5 row (selftest, 54 keys); `a` / `b` are the
  role-ordered operands, so `finalise_role_bank_ml2.py` writes gold_run_idx [a, b] unchanged; pair_key twins are
  complete; `bank_version` v5, `source` signed_bank_v5, row ids `sg5:`. Dump 3-numeral rows with --max-runs 3 and the
  4-5-numeral rows with --max-runs 5, as v4 did (REPORT section 6). Size bound: the v4 r5 dumps were 61,417,593,727
  bytes for 16,778 rows (REPORT:168), 3.66 MB per row, so T2's 115,200 rows are at most ~420 GB at 8B.
- `wild_op` of division is NEW, `aquot`. `wild_reader.py` / `wild_reader2.py` map only aspread / asum / aprod
  (`wild_reader.py:61`) and their `opres` treats any other op as a product (`wild_reader.py:149-150`): pair selection
  is op-agnostic, but their attribution / end-to-end numbers on div rows would be wrong. `audit_bank_v4.py` has no
  division (`APPLY`, line 19) and would report the redraw twins as `distractor_differs_within_pair`; use
  `validate_v5.py --bank` or the gen_v5 audit. `host_selection.py` is subtraction-only; use `host_attr_v5.py`.
- The pinned reader (3 runs) reads the T / ex / sem arms; the 2-numeral base arm is the no-distractor control.
- `distractor_pos`: None on the base and T arms (v4wild's convention for the inline {T}), `dpre` / `dsuf` / `dmid` on
  the single-sentence ex / sem arms (v4 had dpre / dsuf; dmid is new), `dmulti` on the 4-5-numeral arms (v4's value);
  `dist_positions` and `d_positions` carry the real placement everywhere.
- Writers never open the 0.7 MB manifest: `status_v5.py --next` prints each writer unit's spec for its prompt.

## 8. Files (all new, all in `signed/v5/`; md5s in `V5_CODE.md5`)

| file | what |
|---|---|
| `BRIEF_v5_writer.md` | per-unit writer brief: fences, schema, quotas, English examples, validator loop |
| `VERIFY_v5.md` | Opus-medium blind verifier brief |
| `v5_common.py` | languages, groups, slices, schema, quotas, text helpers, planted English units (selftests only) |
| `validate_v5.py` | writer-unit gate (+ accepted-unit near-dups), `--bank` row gate, `--corpus` diversity + cross-unit near-dups, `--calibrate`, `--selftest` |
| `status_v5.py` | manifest, per-unit state, `--next`, `--accept`, `--selftest` |
| `manifest_v5.json` | every writer and verifier unit, stable ids |
| `make_blind_v5.py` | blind + key files per verifier unit, `--base-sample`, `--selftest` |
| `check_v5.py` | `--format`, `--report`, `--clean`, `--selftest` |
| `host_attr_v5.py` | op-general pair attribution, `--selftest` |
| `gen_v5.py` | fill + audit + md5, `--selftest` |

Selftests, run locally with `python3` (Python 3.14.7) on 2026-09-29: `host_attr_v5` 22 checks, `validate_v5` 33,
`gen_v5` 17, `status_v5` 21, `make_blind_v5` 11, `check_v5` 12; each prints `SELFTEST <name>: 0 fail`. They build
their fake trees under `v5/_selftest_tmp/` and delete it.
