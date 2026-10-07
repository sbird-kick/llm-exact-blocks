# data/wild: real word problems with gold equations (folds 1-4 only)

These are the def-use pool's rows from two public datasets whose license and train / test status are clear. They are
**training rows**: everything here is in folds 1-4, the folds every fit, setting and gate cut is chosen on. Nothing here
is an evaluation set, a held-out fold, a hidden-state dump or a host's answer.

| set | license | file | rows | md5 |
|---|---|---|---|---|
| ASDiv | CC BY-NC 4.0 (non-commercial, attribution; see `asdiv/LICENSE.md`) | `asdiv/fold1.jsonl` | 270 | `8228b274cec34971bf62ec265c13e3bc` |
| | | `asdiv/fold2.jsonl` | 227 | `eac3b1e44a382bdc8a62e54130c8a06b` |
| | | `asdiv/fold3.jsonl` | 310 | `637d44d505ea2705f96317af7b76a696` |
| | | `asdiv/fold4.jsonl` | 294 | `636acd0bdd77976e390e1bd84701f37f` |
| MathQA (train split only) | Apache-2.0 (see `mathqa/LICENSE.md`) | `mathqa/fold1.jsonl` | 1,572 | `55aec6420e21d787d4dab556409958e1` |
| | | `mathqa/fold2.jsonl` | 1,711 | `6922c067d4c12e80b5d265ac79d89f2d` |
| | | `mathqa/fold3.jsonl` | 1,485 | `14a339380239d6f7cba75cbaffd7fd28` |
| | | `mathqa/fold4.jsonl` | 1,628 | `9fe56a6669a3b4f036db0ea50e6c3a75` |
| all | | 8 files | **7,497** (ASDiv 1,101, MathQA 6,396) | `WILD.md5` |

`MANIFEST.jsonl` (md5 `53c2227cbf6fd952ea556cbf25f6bef6`) lists every shipped row once: `row_id`, `set`, `fold`, `file`,
and the project's pool labels (`gold_status`, `inv_status`, `decodable`, `a_ident`, `n_bin`). Every one of these rows may
be used for fitting, choosing settings and fitting the gate; that is all they are for.
`python -m pytest -q tests/test_wild_data.py` checks the md5s, the folds and the columns.

## How the rows were chosen (from the project's pool of 154,553 rows over 19 source files)

1. Only rows in the def-use pool (the pool keeps rows whose numbers the reader can see: at most 5 digit runs, a status
   of `scored`; 501 ASDiv and 6,732 MathQA rows of the source files are not in it).
2. Only folds 1-4. Folds were assigned in the project by connected components over a numbers-masked template key and
   near-duplicate links, so no paraphrase sits in two folds. Fold 5 (the held-out fold: 285 ASDiv, 2,007 MathQA rows)
   and fold 6 (official test splits) are **not here and never will be**.
3. MathQA: only its official **train** split (909 dev and 594 test rows that sit in folds 1-4 of the pool are left out).
   ASDiv has no official test split.
4. Rows that the project linked as near-duplicates of an evaluation-set row are left out (76 ASDiv rows; 0 MathQA).

## Columns

Each row has the fields `defuse/` reads (`row_id`, `fold`, `text` (the prompt, ending at the cue " The answer is"),
`annotation` (the gold equation: `asdiv Formula` or `mathqa linear_formula`), `numerals_written`, `prov`, `gold_frac`,
`status`), the source fields (`source_set`, `source_split`, `source_row_id`, `question`, `lang`, the set's own
category fields), and `pool` (the project's labels above).

`prov.run_values` / `prov.n_runs` are the digit runs the project's locator found under the **Qwen3 tokenizer** (one
digit per token). The dumper skips (and counts) any row whose run count differs on your tokenizer; on Qwen3 it should
be 0 skips.

**Not included, on purpose:** any host's answers or host-outcome labels (host right / host silent / the host's number):
you make your own with `--greedy 12` when you dump, on your own hardware. Also dropped: the near-duplicate links (they
name evaluation rows), the project's bookkeeping flags (`never_fit`, `test_only`, `dump_bank_eligible`, `surface`,
`cut`, `ds`, `list_values`, `echo_gold*`), a token count under the project's tokenizer (`n_prompt_tokens`), a raw-text
copy (`text_raw`), and a few derived duplicates (`gold_float`, `gold_digits`, `n_number_words`, `source`, `asdiv_a`).

## Using them

```python
from defuse import data as D
rows = D.load_rows("data/wild/mathqa/fold1.jsonl", fit=True)   # refuses any fold-5 / fold-6 row
```

To dump or fit on all of them at once, concatenate the eight files into one rows file (RUN_ON_THOR.md, step 4).
