# Bank v5's clean templates, one file per language

The 4,352 templates that blind verification kept (of 4,800 written, rounds 1-16), split by
language so that no file is large:

* `<lang>.json` (25 files, 0.3-0.6 MB each): `{"lang", "kept", "dropped"}`, that language's
  kept templates (with their verifier tags) and the ids and reasons of its dropped ones;
* `index.json`: what belongs to no language: the language list, `pending_units` (empty: the
  bank is finished), the top-level key order, the counts, and the md5 of the joined file.

`python banks/make_v5.py --join-only` joins them into `banks/v5/clean/clean_v5_r1-16.json`
(ignored by git), byte for byte the project's clean file, md5
`e92b1741ff7d4cac752f18bf033f60e9`; `python banks/make_v5.py` does that and then regenerates
the bank. `make_v5.split_clean()` splits a clean file of your own the same way.
