#!/usr/bin/env python3
"""Regenerate bank v5 from its per-language clean template files and check every byte.

    python banks/make_v5.py                 # join the clean files, check the md5, run gen_v5.py -> banks/v5/bank/, check
    python banks/make_v5.py --check-only    # only compare banks/v5/bank/ with banks/v5/SHIP_V5.md5
    python banks/make_v5.py --join-only     # only rebuild banks/v5/clean/clean_v5_r1-16.json and check its md5

Bank v5 is 4,352 blind-verified templates in 25 languages (add / sub / mul / div), kept from
4,800 written. They are stored one file per language, banks/v5/clean/r1-16/<lang>.json, plus
banks/v5/clean/r1-16/index.json for the parts that belong to no language. gen_v5.py fills
each template 24 ways, so the bank is 104,448 rows (about 290 MB, never committed;
banks/v5/bank/ is ignored by git). It takes about three and a half minutes on a laptop,
standard library only.

The steps:
  1. join the 25 language files into banks/v5/clean/clean_v5_r1-16.json (ignored by git) in
     the order check_v5.py wrote it (unit number, then language, then template number): the
     result is byte for byte the project's clean file, whose md5 must be the one below;
  2. gen_v5.py --clean <that file> --out-dir banks/v5/bank --min-cell 500
     (it refuses a bank with a row-level violation or a designed cell under 500 rows);
  3. every file listed in banks/v5/SHIP_V5.md5 must match.

gen_v5.py keys every random draw through blake2b, never through Python's per-process hash,
so the bytes do not depend on the machine or on PYTHONHASHSEED (the md5s in SHIP_V5.md5 were
recorded twice, under PYTHONHASHSEED=0 and 1, with identical results).

split_clean() is the inverse of join_clean(): it is how the per-language files were made
from the project's single clean file, and you can use it on a clean file of your own.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
V5 = os.path.join(HERE, "v5")
SPLIT_DIR = os.path.join(V5, "clean", "r1-16")
CLEAN = os.path.join(V5, "clean", "clean_v5_r1-16.json")
CLEAN_MD5 = "e92b1741ff7d4cac752f18bf033f60e9"
# the languages in check_v5.py's order (v5_common.LANGS); the order of the joined lists depends on it
LANGS = ("ar bn de el en es fa fr he hi id it ja ko nl pl pt ru sw ta th tr uk vi zh").split()

sys.path.insert(0, HERE)
from make_banks import check, md5_of, read_ship  # noqa: E402


def dump(obj) -> str:
    """check_v5.py's serialisation, exactly."""
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def order_key(template_id: str):
    """W5-<lang>-uNN-KK -> (unit, language position, template): check_v5.py's order."""
    _, lang, unit, k = template_id.split("-")
    return int(unit[1:]), LANGS.index(lang), int(k)


def split_clean(clean_path: str, out_dir: str) -> list[str]:
    """One file per language ({"lang", "kept", "dropped"}) + index.json (everything else)."""
    d = json.load(open(clean_path, encoding="utf-8"))
    os.makedirs(out_dir, exist_ok=True)
    langs = sorted({e["lang"] for e in d["kept"]} | {e["lang"] for e in d["dropped"]})
    written = []
    for lang in langs:
        part = dict(lang=lang, kept=[e for e in d["kept"] if e["lang"] == lang],
                    dropped=[e for e in d["dropped"] if e["lang"] == lang])
        p = os.path.join(out_dir, f"{lang}.json")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(dump(part))
        written.append(p)
    index = {k: v for k, v in d.items() if k not in ("kept", "dropped")}
    index.update(languages=langs, joined_md5=md5_of(clean_path), top_level_keys=list(d),
                 n_kept=len(d["kept"]), n_dropped=len(d["dropped"]))
    p = os.path.join(out_dir, "index.json")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(dump(index))
    return written + [p]


def join_clean(split_dir: str = SPLIT_DIR) -> dict:
    """The clean file as one object, lists in check_v5.py's order and keys in its order."""
    index = json.load(open(os.path.join(split_dir, "index.json"), encoding="utf-8"))
    kept, dropped = [], []
    for lang in index["languages"]:
        part = json.load(open(os.path.join(split_dir, f"{lang}.json"), encoding="utf-8"))
        kept += part["kept"]
        dropped += part["dropped"]
    kept.sort(key=lambda e: order_key(e["template"]["id"]))
    dropped.sort(key=lambda e: order_key(e["template"]))
    whole = dict(kept=kept, dropped=dropped)
    whole.update({k: index[k] for k in index["top_level_keys"] if k not in whole})
    return {k: whole[k] for k in index["top_level_keys"]}


def write_joined(split_dir: str = SPLIT_DIR, out: str = CLEAN) -> str:
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(dump(join_clean(split_dir)))
    return md5_of(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(V5, "bank"), help="where gen_v5.py writes the bank")
    ap.add_argument("--ship", default=os.path.join(V5, "SHIP_V5.md5"))
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--join-only", action="store_true")
    a = ap.parse_args(argv)
    ship = {f"bank/{rel}": d for rel, d in read_ship(a.ship).items()}

    if not a.check_only:
        got = write_joined()
        print(f"clean file: joined {os.path.relpath(SPLIT_DIR, HERE)}/*.json -> "
              f"{os.path.relpath(CLEAN, HERE)} md5 {got} ({'ok' if got == CLEAN_MD5 else 'EXPECTED ' + CLEAN_MD5})")
        if got != CLEAN_MD5:
            return 2
        if a.join_only:
            return 0
        os.makedirs(a.out, exist_ok=True)
        log = os.path.join(a.out, "gen.log")
        cmd = [sys.executable, os.path.join(V5, "gen_v5.py"), "--clean", CLEAN,
               "--out-dir", a.out, "--min-cell", "500"]
        print(f"== v5: generating into {os.path.relpath(a.out)} (about three and a half minutes)")
        with open(log, "w", encoding="utf-8") as fh:
            rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")).returncode
        print(f"   gen_v5.py exit {rc}; log: {os.path.relpath(log)}")
        if rc != 0:
            print("   gen_v5.py refused the bank (a violation or a cell under 500 rows): see the log")
            return 1
    # check() takes <out>/<rel>; the ship keys are "bank/<file>", so hand it the parent of --out
    out_parent = os.path.dirname(os.path.abspath(a.out))
    if os.path.basename(os.path.abspath(a.out)) != "bank":
        ship = {os.path.join(os.path.basename(os.path.abspath(a.out)), k.split("/", 1)[1]): d
                for k, d in ship.items()}
    return 1 if check(out_parent, [next(iter(ship)).split("/")[0]], ship, "SHIP_V5.md5") else 0


if __name__ == "__main__":
    sys.exit(main())
