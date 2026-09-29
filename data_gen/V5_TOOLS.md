# The bank v5 tools: what they are, where they go, and their pinned md5s

Bank v5 is the next bank: 25 languages, four operations (add, sub, mul, div), and
distractors shaped like the ones real word problems carry. At the time of writing rounds 1-5
of 16 are written and verified, and 1,357 of 1,500 templates were kept. **The v5 templates
are not shipped yet; they arrive when the bank is finished.** What is pinned here is the
tool chain, so you can run the pipeline, extend it, and write your own units with it. How
to use it is in [DATA_GENERATION.md](DATA_GENERATION.md).

## Where the files go

The tools find the older banks' templates through paths relative to their own folder
(`../verified/`, `../writers_wild/`, `../v4/`), so they live one level below `banks/`:

```
banks/
  verified/ distfact/ distfact2/ writers_wild/ gen_signed_bank_ml.py     (see banks/README.md)
  v4/ v4wild/                                                              (python banks/make_banks.py)
  v5/
    v5_common.py  validate_single.py  validate_v5.py  status_v5.py  make_blind_v5.py
    check_v5.py   host_attr_v5.py     gen_v5.py       manifest_v5.json
    BRIEF_v5_writer.md  VERIFY_v5.md  ADDON_v5_writer_ru_uk.md
```

All of them are standard library only (last run on Python 3.14). Each tool with a `--selftest`
builds a fake tree under `banks/v5/_selftest_tmp/`, checks itself, and deletes the tree.

## Pinned md5s (the project's copies)

| file | bytes | md5 | what it is |
|---|---:|---|---|
| `v5_common.py` | 36,632 | `3c162b31a9b1ba4ea9bfcd2116a61f78` | languages, verifier groups, topic slices, the template schema and quotas, text helpers |
| `validate_single.py` | 20,584 | `df1c37d9becc7b1ba552d89989e983f6` | the leaf text checks v5_common imports: digits of any script, number words per language, script sanity (ru vs uk, ar vs fa, zh vs ja) |
| `validate_v5.py` | 37,705 | `7a326112b2355029ed62bc1a7aa9fc33` | the writer-unit gate (`VALIDATE ok 12`), `--bank` row gate, `--corpus` near-duplicate report, `--calibrate` |
| `status_v5.py` | 22,085 | `4efc3f2cd32b06a2c73e8fb87f254af4` | the manifest, per-unit state recomputed from the files, `--next`, `--accept` |
| `make_blind_v5.py` | 9,870 | `866aefdb86b75b5ba2dff5c27bbf2c2c` | blind file + key file per verifier unit, `--base-sample` |
| `check_v5.py` | 19,264 | `741447d90d4a0f9ca6295994108ab918` | `--format` (verifiers run it), `--report`, `--clean` |
| `host_attr_v5.py` | 12,549 | `487094606226315106bc2b347799bcba` | which pair of numerals a model's integer answer can be attributed to, for all four operations |
| `gen_v5.py` | 33,863 | `fc1e1f71c26fe39cb6a511f818549d50` | fills clean templates into rows (24 per template), audits them, writes md5s |
| `manifest_v5.json` | 704,820 | `6713f29fbfc3e8c896d479ff6346350d` | every writer unit (800) and verifier unit (160) with a stable id |
| `BRIEF_v5_writer.md` | 18,179 | `3f5a2bf7d19136c2e352c9a5924682c6` | the writer brief, one unit of 12 templates |
| `VERIFY_v5.md` | 4,918 | `593da4f4c013a2a26bf5c36ebedf5fb1` | the blind verifier brief |
| `ADDON_v5_writer_ru_uk.md` | 6,929 | `05f92d0203b3f9f77039388e091b7886` | the Russian / Ukrainian add-on to the writer brief |

## The three edits a copy needs (so its md5 will differ, by design)

1. `v5_common.py` adds `ROLE/singlestep` to `sys.path` to find `validate_single.py`. With
   `validate_single.py` placed beside it, that line becomes
   `sys.path.insert(0, HERE)`.
2. `BRIEF_v5_writer.md` and `VERIFY_v5.md` name absolute output and validator paths of the
   project's machine; replace them with paths relative to `banks/v5/` (for example
   `banks/v5/writers/<lang>/W5-<lang>-uNN.json` and
   `python banks/v5/validate_v5.py <your output path>`).
3. `status_v5.py`'s docstring names a person on its "UNITS" line; drop the name.

Keep a two-column md5 table (the project's md5 above, and your copy's) so anyone can see
exactly which files you changed.

## What is deliberately not here

The v5 working directories: `writers/`, `accept/`, `blind/`, `blind_key/`, `verify/`,
`clean/` and the generated bank. They are the bank in progress (and `blind_key/` is, by
design, the one thing a verifier must never see). The design notes that cite the project's
own logs and real-problem test numbers are summarised, with synthetic numbers only, in
[DATA_GENERATION.md](DATA_GENERATION.md) instead.
