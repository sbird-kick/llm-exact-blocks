# NOTES since 2026-10-07: what changed in the project that matters to you

Written 2026-10-20 for the students. Plain words, no new result numbers (every number here is a count or an id from
this repo or from the model files). If a line says "check", check it before you rely on it.

## 1. What changed in the project (the short version)

* **Claims are pre-write only.** The project now claims only what is decided *before* the first digit of an answer is
  written. A reader that looks at the numbers after the model has begun writing its answer does not count for the paper.
  Your Llama port is on the pre-write side already (you read the prompt and the cue), so nothing changes for you, but
  keep that wording in your own write-ups.
* **Thinking models.** The readers are now also run on models that think before answering ("thinking mode"). Plain
  (non-thinking) and thinking are two separate settings; never pool them in one table.
* **Tool-call baseline.** The comparison point for "does the reader help" is now a model that is allowed to call a
  calculator tool and a python tool, not a program-of-thought prompt. See section 4 for the formats Llama uses.
* **New train / val / test split rules.** The project re-cut its arithmetic data with one rule set (official splits win;
  rows that belong together stay together; a train row that shares a 10-word sequence with another source's val or
  test row is dropped). The old fold system (folds 1-6 in `data/wild/`) is still what `data/wild/` uses.
  The new rows in `data/more/` follow the new rules and are **train only**. See `data/more/README.md`.
* **Larger numbers are the target.** Rows with 6, 9 and 12-digit numbers matter now; that is why `data/more/` has
  copies of rows with only the numerals redrawn (`selfcue_v24`, `wildbig`).
* **Llama runs moved to a different cluster** (one host per model, each model recorded in full again). You do not need
  to do anything for this; it only means the project's own Llama recordings will not be a shortcut for your port.

## 2. More data: `data/more/`

207,332 train rows, 40 files, each under 25 MB, `python -m defuse.more --out rows.jsonl` joins them after an md5
check and refuses any row that is not `train` in the shipped manifest. **Build your own held-out fold from it, as with
folds 1-4** (the `fold` column is a hash of the row's family, so one family never sits in two folds). Read
`data/more/README.md` for sources, counts, languages, licenses and the filters you will want
(`n_runs <= 5`, `gold_status == "exec_exact"`). Do not mix a held-out fold chosen on `data/more/` with the old
`data/wild/` folds: the old and new rows were not cross-checked against each other.

## 3. Bug found in the project: the numeral finder (and is this repo affected?)

**The bug.** The project's text pattern for finding the numbers in a question used `\w` as the boundary
(`(?<![\w.])(\d+...)(?![\w])`). In Python 3, `\w` also matches Chinese, Japanese, Thai, Devanagari and similar letters,
so a number written right next to such a letter (for example a figure followed by the Chinese word for yuan) was not
found at all. A reader that is handed no numbers can only produce constant-only programs. The project's own arithmetic
readers were fitted with that blind spot; the fix is a refit, folded with the large-number copies, not a patch.

**This repo is not affected.** Checked 2026-10-20 by reading every place `defuse/` finds numbers:

| where | how it finds numbers | verdict |
|---|---|---|
| `defuse/dump.py` `digit_runs_single` / `digit_runs_grouped` | token by token, `str.isdecimal()`, no text pattern | not affected (this is the locator that decides what the readers see) |
| `defuse/reader_a.py` lines 125, 469, 484 | `re.findall(r"\d+", ...)`, no `\w` boundary | not affected |
| `defuse/inventory.py` `NUM_RE` (has the `\w` boundary) | applied to the **gold equation text** (`wrap_literals`), not to the question | not the bug; an equation with digits glued to letters could be mis-parsed; the parse status of every shipped row is stored with the row and re-checked by the tests |
| `defuse/dump.py` `INT_RE`, `defuse/run.py` `NUM` | pick the first number out of the **model's answer** | not affected (no boundary assertion) |
| `defuse/bank_rows.py` `DIGITS = [0-9]+` | ASCII digits only, no boundary | not the same bug, but a related weakness: a bank row written with native digits (Arabic-Indic, Devanagari, ...) gets no runs recorded; the dumper then sees a different run count from `prov.n_runs` and **skips** the row, and counts the skip. `data_gen/selfcue_to_defuse.py` (used for `data/more/`) uses `isdecimal()` like the dumper, so its rows do not have this weakness |

What to do: nothing, except watch the dumper's skip counter on non-English rows (it should be 0 or near 0; report it
as n/total). A row with digits touching Chinese or Thai text is read correctly by the token-based locator.

## 4. What your Llama port needs to know

### 4.1 The exact plain prompt (system date line pinned)
The plain recording uses the question verbatim, with **no instruction of any kind** (no "step by step", no answer-format
line), through the model's own chat template, greedy, no thinking. For Llama-3.2-1B / 3B-Instruct and Llama-3.1-8B-Instruct the
rendered text is the same:

```
<|begin_of_text|><|start_header_id|>system<|end_header_id|>

Cutting Knowledge Date: December 2023
Today Date: 26 Jul 2024

<|eot_id|><|start_header_id|>user<|end_header_id|>

{question}<|eot_id|><|start_header_id|>assistant<|end_header_id|>

```

* The template always opens a system turn. The date is **pinned** to `26 Jul 2024` (pass `date_string="26 Jul 2024"`;
  the 3.2 templates otherwise call `strftime_now` and the prompt changes every day).
* Exactly one `<|begin_of_text|>` (it comes from the template text; do not add a second one when tokenizing).
* The prompt ends at `assistant<|end_header_id|>\n\n`; you generate from there.
* The user text is the question exactly as in the project's rows file. (The def-use rows in this repo end with the cue
  " The answer is" because the dumper reads the cue position; the plain recording and the tool-call cells use the
  cue differently, so decide once what your host sees and keep it the same for every size.)
* Decode: greedy, up to 4,096 new tokens, no budget forcing.

### 4.2 Tokenization (Llama 3 is not Qwen3)
* Digits come in **groups of up to three** (`1234567` is `123` `456` `7`), not one digit per token.
* The space before a numeral is **its own token** (` ` then `165`), so the number does not start with a space.
* Use `--locator grouped` (`defuse/dump.py` `digit_runs_grouped`). A token with a leading space or any other character
  ends a run. Check the dumper's `run_count_mismatch` skip counter on 200 rows before a long job.
* The project's "candidate position" rule (the next token starts a numeral) and character-offset values work as is; the
  token before the first digit group is the one before the number; the last digit group holds the number's last digit.
* A degenerate generation can write thousands of digits; Python refuses `int()` on more than 4,300 digits. Set the
  environment variable `PYTHONINTMAXSTRDIGITS=0` for decode and scoring jobs (the project's Llama runs crashed on this).

### 4.3 End-of-sequence ids
Stop on any of **128009** (`<|eot_id|>`), **128001** (`<|end_of_text|>`) and **128008** (`<|eom_id|>`, "end of
message", the terminator after a tool call). Pad id **128004** (`<|finetune_right_pad_id|>`), left padding for batched
decode. DeepSeek-R1-Distill-Llama-8B (thinking) stops on **128001** only, and its `<think>` / `</think>` are ids
**128013 / 128014** (not special tokens).
Careful with R1-Distill-Llama's tokenizer: with recent `transformers` it can load as a sentencepiece-style tokenizer that
**drops spaces and newlines**. Load it with `PreTrainedTokenizerFast` on the directory's own `tokenizer.json` and check
that `"What is 2 plus 3?"` keeps its spaces.

### 4.4 Each model's native tool-call format (the project uses each model's own trained format)
| model | tool definition goes in | the model answers with | tool result comes back as |
|---|---|---|---|
| Qwen3 (any size) | `tools=` through its chat template | `<tool_call>\n{"name": ..., "arguments": {...}}\n</tool_call>` then `<\|im_end\|>` | a `tool` message (rendered as a user turn) |
| Llama-3.1-8B-Instruct, calculator | the **user** turn: Meta's own wording "Answer the user's question by making use of the following functions if needed. ... Here is a list of functions in JSON format: ... Return function calls in JSON format." plus the tool JSON; system turn has `Environment: ipython` | the whole message is JSON `{"name": "calc", "parameters": {"expression": "12 + 3"}}` (key `parameters`, not `arguments`), optionally behind `<\|python_tag\|>`, ended by `<\|eom_id\|>` or `<\|eot_id\|>` | an `ipython` header turn holding the JSON-quoted string (`"15"`) |
| Llama-3.2-1B / 3B-Instruct, calculator | the **system** turn, in Meta's documented zero-shot function-calling form (Meta's text plus the function list; parameters typed `dict`) | pythonic: `[calc(expression="12 + 3")]` then `<\|eot_id\|>`; several calls may share one list | an `ipython` turn as above |
| all three Llama, python tool | no schema at all: Meta's built-in code interpreter, switched on by `Environment: ipython` in the system turn | `<\|python_tag\|>` + raw python + `<\|eom_id\|>` | an `ipython` turn with the printed output |

Notes: (1) the stock Hugging Face template for the 3.2 models does not implement the pythonic format (its `tools=`
path renders the 3.1 JSON format), so the project builds those prompts itself from the real template's output plus
one inserted line; (2) one call per turn; at most 6 calls per problem; 1,024 new tokens shared across turns; (3) a
malformed call or a call to an undeclared tool is **counted** and its error text is returned to the model, never
silently dropped; (4) the user text is the question plus " The answer is" and nothing else. R1-Distill-Llama has no tool
template; do not give it tools. The project does not use tool calls for the redaction task, for any model.

## 5. Things I would check first
1. `python -m pytest -q tests --ignore=tests/test_cpu.py` (CPU; `test_cpu.py` needs torch).
2. Your Llama dump's skip counter with `--locator grouped` on 200 rows.
3. One rendered prompt per host, printed and compared with 4.1 byte for byte.
4. Your held-out fold: chosen before you fit, from `data/more/` or the old folds, never from both.
