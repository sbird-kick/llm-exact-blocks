#!/usr/bin/env python3
"""Score a trained block against its own frozen host, per (op, width cell).

    python eval.py --model Qwen/Qwen3-1.7B --data data --ckpt runs/demo/block.pt

WHAT THE COLUMNS MEAN
  rows    how many problems were scored. Printed BEFORE any percentage, always.
  host    the frozen model's answer accuracy. Produced by zeroing `gate`, which makes the
          block bitwise inert, so this is the same model with the same hooks installed --
          not a separate load that might differ in some other way.
  block   the same rows with the block live.
  route   the router picked the right body (or `off` on an off row).
  span    the TAGGER's operand positions equalled the ones build_batch located. The block
          runs with --learned-spans here: at eval time nothing tells it where the digits
          are, which is the only honest way to read the other columns.
  calc    the exact calculator's integer equalled the gold answer -- i.e. the probe read
          both operands correctly AND the router chose the right body.

Answer accuracy is TEACHER-FORCED and ALL-OR-NOTHING: the gold completion is in the
sequence, and a row counts only if the argmax at EVERY answer position is the gold digit.
That is the measure the host is strongest under, since it never has to recover from its
own earlier mistake.
"""
from __future__ import annotations

import argparse
import json
import os

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from exact_block.block import CalcBlock
from exact_block.calc import OPS
from exact_block.data import read_jsonl
from train import run_eval


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-1.7B")
    ap.add_argument("--data", default="data")
    ap.add_argument("--split", default="test")
    ap.add_argument("--ckpt", default="runs/demo/block.pt")
    ap.add_argument("--bs", type=int, default=32)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    ck = torch.load(args.ckpt, map_location="cpu", weights_only=False)
    targs = ck["args"]
    ops = tuple(targs.get("ops", ",".join(OPS)).split(","))
    args.dmax = targs["dmax"]

    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, dtype=torch.bfloat16 if device == "cuda" else torch.float32)
    model.to(device).eval().requires_grad_(False)

    blk = CalcBlock(model.config.hidden_size, dmax=targs["dmax"], ops=ops,
                    off_bias=targs["off_bias"]).to(device).float()
    blk.load_state_dict(ck["state_dict"])
    blk.attach(model, targs["read_layer"], targs["route_layer"], targs["write_layer"])
    print(f"checkpoint {args.ckpt} (step {ck['step']}), read {targs['read_layer']} / "
          f"route {targs['route_layer']} / write {targs['write_layer']}, "
          f"gate {float(blk.gate):+.4f}")

    rows = read_jsonl(os.path.join(args.data, f"{args.split}.jsonl"))
    cells = sorted({p.cell for p in rows if p.cell},
                   key=lambda c: tuple(int(x) for x in c.split("x")))
    # WHICH CELLS WERE ACTUALLY TRAINED is a property of the training FILE, not of a flag,
    # so it is read back from the file rather than trusted from the args.
    train_path = os.path.join(args.data, "train.jsonl")
    train_cells = ({p.cell for p in read_jsonl(train_path) if p.cell}
                   if os.path.exists(train_path) else set())

    print(f"\n{args.split}: {len(rows)} rows, cells {','.join(cells)}\n")
    header = f"{'op':<5} {'cell':<6} {'rows':>5} {'host':>7} {'block':>7} " \
             f"{'route':>7} {'span':>7} {'calc':>7}"
    print(header)
    print("-" * len(header))
    table = []
    for op in ops:
        for cell in cells:
            sub = [p for p in rows if p.op == op and p.cell == cell]
            if not sub:
                continue
            ev = run_eval(model, blk, tok, sub, args, device, bs=args.bs)
            ev.update(op=op, cell=cell)
            table.append(ev)
            mark = "" if not train_cells or cell in train_cells else "  (held out)"
            print(f"{op:<5} {cell:<6} {ev['n_arith']:>5} {ev['host']:>7.4f} "
                  f"{ev['block']:>7.4f} {ev['route']:>7.4f} {ev['span']:>7.4f} "
                  f"{ev['calc']:>7.4f}{mark}")

    off = [p for p in rows if p.op == "off"]
    if off:
        ev = run_eval(model, blk, tok, off, args, device, bs=args.bs)
        ev.update(op="off", cell="")
        table.append(ev)
        print(f"\noff rows: {ev['n_off']}  route(=off) {ev['route']:.4f}  "
              f"fired anyway {ev['fire_on_off']:.4f}")

    ar = [r for r in table if r["op"] != "off"]
    n = sum(r["n_arith"] for r in ar)
    if n:
        agg = {k: sum(r[k] * r["n_arith"] for r in ar) / n
               for k in ("host", "block", "span", "calc")}
        print(f"\nall arithmetic rows: {n}  host {agg['host']:.4f}  "
              f"block {agg['block']:.4f}  span {agg['span']:.4f}  calc {agg['calc']:.4f}")

    out = args.out or os.path.join(os.path.dirname(args.ckpt) or ".",
                                   f"eval_{args.split}.json")
    with open(out, "w") as f:
        json.dump({"ckpt": args.ckpt, "split": args.split, "table": table}, f, indent=1)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
