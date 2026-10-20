# data/more: more training rows (TRAIN split of the project's in-force split rules only)

207,332 rows in 40 files (every data file under 25 MB, 340 MB in all), added 2026-10-20 to what `data/wild/` and
`data/banks/` already ship. Everything here is a **train** row. Nothing here is a validation, test, dropped or
sealed row, and no row text of one of those was read to build this folder.

**The split rule.** The project's arithmetic data is cut into train / val / test (and dropped) by its stamped split rules
(official splits win; lineage families never straddle; any train row sharing a 10-gram with another source's val / test
row is dropped). The manifests in force when this was built are the AMEND5b overlay (53 manifest files, `MANIFESTS.md5`
file md5 `529502974a7073473fae45b3c50b6bf3`). A row is here only if its manifest split is `train`. **Training split only:
build your own held-out fold from it, as with folds 1-4.** The `fold` column (1-4) is `1 + md5(family) % 4` of the
row's lineage family, so a family never straddles two folds: hold one fold out before you fit and score it once.
The older `data/wild/` rows keep the older fold system; do not mix the two when you hold a fold out (the families of
the old and new rows are not cross-checked).

| path | what | rows | languages | license |
|---|---|---:|---|---|
| `wild/ape210k/` | Ape210K problems (def-use pool, at most 5 digit runs) | 95,808 | zh | not clearly stated, see `wild/ape210k/LICENSE.md` |
| `wild/math23k/` | Math23K | 11,676 | zh | not found, see its `LICENSE.md` |
| `wild/mathqa/` | MathQA train rows not already in `data/wild/mathqa/` | 1,622 | en | Apache-2.0 |
| `wild/asdiv/` | ASDiv rows not already in `data/wild/asdiv/` | 185 | en | CC BY-NC 4.0 |
| `wild/mawps/` | MAWPS | 196 | en | none stated |
| `ours/selfcue_v1/` | generated: `omni` 2,589, `tmpl_small` 2,738, `tmpl_large` 1,415, `twin` 528 | 7,270 | 82 | MIT (ours) |
| `ours/selfcue_v2/` | generated: `omni` 532, `tmpl_small` 6,304 | 6,836 | 82 | MIT (ours) |
| `ours/selfcue_v3/` | generated: `tmpl_large` (large numerals) | 5,495 | 73 | MIT (ours) |
| `ours/selfcue_v4/` | generated: `omni` with numerals redrawn to 6 and 9 digits, plus a small set | 7,966 | de en es fr ja zh | MIT (ours) |
| `ours/selfcue_v5/` | generated BIG-bench-style one-step arithmetic, 1-16 digits | 47,237 | de en es fr ja zh | MIT (ours) |
| `ours/selfcue_v24/` | numeral-only copies (6 / 9 / 12 digits) of v1 / v2 rows; `thinking_subset` true on 3,683 | 6,389 | 82 | MIT (ours) |
| `ours/bigbench_arith/` | the BIG-bench `arithmetic` questions, 1-5 digits | 10,516 | en | Apache-2.0 |
| `ours/bbx/` | BIG-bench-form questions with 6-20 digit operands | 5,040 | en | MIT (ours; sentence form from BIG-bench, Apache-2.0) |
| `ours/wildbig/` | Ape210K / Math23K problems with numerals redrawn to 6 / 9 / 12 digits | 1,096 | zh | as Ape210K / Math23K |

Each source folder has its own `LICENSE.md` with the license name, the URL it was read from and the attribution.
**License note (2026-10-20).** Ape210K, Math23K and MAWPS carry no clear data license. They are here because this is a
private repository of the owner's and these rows are kept for the owner's private use; clear them (or delete the
folders) before the repo or its data is made public. The ASDiv rows are non-commercial only (CC BY-NC 4.0).

## Columns and manifests

Wild rows have the same columns as `data/wild/` (`row_id`, `fold`, `text` ending at " The answer is", `annotation`,
`numerals_written`, `prov`, `gold_frac`, `status`, `source_set`, `source_split`, `source_row_id`, `question`, `lang`, `pool`,
and the set's own fields), plus `family`. The project's older bookkeeping columns, host outcomes, and the near-duplicate
link are not shipped (as for `data/wild/`). Generated rows are converted by `data_gen/selfcue_to_defuse.py` from the
project's two-file form (rows file + gold file) and have the same def-use columns plus `family`, `tid`, `src`,
`steps`, `width` and (v24) `think_source` (true on the 3,683 rows of the thinking subset; the manifest calls it `thinking_subset`); `annotation.kind` is `ape210k` (the parser's infix `x=...` form).
`pool.gold_status` is the package's own parser run on the row (`defuse.reader_a.gold_tree`); `pool.n_runs` is the digit
run count of the question.

* `<kind>/<set>/MANIFEST.jsonl`: one line per shipped row (`row_id`, `file`, `fold`, `family`, `split` = "train",
  `gold_status`, `lang`, `n_runs`). `MORE.md5` lists the md5 of all 40 files (data and manifests).
* `python -m defuse.more --out runs/more/rows.jsonl [--sets mathqa asdiv ...]` checks the md5s and writes one rows file;
  it stops on any row that is not listed as `train` in the manifest, or whose file or fold disagrees with it.
* `python -m pytest -q tests/test_more_data.py` checks md5s, sizes, ids, the train-only rule and the gold parses.

## Things to know before you fit

* **At most 5 digit runs.** The dump keeps rows with up to 5 digit runs (R = 5). Rows with more are in the generated
  sets: v24 has 542 of 6,389, v4 2,306 of 7,966 and v5 15,210 of 47,237 (`n_runs` in the manifest). Filter on `n_runs <= 5`
  if you want the dumper to keep every row. Wild rows are all at most 5.
* **Gold parses.** `gold_status` is `exec_exact` for most rows. Rows whose program uses a constant outside the
  reader's 20-value vocabulary (`not_representable:const_outside_vocab`) or an operator outside its grammar (Ape210K
  powers, some MathQA operators) are shipped as they are: v5 has 22,884 of 47,237 const-outside-vocab rows, Ape210K 13,185 const and 3,369 pow rows of 95,808. Filter on `gold_status` to fit only
  what the reader can express.
* **Comma numerals.** Generated rows may write `241,288,100`; `numerals_written` keeps the written form and
  `prov.run_values` the three digit groups, as in `data/wild/` (the gold parser aligns them).
* **Rows the older system had set aside.** The project's older fold system put 1,502 Ape210K and 173 Math23K rows in
  its fold 6 (linked to evaluation rows) and flagged about 800 rows in all with a near-duplicate link to an evaluation
  row. The in-force split rules no longer use those links (only lineage and exact 10-gram overlap), so these rows are
  `train` and are here. The flags are not shipped, so you cannot filter on them; if you want the older, stricter cut,
  say so before relying on this folder.
* **The shipped `data/wild/` rows were cut by the older system.** Counted against the in-force manifests, 741 of the
  1,101 shipped ASDiv rows are train; 136 are now val, 163 test and 61 dropped. Of the 6,396 shipped MathQA rows 6,370
  are train and 26 dropped. This folder does not repeat them and does not remove them.
