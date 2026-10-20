# Project-generated rows: license

The rows in `selfcue_v1`, `selfcue_v2`, `selfcue_v3`, `selfcue_v4`, `selfcue_v5` (version tags of the project's
generated problem sets) and `selfcue_v24` were written or generated for this project and are **MIT**, like the repo
(`LICENSE` at the root). How they were made:

* `omni` rows (in v1, v2, v4): word problems written by language models for this project, in many languages, from
  the project's story banks; these are the project's own rows.
* `tmpl_small` / `tmpl_large` rows (v1, v2, v3) and the `twin` rows of v1: filled from the project's own templates.
* v4: the `omni` problems with their numerals redrawn to larger sizes (6 and 9 digits) and a small-size set.
* v5: generated BIG-bench-style one-step arithmetic questions in six languages (de en es fr ja zh) from the project's
  own sentence templates; 1 to 16 digits.
* v24: copies of v1 / v2 `omni` and `tmpl_small` rows with only the numerals redrawn to 6, 9 or 12 digits (wording
  kept); `thinking_subset` marks the 3,683 rows whose source row was also recorded with a thinking model.
Rows the generators could not give a numeric gold (the v1 abstain problems, 531 train rows) are not here.

Provenance is taken from the project's build notes (BUILD.json of each set); the problems were not re-audited against
public datasets for this page. `ours/wildbig`, `ours/bigbench_arith` and `ours/bbx` are different: they have their own
license files.
