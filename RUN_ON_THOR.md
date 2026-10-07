# RUN_ON_THOR: the def-use reader at Qwen3-1.7B on the Thor, end to end

This is the whole pipeline on your own: dump the host's hidden states, fit the readers and the gate on folds 1-4 of
the shipped wild rows, score them beside the project's own numbers on the same rows, and run the live demo with your
fits. Only step 5 (the dump) and step 9 (the demo) use the GPU. Everything below runs from the repository root.

Our smoke ran on 2026-10-07 while another user's 8B job held most of the GPU (GPU utilisation 96% mean over the job,
all users together), so its times are on a busy GPU; the full-run figures are ESTIMATES scaled from it, not measurements.

| step | what | where | measured in our smoke (200 rows) | full run (7,497 rows) |
|---|---|---|---|---|
| 1 | environment | login shell | - | once |
| 2 | weights (3.4 GB) | login shell | - | once |
| 3 | smoke: the whole recipe on 200 rows | one GPU job | 2 min 08 s wall; peak RSS 4.1 GB (loading the model); the job file asks `--mem 6G` (ours ran with 16G) | - |
| 4 | the rows file | login shell (seconds) | - | 7,497 rows |
| 5 | dump | one GPU job | 40 s (forward 10 s, greedy 19 s); peak RSS 4.1 GB | about 20 min, about 5.3 GB (estimate: 1.2 GB more tensors); `--mem 8G` |
| 6 | fit reader B, out-of-fold decodes, gate, tables | one CPU job | fit-b 5 s + lofo-b 9 s (smoke grid); peak RSS 0.6 GB | about 2-3 h with the full grid, about 6.5 GB (estimate); `--mem 10G` |
| 7 | read your numbers beside the reference | - | - | - |
| 8 | parity check of the live path | inside the smoke, or one GPU job | 43 s for 40 rows; peak RSS 4.1 GB | - |
| 9 | the demo | one GPU job, as long as you use it | model load 10-12 s; 0.7-1.7 s per prompt; RSS 0.9-1.8 GB after loading, 4.1 GB peak while loading; `--mem 6G` | - |

## The Thor's rules (it is a shared machine)

* **Everything that computes goes through SLURM** (`sbatch`, or `srun` for a short interactive command). The login
  shell is for editing, `git`, downloads and `sbatch`.
* **GPU jobs ask for the GPU explicitly** (`--gres=shard:1`, a share of the one GPU) and **every GPU job samples GPU
  utilisation** with `nvidia-smi` into `logs/gpu-<job>.csv` (the `sbatch/thor_*.sbatch` files do both through
  `sbatch/thor_common.sh`). CPU-only jobs ask for no GPU.
* **`export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` in every job** (thor_common.sh sets it, again after the
  venv is activated).
* **`--mem` is tight and measured.** The Thor's 122 GB is ONE pool shared by the CPU, the GPU and every user. Each job
  file asks for its measured peak plus a margin (the table above); after your own run, check
  `sacct -j <jobid> --format=JobID,Elapsed,MaxRSS,State` and keep `--mem` about 25% above MaxRSS.
* **Large dumps are sharded**: one rows file per job. The 7,497 wild rows are one job (about 1.2 GB of tensors); if you
  add bank rows, give each bank its own rows file and job.
* **Never reboot the board to free memory.** The "used" memory that `free` shows on the Thor includes the unified pool's
  caches; a reboot kills other people's jobs and frees nothing that matters. If a job cannot get memory, wait or ask.
* **Never touch other people's jobs or files.** `squeue` shows everyone's; `scancel` only your own job ids.
* **Folds 1-4 only.** Every row you have is in folds 1-4. Fold 5 (the project's held-out fold), fold 6 (official test
  splits), the fresh held-out set and the evaluation sets (GSM8K test family, MGSM, AfriMGSM, SVAMP) are not in this
  repository, and nothing here reads them; the loaders refuse a fold-5 / fold-6 row.

## 1. Environment (once)

```bash
git clone <the repository> && cd llm-exact-blocks && git checkout defuse-v1
python3 -m venv ~/defuse-venv && source ~/defuse-venv/bin/activate
# torch: install the CUDA build for the Thor (aarch64) from NVIDIA's JetPack instructions for your JetPack version;
# a plain `pip install torch` from PyPI may give you a CPU-only build. Then:
pip install "transformers>=4.56" numpy pytest       # the dumper passes dtype= to from_pretrained
python -c "import torch, transformers; print(torch.__version__, transformers.__version__, torch.cuda.is_available())"
srun --partition=main --cpus-per-task=2 --mem=4G python -m pytest -q tests/test_defuse_cpu.py tests/test_reader_a_decode.py \
    tests/test_wild_data.py tests/test_reference.py tests/test_live_demo.py tests/test_thor_recipe.py
```

The last line should print `True` for CUDA, and the tests should all pass (about a minute). If your venv lives
elsewhere, pass it to every job: `sbatch --export=ALL,VENV=/path/to/venv ...`.

## 2. Weights (once)

```bash
export HF_HOME=~/hf_cache                      # thor_common.sh uses $HOME/hf_cache unless you pass HF_HOME
hf download Qwen/Qwen3-1.7B                    # older huggingface_hub: huggingface-cli download Qwen/Qwen3-1.7B
```

Qwen3-1.7B is open (Apache-2.0, no license form). The jobs run with `HF_HUB_OFFLINE=1`, so the weights must be in
`$HF_HOME` before you submit.

## 3. Smoke test: the whole recipe on 200 rows (one small job)

```bash
mkdir -p logs && sbatch sbatch/thor_smoke.sbatch
```

It builds a 200-row rows file (the first 25 rows of each of the 8 wild files), dumps it, fits reader B with a
one-setting grid (`fit-b --smoke`: a plumbing test, never a fit to report), runs the out-of-fold decodes, tries the gate
(on 200 rows it may refuse: too few fires to cross-fit; the demo then runs ungated), prints the tables beside the
reference, checks the live path against the dump (step 8), and starts the demo once (a self-test, then the server,
two requests, stop). Read `logs/defuse-smoke-<jobid>.out`:

* `kept 200/200 rows ... skips {'run_count_mismatch': 0, ...}`: Qwen3's tokenizer finds the same digit runs as the
  project's (it is the same tokenizer). Any skip here means something is wrong with the rows or the tokenizer.
* `STEP ... rc 0, wall ..., peak RSS ...` for every step, and a `GPU util:` line at the end.
* `live vs dump on 40 rows: ...` (step 8) and a `DEMO predict:` line.

## 4. The rows file

```bash
python -m defuse.wild --out runs/q17/rows.jsonl
```

This checks every shipped file against `data/wild/WILD.md5` and writes the 7,497 rows (ASDiv 1,101, MathQA train
6,396; folds 1-4) into one file. `runs/` is ignored by git.

## 5. Dump (GPU)

```bash
sbatch sbatch/thor_dump.sbatch runs/q17/rows.jsonl runs/q17
```

`python -m defuse.dump` with `--host Qwen/Qwen3-1.7B --layers 16,19,22 --max-runs 5 --greedy 12 --locator single`:
for each row, the hidden state at the last token of each digit run and at the answer position (after the cue and one
added space), the attention mass from the answer position onto each run, and the host's own 12-token greedy answer
(your host-right / host-silent labels come from it). Layers 16 / 19 / 22 of 28 are the project's 1.7B layers; they are
relabelled 20 / 24 / 28 in the next step. Output: `runs/q17/q17_wild_operandstate.pt`. The log should say
`kept 7497/7497` with every skip at 0, and `host greedy right <n>/7497`.

## 6. Fit and score (CPU)

```bash
sbatch sbatch/thor_fit.sbatch runs/q17
```

In order (`defuse/run.py`; each step is skipped on a re-run if its output exists):

1. `fit-b`: reader B per layer label: the F2 grid (l2 x lr x epochs) fitted on folds 1-3, the setting chosen by exact
   programs on fold 4, then refitted on folds 1-4 -> `runs/q17/fitB/READERB_L{20,24,28}.{npz,json}`.
2. `lofo-b`: for each fold k in 1-4, reader B refitted (chosen setting) on the other three folds and used to decode fold
   k -> `runs/q17/lofo/OOF.jsonl`, one out-of-fold record per row (the program at each layer, DU-AG's decision, the
   host's answer, right / wrong).
3. `fit-gate --tau 0.0075`: the gate (10 features: reader B's beam score per leaf, its minimum over layers, steps and
   numeral-count one-hots, interactions; no host-outcome probes) cross-fitted over folds 1-4, its cut calibrated so that
   broken <= floor(0.75% x host-right) on these out-of-fold records -> `runs/q17/gate.json`.
4. `evaluate --reference`: the tables -> `runs/q17/RESULTS.md`.

## 7. Read your numbers beside the reference

`RESULTS.md` has three tables: value-right by gold steps, the R1 ledger (ungated DU-AG and gated), and your headline
numbers beside the project's on the same rows (`data/wild/reference/qwen3-1.7b_h100.json`). The reference, on all
7,497 rows:

| quantity | reference (Qwen3-1.7B, H100 dumps, the project's run) |
|---|---|
| host right | 1576/7497 |
| reader value-right (L24 program, ungated) | 1243/7497 |
| DU-AG ungated: fires / broken / fixed | 335/7497, 34/1576, 211/5921 (R1 NEITHER, bar 15) |
| DU-AG + no-probe gate (the recipe of step 6, on the reference decodes): fires / broken / fixed / system right | 111/7497, 4/1576, 98/5921, 1670/7497 (R1 SUCCESS, bar 15) |
| context: the project's frozen 1.7B gate (with host-outcome probes) | fires 127, broken 4, fixed 113 |

What should and should not match, and why:

* **Host right** should be close but not equal. Two reasons, both labelled in the table: the reference dumps ran on an
  H100, and the same bf16 weights take a slightly different arithmetic path on the Thor (expect a few percent of rows to
  flip); and the reference host answer is the first number of a natural-form decode (no added space, up to 64 tokens),
  while yours is the first number of the dump's 12-token greedy text after the added space.
* **Reader value-right** should be LOWER than the reference. The reference readers were fitted (leave one fold out) on
  the project's full pool, about 98,600 training programs per layer from five sources; yours see 7,497 rows from the two
  sources whose licenses let us ship them. How much lower is itself a result: it measures what the other sources bought.
* **The R1 word of your gate on folds 1-4** says little: the cut is calibrated on these very records, so broken <= the
  budget there by construction. Treat the gated line as "the gate works mechanically"; a held-out claim needs rows that
  played no part in any choice. The project's fold 5 is not shipped; with this repository the only such rows are bank
  rows from a template fold you hold out before fitting (DATA.md, "What you may fit on").
* Quote every number as n/total, with the host and the hardware ("Qwen3-1.7B, Thor").

## 8. The live path's parity with the dump (GPU; the smoke runs it)

```bash
python -m defuse.live check --host Qwen/Qwen3-1.7B --dump runs/q17/q17_wild_operandstate.pt --rows runs/q17/rows.jsonl \
    --layers 16,19,22 --relabel 16:20,19:24,22:28 --fit runs/q17/fitB --gate runs/q17/gate.json --n 40
```

(inside a GPU job: `srun --partition=main --gres=shard:1 --mem=8G ...`). It runs the demo's live path on the first 40
dumped rows and compares: the digit runs, the greedy text, the features (max |difference| from the dump's tensors), the
three layers' programs, DU-AG's decision and the final decision. The live path runs one prompt at a time and the dump
ran batches of 8 (right-padded forward, left-padded greedy decode), so bf16 differences and a few flipped near-ties are
expected; the programs and decisions should agree on nearly every row. The max |difference| it prints is absolute and
dominated by a few very large hidden-state coordinates that Qwen3 carries at every position, so judge the check by the
programs and decisions (our smoke: 40 rows: digit runs 40/40, greedy text 32/40, programs at all three layers 35/40, DU-AG fire 39/40, final decision 40/40).

## 9. The demo with your readers (GPU)

```bash
cp demo/config.example.json demo/config.json      # paths to runs/q17/fitB and runs/q17/gate.json; pick a free port
ss -ltn | grep -c ":8765 " || true                # 0 = the port is free (two people cannot share one port)
sbatch sbatch/thor_demo.sbatch demo/config.json
tail -f logs/defuse-demo-<jobid>.out              # wait for "serving on http://127.0.0.1:<port>/"
```

On your laptop: `ssh -N -L <port>:127.0.0.1:<port> <you>@<the Thor's address>`, then open `http://localhost:<port>/`.
The page is the project demo's page cut down to what your fits can fill: the host's next-token distribution and its
answer, the numbers the locator found, and the decision (reader B's program at the three layers, whether they agree,
the host's class, the gate's score against its cut, FIRE or ABSTAIN, and the system's answer). The server binds
127.0.0.1 only and answers one prompt at a time. Stop it with `scancel <jobid>` when you are done: it holds a GPU share
for as long as it runs.

## 10. Clean up

`runs/` is not in git. The dump (`runs/q17/q17_wild_operandstate.pt`, about 1.2 GB) can be remade in one job; delete it
when you no longer need it, since the disk is shared too.
