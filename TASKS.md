# TASKS: porting the def-use reader to Llama hosts

The question: **does a frozen Llama hold the same readable program at the cue that a frozen Qwen3 does, and does
the R1-gated system help it as much at matched size?** Everything in `defuse/` is host-agnostic; nothing in it was
fitted on a Qwen row, so the port is a refit, not a transfer. Budget: about two batch GPUs, and the dump is the only
GPU step.

## Stage 0: the package on your machine (CPU, an hour)
- `python -m pytest -q tests/test_defuse_cpu.py` (17 tests, numpy + pytest). Read `defuse/PROVENANCE.md` and
  MIGRATION.md.
- `python -m pytest -q tests/test_reader_a_decode.py` (reader A's decoder against the pinned file's recorded outputs).
  The runnable end-to-end path (`run.py`) is reader B + gate.

## Stage 0b: reproduce the project's 1.7B pipeline on the Thor (one GPU dump, one CPU job, the demo)
- Follow RUN_ON_THOR.md end to end on the shipped wild rows (`data/wild/`, folds 1-4). The scoring step prints the
  project's own Qwen3-1.7B numbers on the same rows beside yours; step 7 there says what should and should not match.
- This is the baseline every Llama line below is compared with: same rows, same folds, same recipe, your hardware.

## Stage 1: tokenizer and layers (CPU, then one small GPU job)
- Llama 3 writes numbers in chunks of up to three digits, so the project's locator (one decimal digit per token)
  finds the wrong runs. Use `--locator grouped`, and check on 200 rows that the dumper's `run_count_mismatch` skip
  counter is 0 or near it (it compares against each row's `prov.n_runs`). Report the skips as n/total.
- Pick three layers at about the relative depths the project used (20 / 24 / 28 of 36 at 8B, 16 / 19 / 22 of 28 at
  1.7B / 0.6B: roughly 0.56, 0.67, 0.78 of the depth) and relabel them to 20 / 24 / 28 when loading
  (`data.relabel_layers`).
- One short smoke job first (`python -m defuse.dump ... --max-rows 200` inside a batch job); size `--time` from it.

## Stage 2: refit on Llama dumps (GPU dump, then CPU)
- Hosts, matched to the project's Qwen sizes where possible: Llama-3.2-1B (vs Qwen3-0.6B / 1.7B),
  Llama-3.2-3B, Llama-3.1-8B (vs Qwen3-8B). Weights must already be in your `HF_HOME` (license accepted).
- Data: a cleared bank from `banks/` / `data/` first (synthetic, in many languages), then wild rows if and when
  they are added (DATA.md).
- Per host: dump (with `--greedy 12` for the host's own answer), `fit-b` on folds 1-4, `lofo-b`, `fit-gate` with the
  project's tau (0.75% at 0.6B / 1.7B / 32B, 1.00% at 8B), then fold 5 ONCE.
- Reader A's heads can be fitted (`reader_a.fit_reader`), their per-head accuracy measured
  (`reader_a.head_accuracy_by_position`) and programs decoded (`reader_a.decode(reader_a.predict_row(...))`).

## Stage 3: compare with Qwen at matched size (CPU)
- On the SAME rows and folds, put the Llama line beside the Qwen line for each table: value-right by gold steps
  (`defuse.evaluate`), host right, and the R1 ledger. Every number n/total; label each line with model and GPU.
  Never pool hosts, and never compare across different row sets.
- If you have only the project's published Qwen numbers (README), say so: they are on the project's wild pools,
  not on your rows, so they are context, not a matched comparison. A matched comparison needs a Qwen dump of your
  rows on your hardware (one more GPU job per size).

## Stage 4: the R1 ledger (CPU)
- For every configuration you report: fires, broken / host-right with the bar floor(1% host-right), fixed /
  host-wrong, net, system right, and the word SUCCESS / NEITHER / FAILURE (`gate.ledger`). Host-silent rows must
  never be fired on (the DU-AG rule guarantees it; check the count is 0).
- Keep a short ledger file per run: host, hardware, rows file md5, dump md5, gate json md5, tau, the fold-5 table,
  and the date. Decide what you will report before the fold-5 pass and do not rerun it.

## Rules that do not change
- Fold 5 and fold 6 are never fitted, calibrated or selected on (the loader refuses them).
- GPU jobs on `--partition=batch`, CPU jobs on `--partition=cpu`, nothing on the login node (README, Cluster rules).
- Quote n/total everywhere, and the host and hardware on every line.
