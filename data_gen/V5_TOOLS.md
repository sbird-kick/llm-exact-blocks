# Bank v5: the templates, the tools, where they live, and their md5s

Bank v5 is the newest bank: 25 languages, four operations (add, sub, mul, div), and
distractors shaped like the ones real word problems carry. **It is finished.** All 16
rounds were written and blind-verified: 4,800 templates were written (16 units of 12 per
language), and cleaning kept **4,352 of 4,800** (per language below). The kept templates
are in this repository, together with the tool chain that made them, so you can
regenerate the bank, look at it, and extend it with your own units. How to use the tools is
in [DATA_GENERATION.md](DATA_GENERATION.md).

## Regenerating the bank

```bash
python banks/make_banks.py --banks v4,v4wild   # optional: only the v5 selftests need these older banks
python banks/make_v5.py                        # about 3.5 minutes; writes banks/v5/bank/ (ignored by git)
python banks/make_v5.py --check-only
```

The clean templates are stored one file per language, `banks/v5/clean/r1-16/<lang>.json`
(25 files of 0.3-0.6 MB), plus `index.json` for what belongs to no language. `make_v5.py`
joins them into `banks/v5/clean/clean_v5_r1-16.json` (ignored by git), byte for byte the
project's clean file, and checks its md5 (`e92b1741ff7d4cac752f18bf033f60e9`;
`--join-only` stops there). It then runs
`gen_v5.py --clean banks/v5/clean/clean_v5_r1-16.json --out-dir banks/v5/bank --min-cell 500`
(which refuses a bank with any row-level violation or any designed cell under 500 rows),
and compares the six output files with `banks/v5/SHIP_V5.md5`. The last line must read
`md5 check: 6/6 files match SHIP_V5.md5`. The result is 104,448 rows (4,352 templates x 24),
`signed_A_int.jsonl` of 291 MB, plus `pairs.json` and `AUDIT_v5.txt`. The md5s were
recorded by regenerating twice, under `PYTHONHASHSEED=0` and `1`, with identical bytes.

Kept templates per language (the rest were dropped by the blind verification; `numdep` =
kept and tagged number-dependent grammar, `demoted` = a signed subtraction kept but filled
with the minuend larger only):

| lang | kept | dropped | numdep | demoted | | lang | kept | dropped | numdep | demoted |
|---|---:|---:|---:|---:|---|---|---:|---:|---:|---:|
| ar | 174 | 18 | 7 | 1 | | nl | 167 | 25 | 0 | 1 |
| bn | 178 | 14 | 0 | 0 | | pl | 176 | 16 | 7 | 2 |
| de | 172 | 20 | 0 | 2 | | pt | 179 | 13 | 0 | 1 |
| el | 166 | 26 | 0 | 3 | | ru | 157 | 35 | 11 | 1 |
| en | 178 | 14 | 0 | 2 | | sw | 177 | 15 | 0 | 4 |
| es | 172 | 20 | 0 | 2 | | ta | 173 | 19 | 0 | 0 |
| fa | 178 | 14 | 0 | 0 | | th | 179 | 13 | 0 | 2 |
| fr | 162 | 30 | 0 | 2 | | tr | 173 | 19 | 6 | 1 |
| he | 179 | 13 | 0 | 5 | | uk | 153 | 39 | 11 | 3 |
| hi | 171 | 21 | 0 | 0 | | vi | 181 | 11 | 0 | 1 |
| id | 184 | 8 | 0 | 4 | | zh | 184 | 8 | 0 | 2 |
| it | 168 | 24 | 0 | 5 | | | | | | |
| ja | 184 | 8 | 0 | 1 | | **all 25** | **4,352** | **448** | **42** | **45** |
| ko | 187 | 5 | 0 | 0 | | | | | | |

By operation the kept templates are add 1,126, sub 1,104, mul 1,090, div 1,032.

## Where the files are

The tools find the older banks' templates through paths relative to their own folder
(`../verified/`, `../writers_wild/`, `../v4/`), so they live one level below `banks/`:

```
banks/
  verified/ distfact/ distfact2/ writers_wild/ gen_signed_bank_ml.py     (see banks/README.md)
  v4/ v4wild/                                                              (python banks/make_banks.py)
  make_v5.py                                                               regenerate + check bank v5
  v5/
    clean/r1-16/<lang>.json        the 4,352 kept templates, one file per language (the bank's only data input)
    clean/r1-16/index.json         the parts of the clean file that belong to no language; README.md says more
    SHIP_V5.md5                    the md5 of every file gen_v5.py writes for it
    V5_CODE.md5                    the md5 of every tool and brief below, as shipped here
    v5_common.py  validate_single.py  validate_v5.py  status_v5.py  make_blind_v5.py
    check_v5.py   host_attr_v5.py     gen_v5.py       manifest_v5.json
    BRIEF_v5_writer.md  VERIFY_v5.md  ADDON_v5_writer_ru_uk.md  DESIGN_v5.md
```

All the tools are standard library only (last run on Python 3.14). Each tool with a
`--selftest` builds a fake tree under `banks/v5/_selftest_tmp/`, checks itself, and deletes
the tree. `gen_v5.py --selftest` also reads `banks/v4/signed_A_int.jsonl` and
`banks/v4wild/signed_A_int.jsonl` (to check that every v4 key is on every v5 row), so run
`make_banks.py` first. On the copies shipped here: `host_attr_v5` 22 checks, `validate_v5`
33, `gen_v5` 18, `status_v5` 21, `make_blind_v5` 11, `check_v5` 12, each `0 fail`.

## Pinned md5s: the project's copies and the copies shipped here

| file | bytes here | project md5 | md5 here | what it is |
|---|---:|---|---|---|
| `v5_common.py` | 36,604 | `3c162b31a9b1ba4ea9bfcd2116a61f78` | `7b99e872a5033bafa8e3009d953e8cb9` | languages, verifier groups, topic slices, the template schema and quotas, text helpers |
| `validate_single.py` | 20,584 | `df1c37d9becc7b1ba552d89989e983f6` | same | the leaf text checks v5_common imports: digits of any script, number words per language, script sanity (ru vs uk, ar vs fa, zh vs ja) |
| `validate_v5.py` | 37,705 | `7a326112b2355029ed62bc1a7aa9fc33` | same | the writer-unit gate (`VALIDATE ok 12`), `--bank` row gate, `--corpus` near-duplicate report, `--calibrate` |
| `status_v5.py` | 22,067 | `4efc3f2cd32b06a2c73e8fb87f254af4` | `a657bc42f56e58e9a840539ded8da3a0` | the manifest, per-unit state recomputed from the files, `--next`, `--accept` |
| `make_blind_v5.py` | 9,870 | `866aefdb86b75b5ba2dff5c27bbf2c2c` | same | blind file + key file per verifier unit, `--base-sample` |
| `check_v5.py` | 19,264 | `741447d90d4a0f9ca6295994108ab918` | same | `--format` (verifiers run it), `--report`, `--clean` |
| `host_attr_v5.py` | 12,549 | `487094606226315106bc2b347799bcba` | same | which pair of numerals a model's integer answer can be attributed to, for all four operations |
| `gen_v5.py` | 35,296 | `dd015dde3d0734d2ebf694b18f3e44b5` | `fa56d9c8031b3b46d097b31098c4d804` | fills clean templates into rows (24 per template), audits them, writes md5s |
| `manifest_v5.json` | 704,820 | `6713f29fbfc3e8c896d479ff6346350d` | same | every writer unit (800) and verifier unit (160) with a stable id (the paths in it are relative) |
| `BRIEF_v5_writer.md` | 18,114 | `3f5a2bf7d19136c2e352c9a5924682c6` | `3c88585f94939bfc8f23cb335297d744` | the writer brief, one unit of 12 templates |
| `VERIFY_v5.md` | 4,770 | `593da4f4c013a2a26bf5c36ebedf5fb1` | `b9766d867ba7c8bc0cebd54502e1b8e6` | the blind verifier brief |
| `ADDON_v5_writer_ru_uk.md` | 6,929 | `05f92d0203b3f9f77039388e091b7886` | same | the Russian / Ukrainian add-on to the writer brief |
| `DESIGN_v5.md` | 18,835 | `145f2d4aee2ad360828a250326fc0b34` | `03e40757c13641f7aef91964c445e6f8` | the design: slots, rows per template, difficulty cells, cost and chunking |
| `clean/clean_v5_r1-16.json` | 10,248,269 | `e92b1741ff7d4cac752f18bf033f60e9` | same, once joined | the kept templates, with their verifier tags; shipped split into `clean/r1-16/` (26 files, md5s in `V5_CODE.md5`) and joined by `make_v5.py` |

(An earlier version of this table pinned `gen_v5.py` at `fc1e1f71...`, 33,863 bytes. The
project updated its generator after that; the md5 above is the project's current one, and
it is the version that generates the bank in `SHIP_V5.md5`.)

## What was changed in the copies, and why

None of these edits touches the logic: every selftest passes on the copies, and the bank
above is what they generate.

1. `v5_common.py` added the project's `singlestep/` folder to `sys.path` to find
   `validate_single.py`. With `validate_single.py` placed beside it, that line is now
   `sys.path.insert(0, HERE)` (and its docstring says so).
2. `BRIEF_v5_writer.md` and `VERIFY_v5.md` named absolute output and validator paths on the
   project's machine; they now give paths relative to the repository root
   (`banks/v5/writers/<lang>/W5-<lang>-uNN.json`, `python3 banks/v5/validate_v5.py <path>`,
   `banks/v5/blind/...`, `banks/v5/verify/...`). Their "never read" fences named specific
   public test sets; they now say "any collected or published word-problem set" and fence
   paths containing `wild`, `test`, `key` or `answers`.
3. `status_v5.py` and `gen_v5.py` each had a person's name in one comment; dropped.
4. `DESIGN_v5.md` is an edited copy: citations of the project's logs are removed, results
   measured on a real-problem test set are described in words only, and its closing list of
   open decisions is left out. Its header says so.

## What is deliberately not here

The v5 working directories: `writers/`, `accept/`, `blind/`, `blind_key/` and `verify/`,
the verification report and disagreement list, and the generated bank. `blind_key/` is, by
design, the one thing a verifier must never see, and the others hold the writers' raw
drafts and the verifiers' raw judgements, which the clean file already summarises. All of
these paths are in `.gitignore`, so a run of your own cannot be committed by accident.
