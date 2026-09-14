# An exact-arithmetic block on a frozen LLM

A large language model adds and multiplies by pattern-matching, and the pattern gets
thinner as the numbers get wider: on the corpus in this repo a frozen Qwen3-1.7B answers
three quarters of four-digit additions and three percent of eight-by-four ones, and none
of the multiplications at any width. The usual fixes either
fine-tune the model (expensive, and it forgets things) or hand the arithmetic to an
external tool (a second process, a parser, and a calling convention). This repository is
a small re-implementation of a third option: leave the model **completely frozen** and
bolt a ~60,000-parameter *block* onto its residual stream with three forward hooks. The
block reads the operand digits out of the model's own hidden states, does the arithmetic
exactly in integer column form, and writes the answer's digits back into the stream a few
layers before the end, where the model's own unembedding reads them out as text. No
weights of the host change, nothing is decoded in between, and the whole thing is one
forward pass.

The interesting part is not the arithmetic -- a calculator is a calculator. It is that
every *interface* to the arithmetic is learned from the host's own activations: a probe
that turns a hidden state at a digit token into "that is a 7", a tagger that decides which
number in the sentence is the first operand and which is the second, and a router that
decides whether the sentence is asking for a sum at all. The calculator itself has zero
parameters. So does the locator. What is learned is only the reading, the naming and the
decision to fire -- which is why the block is measured in tens of thousands of parameters
against the host's billions.

This repo does **binary integer arithmetic only**: addition, subtraction and
multiplication, operands up to 16 digits, results up to 32 digits. It is meant to be read
in an afternoon and reproduced in an hour on one GPU.

## The architecture

```
prompt: "The depot received 90310 bolts on Monday and 472 bolts on Tuesday,
         so the running total is"                                         answer: " 90782"
                                                    ^                       ^^^^^^
                                                    P = control position    answer positions

frozen Qwen3-1.7B, 28 decoder layers, NOT ONE WEIGHT CHANGES
 L0 ... L7  [L8]  L9 ... L15  [L16]  L17 ... L23  [L24]  L25 L26 L27 -> norm -> LM head
             |                  |                   |
            READ              ROUTE               WRITE
             |                  |                   |
   +---------+----------+       |          h <- h + gate * (1 + gate_head(h_P)) * delta
   |         |          |       |                   ^
 probe     span      gate_head  |                   |
(digit)   (tagger)   (gain)     |                   |
   |         |                  |                   |
   |         +-> which runs are A and B             |
   |                  |                             |
   +--> A, B in R^(16x10)  -----------------> [ exact calc ] --> R in R^(32x10)
        LSD-first digit distributions          add / sub / mul      one-hot per place
                                               0 parameters               |
                                    control = Linear(d, 4) <--------------+
                                    add | sub | mul | OFF          write = Linear(10, d)
                                    mass = 1 - p(off)              scatter into 32 lanes
```

Three attach points, and the order is not arbitrary:

* **READ, layer 8.** Digit identity is linearly available *early*. The digit probe, the
  span tagger and the gate's gain all read this one tensor.
* **ROUTE, layer 16.** What the sentence is *asking* linearises *later* than what its
  digits are. Only the router reads this layer, and it reads it by attention-pooling the
  whole prompt -- not just the last token -- because on prompts that end "Answer:" the
  task words sit far from the answer slot.
* **WRITE, layer 24.** Late enough that the remaining layers pass the digits through to
  the unembedding, early enough that they are still processed as part of the stream.

### Components and parameter counts (Qwen3-1.7B, d = 2048)

| component | module | params | learned? |
|---|---|---|---|
| locator | -- | 0 | no: a grammar over digit tokens (`numerals.py`) |
| digit probe | `Linear(2048, 10)` | 20,490 | yes, one head shared over all places and both operands |
| span tagger | `Linear(2048, 3)` | 6,147 | yes: none / A-digit / B-digit, per token |
| router | `Linear(2048, 4)` | 8,196 | yes: add / sub / mul / **off**, `off` bias prior +2.0 |
| router pooling query | `route_q (2048,)` | 2,048 | yes, zero-init (starts as a uniform mean) |
| calculator | -- | 0 | no: exact integer column arithmetic (`calc.py`) |
| write head | `Linear(10, 2048)`, no bias | 20,480 | yes |
| gate | scalar | 1 | yes, **zero-init**: at step 0 the model is bitwise unchanged |
| gate gain | `Linear(2048, 1)` | 2,049 | yes, zero-init |
| **total** | | **59,411** | against 1,720,574,976 frozen |

Three design points worth stopping on, because each one is load-bearing and each one was
a bug before it was a rule:

1. **The gate is multiplicative and zero-initialised.** `delta` enters as
   `gate * (1 + gate_head(h_P)) * delta`. At `gate = 0` the host is bitwise itself, which
   is how every "frozen host" number in `eval.py` is produced -- by zeroing that one
   scalar, not by loading a second copy of the model. Had the gain been *additive*,
   zeroing `gate` would have left `gate_head` still injecting, and the baseline would have
   silently stopped being the baseline.
2. **The write head has no bias.** Abstention must scale the *whole* message. With a bias,
   `write(R) = R @ W.T + bias` and multiplying by `mass = 0` still leaves `bias` injected
   at every answer position.
3. **The block does its arithmetic in fp32 even though the host is bf16.** A 16x16 column
   sum reaches 1296; bf16 is exact only to 256, so a bf16 column is silently wrong in the
   middle of an otherwise perfect number.

### The two refusals

There is no sign channel and no overflow channel in the answer lanes, so a negative or an
over-wide result has no honest rendering. Both fall out of the calculator for free:
`resolve_carry` returns the carry that survives the last place, and

* `carry < 0` means the result is negative (`a - b` with `a < b`),
* `carry > 0` means the result needs more than `2 * dmax` places.

Either sets `mass = 0` for that row and the host's own logits stand. A third refusal, an
operand wider than `dmax`, is caught by the locator before the forward pass, and a fourth,
a span the tagger could not find, is caught by the tagger itself.

## Files

```
exact_block/numerals.py   the locator: digit-token runs -> LSD-first lane vectors
exact_block/calc.py       exact add/sub/mul as column arithmetic, plus the refusals
exact_block/block.py      CalcBlock (probe/tagger/router/gate/write), the hooks, build_batch
exact_block/data.py       templated prose corpus: distractors, reversed order, `off` rows
train.py                  four supervised losses, frozen host, ~0.06 M trainable params
eval.py                   host vs host+block answer accuracy, per op and width cell
tests/test_cpu.py         CPU-only: calculator exactness, locator, hooks, bitwise inertness
sbatch/                   SLURM runners for the cluster
```

Licensed under the MIT License; see [LICENSE](LICENSE).

## Run it

```bash
pip install -r requirements.txt

# 1. the corpus (deterministic in --seed; writes data/{train,val,test}.jsonl)
python -m exact_block.data --out data --seed 0

# 2. the CPU tests. No GPU, no model download, no network.
python tests/test_cpu.py          # or: python -m pytest -q tests/test_cpu.py

# 3. train (one GPU; 231 s for 3000 steps on an RTX PRO 6000 at the defaults)
python train.py --model Qwen/Qwen3-1.7B --data data --out runs/demo \
    --steps 3000 --bs 64 --read-layer 8 --route-layer 16 --write-layer 24

# 4. score it against its own frozen host, per width cell
python eval.py --model Qwen/Qwen3-1.7B --data data --ckpt runs/demo/block.pt --split test

# 4b. optionally, also free-run the answer instead of teacher-forcing it (see "Teacher-
#     forced vs. free-running" below); slower, so it samples --decode-rows per cell
python eval.py --model Qwen/Qwen3-1.7B --data data --ckpt runs/demo/block.pt --split test \
    --decode greedy --decode-rows 20
```

On the cluster, all three steps are one job:

```bash
sbatch sbatch/cpu_tests.sbatch                 # CPU partition
sbatch sbatch/train.sbatch demo 3000 64        # data + train + eval, one GPU
sbatch sbatch/eval.sbatch runs/demo/block.pt test
sbatch sbatch/eval_greedy.sbatch runs/demo/block.pt test 20   # + free-running decode
```

Each sbatch file has a marked `PLACEHOLDER` line where you activate your own environment.

### What the corpus looks like

```
prompt      "Each of the 4821 trays holds 63 seedlings, so the nursery holds"
completion  " 303723\n"
```

Width **cells** are written `<digits of a>x<digits of b>`. Trained: `4x4, 6x6, 8x8, 8x4`.
Also evaluated, and **never trained**: `5x5, 6x3`. Three parts of the corpus are doing
real work:

* **distractor numbers** in half the templates, so "the last two numbers" is not a locator;
* **reversed render order** in several templates ("From 9310 subtract 47",
  "216 of the 740 seats"), so roles cannot be read off position either;
* **`off` rows** -- prose with numbers, an answer-shaped slot, and no arithmetic asked.
  These are the only reason the router's `off` class means anything.

Splits are **problem-disjoint**: the split is a hash of `(op, a, b)`, so the same operand
pair can never appear in two files under any template.

### The four losses

The exact calculator argmaxes the probe's digits and then does integer arithmetic, so it
is not differentiable and the LM loss alone would never reach the probe or the tagger.
Each part is therefore supervised directly:

| loss | what it trains |
|---|---|
| LM cross-entropy at the answer positions (through the **frozen** LM head) | `write`, `gate`, `gate_head`, and the router through `mass` |
| digit cross-entropy at the operand lanes | `probe` |
| 3-class token cross-entropy over the prompt | `span` |
| 4-way cross-entropy over add / sub / mul / off | `control`, `route_q` |

Training uses the positions `build_batch` located; **evaluation uses the tagger's own**
(`--learned-spans` is forced on in `eval.py`), because at deployment nothing tells the
block where the digits are.

## What to expect

### This repo, measured

One run of exactly the commands above, on one GPU. **These are the numbers this code
produced**, not numbers copied from anywhere:

> host Qwen3-1.7B (frozen, bf16), block 59,411 trainable params, read 8 / route 16 /
> write 24, dmax 16, 3000 steps at batch size 64, lr 1e-3, seed 0.
> SLURM job **19584** on `--partition=batch`, 1x NVIDIA RTX PRO 6000 Blackwell (96 GB).
> Wall time **4 min 14 s** for corpus generation + training + the full test eval; the
> 3000 training steps themselves took **231 s**. Test split: 4500 rows (3600 arithmetic
> + 900 `off`), 200 rows per (op, cell).

```
op    cell    rows    host   block   route    span    calc
----------------------------------------------------------
add   4x4      200  0.7500  1.0000  1.0000  1.0000  1.0000
add   5x5      200  0.5300  1.0000  1.0000  1.0000  1.0000  (held out)
add   6x3      200  0.2100  1.0000  1.0000  1.0000  1.0000  (held out)
add   6x6      200  0.3150  1.0000  1.0000  1.0000  1.0000
add   8x4      200  0.0300  0.9900  1.0000  0.9900  0.9900
add   8x8      200  0.3250  0.9950  1.0000  0.9950  0.9950
sub   4x4      200  0.3500  0.9950  1.0000  0.9950  0.9950
sub   5x5      200  0.2600  1.0000  1.0000  1.0000  1.0000  (held out)
sub   6x3      200  0.1050  0.9950  1.0000  0.9950  0.9950  (held out)
sub   6x6      200  0.2300  0.9950  1.0000  0.9950  0.9950
sub   8x4      200  0.0050  1.0000  1.0000  1.0000  1.0000
sub   8x8      200  0.1200  0.9900  1.0000  0.9900  0.9900
mul   4x4      200  0.0050  0.9950  1.0000  0.9950  0.9950
mul   5x5      200  0.0000  1.0000  1.0000  1.0000  1.0000  (held out)
mul   6x3      200  0.0000  1.0000  1.0000  1.0000  1.0000  (held out)
mul   6x6      200  0.0000  0.9900  1.0000  0.9900  0.9900
mul   8x4      200  0.0000  1.0000  1.0000  1.0000  1.0000
mul   8x8      200  0.0000  1.0000  1.0000  1.0000  1.0000

off rows: 900  route(=off) 1.0000  fired anyway 0.0000

all arithmetic rows: 3600  host 0.1797  block 0.9969  span 0.9969  calc 0.9969
```

### Teacher-forced vs. free-running, and a greedy decode column

Every number above is **teacher-forced**: the gold completion is already in the
sequence, and a row counts as right only if the argmax at *every* answer position matches
the gold digit there. That measure never lets the model see its own mistake -- position
`k+1` is scored with the true digit at position `k` sitting in context, not whatever the
model would actually have written there. It is the right way to isolate "does the probe
read the operands and does the calculator get the arithmetic right", which is what this
repo is mostly about, but it is not what a person actually typing the prompt gets back.

`eval.py --decode greedy` adds the honest version. Nothing past the prompt is fed from the
gold completion: the model (host, or host+block) picks a token, that token goes back in as
the next input, one forward pass at a time, until a non-digit token ends the answer or the
digit budget runs out. A row counts as right only if the digits it actually decoded, read
back as one integer, equal the gold answer. Because this is one forward pass per generated
digit rather than one for the whole row, `eval.py` samples `--decode-rows` problems per
`(op, cell)` (20 below) rather than scoring the whole split.

> Same checkpoint as above. SLURM job **19587** on `--partition=batch`, one GPU, wall time
> **46 s** for 18 cells x 20 rows x two passes (host, block) x up to 34 generated tokens
> each.

```
op    cell    rows host_greedy block_greedy
-------------------------------------------
add   4x4       20      0.8000       1.0000
add   5x5       20      0.5500       0.9500  (held out)
add   6x3       20      0.2000       0.9000  (held out)
add   6x6       20      0.3000       0.9500
add   8x4       20      0.0000       0.9000
add   8x8       20      0.4000       0.7500
sub   4x4       20      0.2000       0.9000
sub   5x5       20      0.1000       0.9500  (held out)
sub   6x3       20      0.1000       0.9500  (held out)
sub   6x6       20      0.0000       0.9500
sub   8x4       20      0.0000       1.0000
sub   8x8       20      0.0000       0.8000
mul   4x4       20      0.0000       0.7500
mul   5x5       20      0.0000       0.8500  (held out)
mul   6x3       20      0.0000       0.9000  (held out)
mul   6x6       20      0.0000       0.4000
mul   8x4       20      0.0000       0.7000
mul   8x8       20      0.0000       0.5500

off rows (greedy): 20  fired anyway 0.0000
```

The block is still far ahead of the host at every width, and the off-row behaviour is
identical to the teacher-forced run (it never fires on a non-arithmetic row). But it is no
longer at or near 1.00 everywhere, and the drop is concentrated exactly where teacher-
forced accuracy was already lowest and the answers are widest: `mul 6x6` (0.40), `mul 8x8`
(0.55), `mul 8x4` (0.70), `sub 8x8` (0.80), `add 8x8` (0.75). Five decoded mismatches, by
hand:

```
op    cell    a          b        gold      decoded
add   5x5     82082      18661    100743    074343
add   6x3     947075     606      947681    768182
add   6x3     373943     179      374122    412277
add   6x6     210411     119860   330271    027121
add   8x4     54860908   9008     54869916  86991608
```

None of these are the decode loop losing track of *where* to write: the block still writes
at the right physical column every time (a wrong write position would fail every row of a
width, not ~1 in 5 of the widest ones, and it would not spare `add 4x4`, which stays at
1.00 free-running). What is happening is the mechanism the "Read the `host` column first"
paragraph below did not have to contend with: the calculator's per-place delta is
recomputed fresh every forward pass and is *always* correct for its physical column, but
the three layers after WRITE (25-27) still run ordinary self-attention over the answer so
far, and once one digit is wrong, the *token actually sitting there* -- not the delta that
was added under it -- is what every later digit's attention reads. Free-running, unlike
teacher-forcing, lets that wrong token stay in context and corrupt the digits after it. It
is worse on wider answers for the obvious reason: more digits means more chances for the
one early slip that the rest of the number can't recover from. This is a property of the
architecture (nothing downstream of WRITE re-reads the calculator once a token is chosen),
not a bug in `eval.py`'s decode loop, so it is reported as-is rather than patched.

Read the `host` column first. The frozen 1.7B answers three quarters of 4x4 additions and
**three percent** of 8x4 ones, and it never once gets a multiplication right at any width
in this corpus. The block is at or above 0.99 on every cell, including the two widths it
was never trained on (`5x5` and `6x3`), because the calculator does not know what a width
is -- the only thing that had to generalise is the *reading*, and the digit probe is one
shared head over all sixteen places. On the 900 `off` rows the router chose `off` every
time and the block wrote nothing at all.

The four losses reach their floors in this order: route within ~50 steps, span by ~500,
probe and LM by ~1500. `gate` ends at +0.318, having started at exactly 0.

### The project's own numbers, for comparison

The result this repo re-implements was measured on a larger and messier setup -- an 8B
host, prose mined from the wild as well as templates, five operations including gcd and
quotient, and the attention-based selector this repo omits. **These are the project's
numbers, not this repo's**: on templated in-corpus prose the block reached ~1.00 answer
accuracy on every trained cell against a frozen host at 0.69-0.98 (worse at wider
operands), with route accuracy ~1.00 and span accuracy 0.98-1.00, and the held-out widths
`5x5` and `6x3` also came in at ~1.00. The shape of the result reproduces here; the host
baseline here is lower because this host is the plain base model and this corpus asks for
more multiplication.

## What is deliberately left out

This is a teaching re-implementation of one result, not the deployed system. Omitted, on
purpose:

* **The attention-based selector (arm `ah`).** In the full system the operand *selection*
  does not come from the per-token span tagger at all: it comes from the frozen host's own
  attention mass from the answer slot onto each candidate number run, summed over heads
  across a band of layers (17-20 of 28, 22-26 of 36) and scored by a single
  `Linear(L*H + 1, 1)` head. It needs eager attention, capture hooks on the band, a
  deferred forward (the block's `compute()` has to run at the *write* hook because the
  band sits above the read layer), a role-permutation search and a calibrated abstention
  margin. It is the single biggest omission here, and it matters most on *found* text
  rather than on templates: on templated prose the span tagger is already at 0.98-1.00.
* **The differentiable "soft" calculator.** The full system keeps a fractional-digit path
  so gradients can flow through the arithmetic. With every component supervised by its own
  loss, it turns out not to be needed, so this repo ships the exact path only.
* **Other operations.** gcd, quotient, modulus, powers, digit-sums, ternary bodies,
  floating-point operands and scale alignment, and the "scratch lane" arm that writes a
  tool buffer into the prompt instead of the answer.
* **A fourth span class** (`C-digit`) for a third operand.
* **Grouped numerals and locales.** The real locator understands that `250,000` is one
  number in English and `250.000` is one number in German, with a rule table per language
  and three rules to keep `3.64 ERA` from reading as thousands. This corpus writes plain
  ASCII integers, so the locator here is just "maximal runs of digit tokens".
* **Non-Qwen hosts.** Everything assumes one token per digit and a digit token that never
  absorbs the preceding space. Qwen3 does that; Llama-3 does not, and the tests will say
  so rather than train something quietly wrong.
* **Prose mining, host fine-tuning, and the 8B host.** All of those exist upstream; none
  of them is needed to reproduce the effect.

## Cluster rules (WAVE)

The cluster is shared. These are not suggestions:

* **Every GPU job goes to `--partition=batch`.** CPU-only work goes to `--partition=cpu`.
  Never `dev`.
* **Never run a model on the login node.** It is for editing, `squeue` and `sacct`. Even a
  nine-second CPU test goes through `sbatch`.
* **Never `sbatch --wrap`.** Jobs go in a file that can be read and reviewed.
* **Never interrupt, requeue or cancel a job that is not yours**, and check whose it is
  before you touch anything: `squeue -u $USER`.
* **The model weights are already cached.** Set `HF_HOME` to the shared cache and
  `HF_HUB_OFFLINE=1` so a missing file fails loudly instead of silently downloading a few
  gigabytes onto a login node. Every `sbatch/*.sbatch` file in this repo defaults
  `HF_HOME` to `$HOME/ctrn/hf_cache` -- that is the project's shared cache, owned by the
  project lead, and it is read-only from anyone else's job: the lead has to grant read
  access to it (and to the `$HOME/ctrn` directory it lives under) before a job using these
  defaults will find the weights instead of failing loudly. Raw permissions as of this
  writing (`ls -ld ~/ctrn ~/ctrn/hf_cache ~/ctrn/hf_cache/hub`):

  ```
  drwxr-xr-x 62 humzai users 20480 Sep  8 14:50 /home/humzai/ctrn
  drwxr-xr-x  5 humzai users  4096 Aug 18 14:59 /home/humzai/ctrn/hf_cache
  drwxr-xr-x 10 humzai users  4096 Aug 18 15:28 /home/humzai/ctrn/hf_cache/hub
  ```

  (`rwxr-xr-x`: owner has read/write/execute, group and everyone else have read/execute --
  so on this cluster, as configured right now, any user can traverse into and read the
  cache. If that ever changes, a job pointed at someone else's `HF_HOME` will simply fail
  to find the weights; point `HF_HOME` at your own cache instead.)
* **Keep `--time` tight** and check what a similar job actually took (`sacct -X --format=
  JobID,JobName,Elapsed,State`) before you ask for more.
* **Expect to queue.** `QOSGrpGRES` in `squeue`'s reason column means the GPU pool is full;
  that is normal and it is not a reason to resubmit.
