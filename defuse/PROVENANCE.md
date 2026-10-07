# defuse/ -- where every function came from

This package is a PORT of the project's pinned def-use code, not a rewrite. Each ported module is assembled from
line ranges of a pinned source file (the md5 of the whole source file and of the copied segment are below), plus a
short list of textual patches, each with its reason. Everything else is marked NEW. The only edits are: the
cluster path guard is swapped for `guard.py` (same function names, fold 5 / fold 6 still refused), cluster paths
and cluster-only bookkeeping are removed, and the project's cluster-bound selftests are replaced by
`tests/test_defuse_cpu.py` (synthetic fixtures only).

## Ported segments

| module | source file | source md5 | lines | segment md5 |
|---|---|---|---|---|
| `reader_a.py` | `defuse_reader.py` | `d2eb8b33672d3cb03c7f16c5dfede819` | 45-731 | `3792c20c36a00e5f366b918a00c82ca0` |
| `reader_a.py` | `defuse_reader.py` | `d2eb8b33672d3cb03c7f16c5dfede819` | 732-1063 | `1ac498fbe5a498f81ad2d5c924925524` |
| `reader_a.py` | `defuse_reader.py` | `d2eb8b33672d3cb03c7f16c5dfede819` | 1149-1186 | `eb2bf9e67b4434782a429dd2e43e8190` |
| `reader_b.py` | `defuse_reader_b.py` | `ececa84a8f107191f573d50c94cc398f` | 27-338 | `b967d7cfb68478329d80e1aa0d1b5ab8` |
| `reader_b.py` | `defuse_reader_b.py` | `ececa84a8f107191f573d50c94cc398f` | 340-358 | `d7714cf14be61c86df8562c03af072fb` |
| `inventory.py` | `defuse_inventory.py` | `a0a2b821ac27e04b242f6b041e300d53` | 24-26 | `14da75c371a8c359ed48eda7d822398f` |
| `inventory.py` | `defuse_inventory.py` | `a0a2b821ac27e04b242f6b041e300d53` | 35-507 | `aeee772118c8b4479aeb4481ac5ac636` |
| `gate.py` | `br_common.py` | `6dcfc2da80d12165de1ecf1e1c2052fe` | 16-19 | `2d47574a3c3a212ef9f4e8b77bc119c4` |
| `gate.py` | `br_common.py` | `6dcfc2da80d12165de1ecf1e1c2052fe` | 43-82 | `131e7a6dc1a9a9a96fb28d6b25cc5d6e` |
| `gate.py` | `task4_rules2.py` | `a9102b7a478d370deea497583dc6e1c5` | 20-20 | `3875586527027cb7c63999588f00f81f` |
| `gate.py` | `task4_rules2.py` | `a9102b7a478d370deea497583dc6e1c5` | 26-26 | `6bcbd133c31529c9078c6cc98ce2c536` |
| `gate.py` | `task3_rules.py` | `2bb53325be67b396ac1c93efcda67857` | 66-71 | `5b237afbbf99d19f67bc1f6569878965` |
| `gate.py` | `task4_rules2.py` | `a9102b7a478d370deea497583dc6e1c5` | 33-77 | `117b899f3c325f7536545a60ed817d2e` |
| `gate.py` | `bgate_rules.py` | `cbb27ff3b2e3852bc9e559117ca97255` | 67-86 | `195acb40974d6f74ccc63c09c900bf9a` |
| `gate.py` | `bgate_rules.py` | `cbb27ff3b2e3852bc9e559117ca97255` | 104-113 | `f14b088706a7df71610b16e3a0ddc559` |
| `gate.py` | `firing_probe.py` | `26f014098895427fb6e827f39beed0f0` | 28-30 | `14307f9b7577c1345d63345eabe9835c` |
| `gate.py` | `firing_probe.py` | `26f014098895427fb6e827f39beed0f0` | 37-53 | `f2c8461d05e6fc467404bbed41fd5aa0` |
| `gate.py` | `firing_probe.py` | `26f014098895427fb6e827f39beed0f0` | 98-156 | `83777c5199c436fd0fcc68b8c836a093` |
| `fit_b.py` | `defuse_fit.py` | `80e86a7537404ae1420c25b58b652997` | 76-79 | `334b10a5ad7467c6c821f84efbeca828` |
| `fit_b.py` | `defuse_fit.py` | `80e86a7537404ae1420c25b58b652997` | 556-610 | `55e33911f2db8d7ae5962c9d171524ed` |
| `dump.py` | `hsig_operandstate_v2b.py` | `6a583426e23e8cb08cf2ef8184061dda` | 1-271 | `5ffed9d940f0a911176e6df0f7b6b83a` |

## Patches (each applied to exactly one place)

| module | what and why |
|---|---|
| `reader_a.py` | the cluster fit guard is replaced by defuse/guard.py (same md5f / check_path / check_row_id names) |
| `reader_a.py` | drop PINS and HOST_LABEL (cluster bookkeeping, unused by the ported functions) |
| `reader_a.py` | load_pinned: no cluster path search; returns defuse/inventory.py |
| `reader_b.py` | import reader A from the package |
| `gate.py` | rename task3_rules.prep -> prep_a (reader A rows) |
| `gate.py` | rename task4_rules2.prep -> prep_m1; it calls prep_a |
| `gate.py` | rename bgate_rules.prep -> prep_b (reader B rows) |
| `gate.py` | rename bgate_rules.feats -> feats_b; T4.feats -> feats |
| `gate.py` | cross_scores: T4.fit_logit / T4.score_logit -> local |
| `gate.py` | rename firing_probe.auroc -> auroc_mw (br_common.auroc keeps its name) |
| `gate.py` | fit_arm: its two auroc(...) calls -> auroc_mw(...) |
| `fit_b.py` | run_fitb: data from rows_by_fold(folds) (in memory) instead of the cluster cache; default grid F2_GRID |
| `fit_b.py` | run_fitb: the final refit data from rows_by_fold |
| `fit_b.py` | run_fitb also returns the fitted model |
| `dump.py` | --hr (a cluster path to the locator module) -> --locator single|grouped |
| `dump.py` | the locator comes from this module, not from a cluster path |
| `dump.py` | print the locator name |
| `dump.py` | add digit_runs_single (pinned locator) and digit_runs_grouped (NEW) before main() |
| `dump.py` | torch / transformers imported inside main() so the locators import without them (CPU tests) |
| `dump.py` | the moved imports |

Two more source facts:

* `dump.py`'s `digit_runs_single` is the project's pinned locator `block.digit_runs` (block.py md5
  `aed2e8163bc97ab2db7e077036e87187`), logic verbatim; its long comment was shortened.
* The constants inside the ported code are the project's: the 20-value constant vocabulary (the fit pool's top 20
  constants), layer labels 20 / 24 / 28, beam 8 for reader B, the F2 grid, tau 1.00% (8B) / 0.75% (other sizes).

## NEW code (written for this package; it adds no modelling)

| file | what |
|---|---|
| `guard.py` | fold discipline in the ported readers' shape: refuses fold 5 / 6 rows, blocklisted ids, evaluation file names; `scoring_pass()` for the one held-out pass |
| `data.py` | row loader with the fold refusal, dump loader, `relabel_layers`, dump-order join |
| `gate.py` `fit_gate` / `apply_gate` | the body of readerB `bgate_rules.fit` (md5 `cbb27ff3`) as one function over rows; the frozen cut applied to new rows |
| `fit_b.py` `b_data` / `make_rows_by_fold` / `decode_record` / `_cap` | in-memory versions of `defuse_fit.b_rows` (same predicates) and of readerB `bgate.py`'s decode record (md5 `81a72db4`) |
| `dump.py` `digit_runs_grouped`, `--locator` | the multi-digit-token locator for Llama-style tokenizers (default off) |
| `run.py` | the pipeline as commands; `host_fields` (host answer from the dump's greedy text) is simpler than the project's wild scorer |
| `bank_rows.py` | adapter from a bank row (`data/banks/`) to the def-use row fields; folds from a named bank fold column |
| `evaluate.py` | value-right / host-right / system-right by gold steps, and the R1 ledger table |

## Reader A's decoder (ported 2026-10-07)

Lines 732-1063 of the pinned `defuse_reader.py` (`decode`, `_depth_score`, `a_identifiable`, `oracle_P`,
`search_programs`, `answer_targets`, `host_program_line`, `head_accuracy_by_position`) are copied unchanged, between
`BEAM = 64` and the DU-AG block, in the pinned file's order. They call only functions already ported from lines 45-731.
`tests/test_reader_a_decode.py` compares the port with outputs RECORDED from the pinned file itself
(`tests/fixtures/reader_a_decode.json`, `reader_a_states.npz`; synthetic rows from the pinned `_syn_rows` /
`_syn_states`, seed 20261007): oracle heads (beam 64 and 256, 239/239 A-identifiable programs recovered), the same heads
with noise (beam 64 / 8, P(used) threshold 0.3), flat heads (negative control), the answer-only search, the
host-program line, and reader A fitted end to end on planted states. When the fixture was written, the pinned file and
the port agreed on all 1,350 comparisons.

## Pending (not ported)

* The project's streaming fit driver for reader A (sufficient statistics over a large cache, per-source weights)
  is not ported; `reader_a.fit_reader` (the in-memory fit in the same pinned file) is. run.py wires reader B + its
  gate only; reader A's heads and decoder are callable from Python (see tests/test_reader_a_decode.py for the calls).
* The BW guardrail (lines 1066-1147) needs two cluster-only pinned modules and is not ported.
* The A-text twin and the answer-only arm are not wired into `run.py`.
