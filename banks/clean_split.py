#!/usr/bin/env python3
"""Split a multilingual clean-template file into one file per language, and join it back byte for byte.

    python banks/clean_split.py split <clean.json> <out_dir>    # <out_dir>/<lang>.json + <out_dir>/index.json
    python banks/clean_split.py join <split_dir> <clean.json>   # the original file, byte for byte (md5 checked)

A clean file is one JSON object written by the project's tools with
json.dumps(obj, ensure_ascii=False, indent=1) + "\\n". Its lists of templates ("kept",
"dropped", ...) hold entries that each carry a "lang". split() writes, per language, an
object {"lang", <each list>: that language's entries in their original order}, and an
index.json with everything else: the other top-level keys and values, the key order, the
language of every entry of every list in its original order (so the join puts each entry
back where it was), and the md5 of the original file. join() rebuilds the object from
those pieces and refuses if the md5 differs. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys


def dump(obj) -> str:
    """The project's clean-file serialisation, exactly."""
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def md5_bytes(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def split_clean(clean_path: str, out_dir: str) -> list[str]:
    raw = open(clean_path, "rb").read()
    d = json.loads(raw)
    if dump(d).encode("utf-8") != raw:
        raise SystemExit(f"{clean_path}: not in the project's serialisation; refusing to split")
    lists = [k for k, v in d.items() if isinstance(v, list) and v and all(isinstance(e, dict) and "lang" in e for e in v)]
    langs = sorted({e["lang"] for k in lists for e in d[k]})
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for lang in langs:
        part = {"lang": lang}
        part.update({k: [e for e in d[k] if e["lang"] == lang] for k in lists})
        p = os.path.join(out_dir, f"{lang}.json")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(dump(part))
        written.append(p)
    index = {
        "source_file": os.path.basename(clean_path),
        "joined_md5": md5_bytes(raw),
        "languages": langs,
        "top_level_keys": list(d),
        "split_lists": lists,
        "order": {k: [e["lang"] for e in d[k]] for k in lists},
        "counts": {k: {lang: sum(e["lang"] == lang for e in d[k]) for lang in langs} for k in lists},
        "other": {k: v for k, v in d.items() if k not in lists},
    }
    p = os.path.join(out_dir, "index.json")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(dump(index))
    return written + [p]


def join_clean(split_dir: str) -> tuple[bytes, str]:
    """(the joined file's bytes, the md5 it must have)."""
    index = json.load(open(os.path.join(split_dir, "index.json"), encoding="utf-8"))
    parts = {lang: json.load(open(os.path.join(split_dir, f"{lang}.json"), encoding="utf-8"))
             for lang in index["languages"]}
    pos = {(lang, k): 0 for lang in parts for k in index["split_lists"]}
    whole = {}
    for k in index["top_level_keys"]:
        if k in index["split_lists"]:
            out = []
            for lang in index["order"][k]:
                out.append(parts[lang][k][pos[(lang, k)]])
                pos[(lang, k)] += 1
            whole[k] = out
        else:
            whole[k] = index["other"][k]
    for (lang, k), n in pos.items():
        if n != len(parts[lang][k]):
            raise SystemExit(f"{split_dir}/{lang}.json: {len(parts[lang][k])} entries in {k}, index.json places {n}")
    return dump(whole).encode("utf-8"), index["joined_md5"]


def write_joined(split_dir: str, out_path: str) -> str:
    b, want = join_clean(split_dir)
    got = md5_bytes(b)
    if got != want:
        raise SystemExit(f"join of {split_dir}: md5 {got}, expected {want}")
    with open(out_path, "wb") as fh:
        fh.write(b)
    return got


def main(argv=None) -> int:
    a = sys.argv[1:] if argv is None else argv
    if len(a) == 3 and a[0] == "split":
        for p in split_clean(a[1], a[2]):
            print(p)
        return 0
    if len(a) == 3 and a[0] == "join":
        print(f"{a[2]} md5 {write_joined(a[1], a[2])} (ok)")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
