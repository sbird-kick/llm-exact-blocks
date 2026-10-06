# MIGRATION: from `exact_block/` (read / route / write) to `defuse/` (read the program, execute, gate)

`exact_block/` stays in the repo as legacy: its code, tests, corpus generator and numbers are unchanged, and it is
still the clearest small example of reading a frozen model's state. New work goes in `defuse/`. This page maps the
old pieces onto the new ones, says what has no counterpart, and gives the order in which to move a project over.

## The idea, side by side

| | `exact_block/` (legacy) | `defuse/` (current) |
|---|---|---|
| question answered | which two numbers, and add / sub / mul / off? | which written numbers and hidden constants combine, with which operators, in which order, through which intermediate steps? |
| what is read | digit identity (probe at layer 8), operand roles (span tagger at 8), the operation (router at 16) | per written number: USED, PARENT operator, SIDE, DEPTH, SIBLING pairs; per row: STEPS, ROOT operator, hidden CONSTANTS. Read at three layers (labels 20 / 24 / 28 of a 36-layer host) |
| where it is read | every token (tagger), a pooled prompt (router) | the last token of each digit run and the answer position after the cue (`dump.py`) |
| how the answer is formed | exact column arithmetic, then WRITTEN back into the residual stream at layer 24 | the program is EXECUTED exactly in fractions outside the model; nothing is written into the stream |
| when it acts | the router's `off` class and two arithmetic refusals | DU-AG (three layers agree, the host's answer is an echo or another number, never when the host is silent) and then the gate, calibrated so that broken <= 1% of host-right (R1) |
| problems it covers | one step, two operands | up to 6 binary steps, up to 5 written numbers per row (the dump's R = 5), +, -, x, / and percent, 20 constants |
| training signal | four supervised losses through the frozen LM head | ridge heads (reader A) or a small tree decoder (reader B) on gold programs; the gate on out-of-fold decodes |
| evaluation | answer accuracy per width cell, teacher-forced and greedy | value-right by gold steps, and the R1 ledger (fires, broken / host-right, fixed / host-wrong, system right), always n/total, per host |

## File by file

| legacy | current | notes |
|---|---|---|
| `exact_block/numerals.py` `digit_runs` | `defuse/dump.py` `digit_runs_single` | the project's locator uses `str.isdecimal()` on a one-character token (so native decimal digits count, a superscript does not); the legacy file uses ASCII digits only. For multi-digit tokenizers use `--locator grouped` |
| `exact_block/calc.py` | `defuse/reader_a.py` `execute` | exact `Fraction` execution of a program tree; division by zero gives `None` (no answer) |
| `exact_block/block.py` (probe, tagger, router, write head, gate) | `defuse/reader_a.py` heads, `defuse/reader_b.py`, `defuse/gate.py` | no write head and no hooks: the dump is a plain forward pass with `output_hidden_states` / `output_attentions` |
| `exact_block/data.py` (templated English corpus) | rows with `row_id`, `text` (ending at the cue), a gold equation (`annotation.kind` / `annotation.equation`), `numerals_written`, `prov.run_values` / `prov.n_runs` / `prov.gold_run_idx`, `gold_frac`, `status: "scored"`, a `fold` | `defuse/inventory.py` parses the equation; the banks in `banks/` and `data/` give multilingual rows; see DATA.md |
| `train.py` | `python -m defuse.run fit-b` (reader B), `reader_a.fit_reader` (reader A heads) | folds 1-4 only; fold 4 selects settings, then a refit on 1-4 |
| `eval.py` | `python -m defuse.run decode-b --heldout`, then `python -m defuse.evaluate` | the held-out fold is decoded ONCE with frozen settings |
| (none) | `python -m defuse.run lofo-b`, `fit-gate` | the gate is fitted on leave-one-fold-out decodes of folds 1-4 |
| `tests/test_cpu.py` | `tests/test_defuse_cpu.py` | both CPU-only; the new one needs only numpy and pytest |
| `sbatch/train.sbatch`, `eval.sbatch` | `sbatch/defuse_dump.sbatch` (GPU), `sbatch/defuse_cpu.sbatch` (CPU) | only the dump needs a GPU |

## What has no counterpart, on purpose

* **The write path.** Writing digits back into the stream is gone. The R1 rule needs an explicit "keep the host's
  answer" decision, and a value computed outside the model is easier to audit than a delta added to layer 24.
* **The router's `off` class.** "Is there arithmetic here at all" is now split in two: the host-class step of DU-AG
  (the host agrees, is silent, echoes, or writes another number) and the gate's fixed-versus-broken score.
* **Per-width cells.** Width no longer matters (the values come from the text, exactly); what matters is the number
  of steps, so every table is by gold steps.

## Folds: the one rule that is new and strict

Every def-use row has `fold` in 1..6. Folds 1-4 are for everything you fit or choose: heads, decoder settings, gate
cuts, thresholds, the layer you report. Fold 5 is held out and scored once, with frozen settings, after you have
written down what you will report. Fold 6 marks the source datasets' own official test splits (and rows linked to
them) and is never fitted on either. `defuse.data.load_rows(..., fit=True)`, `fit_b.make_rows_by_fold` and
`gate.fit_gate` all refuse fold 5 / 6 rows. When you build rows of your own, assign folds by connected components
over `inventory.tkey` (numbers masked) and any near-duplicate link, so that no paraphrase sits in two folds.

## Moving a project over, in order

1. Keep your legacy runs; nothing in `exact_block/` changed.
2. Build rows (a bank from `banks/`, or your own) with the fields above and a fold per row.
3. Dump once per host: `sbatch sbatch/defuse_dump.sbatch <model> <tag> <rows> <layers> [grouped]`.
4. Fit reader B on folds 1-4, run the LOFO decodes, fit the gate (`sbatch/defuse_cpu.sbatch fit-b|lofo-b|fit-gate`).
5. Write down tau and what you will report. Then decode fold 5 once and print the tables (`decode-b --heldout`,
   `defuse.evaluate`). Quote n/total and the host and hardware on every line.
