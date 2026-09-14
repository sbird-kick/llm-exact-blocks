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

--decode greedy ALSO free-runs the answer. Nothing fed to the model past the prompt is
gold: the model (host, or host+block) picks a token, that token goes back in as the next
input, and a row counts only if the digits it ends up emitting, read back as one integer,
equal the gold answer. This is slower (one forward pass per generated digit instead of
one for the whole row) and closer to what a user actually gets, so it is opt-in and
samples --decode-rows problems per (op, cell) rather than the whole split. See
`run_greedy_eval` below.
"""
from __future__ import annotations

import argparse
import json
import os

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from exact_block.block import CalcBlock, build_batch
from exact_block.calc import OPS
from exact_block.data import read_jsonl
from train import answer_logits, run_eval


def run_greedy_eval(model, blk, tok, rows, args, device, bs=16):
    """Free-running greedy decode, scored on the decoded integer.

    Teacher-forced accuracy above is measured with the gold completion IN the sequence.
    This is the honest version: generate up to 2*dmax digit tokens (plus a little slack
    for the corpus's leading space) from the answer slot, greedily, once with the block
    gated off (`host`) and once with it live (`block`), feeding each chosen token back in
    as the next input -- exactly what a user typing the prompt at the model gets. A row
    counts as correct only if the decoded digits equal the gold answer.

    `fire_on_off` is the free-running version of eval.py's `fire_on_off`: whether the
    block (gated on) ever wrote anything at all while free-running an OFF row, which
    should never happen.

    Returns a dict with n_arith, n_off, host, block, fire_on_off, and up to 5 `examples`
    of (op, cell, a, b, gold, decoded) for rows the block got wrong -- so a human can look
    at a handful of them before deciding anything is actually broken.
    """
    blk.eval()
    was_learned = blk.learned_spans
    blk.learned_spans = True
    n_arith = n_off = 0
    hit = {"host": 0, "block": 0}
    fired_off = 0
    examples = []
    max_steps = 2 * args.dmax + 2   # the 32 answer lanes, plus slack for the leading space

    with torch.no_grad():
        for i in range(0, len(rows), bs):
            chunk = rows[i:i + bs]
            ids_full, attn_full, ctx = build_batch(tok, chunk, args.dmax, device,
                                                    ops=blk.ops)
            blk.ctx = ctx
            B, T = ids_full.shape
            p0 = ctx["p0"]
            pad_id = tok.pad_token_id if tok.pad_token_id is not None else 0
            arith = ctx["op_label"] < blk.n_ops

            for name, gate_on in (("host", False), ("block", True)):
                saved_gate = blk.gate.detach().clone()
                if not gate_on:
                    blk.gate.data.zero_()          # gate = 0 IS the frozen host, exactly

                # Start from the prompt only -- everything past p0 is generated, not read
                # off the gold completion. Same padded width as the teacher-forced batch
                # (built above for its a_pos/b_pos/ctl_pos), which happens to be exactly
                # enough room for an answer as long as the gold one.
                cur_ids = torch.full_like(ids_full, pad_id)
                cur_attn = torch.zeros_like(attn_full)
                for r in range(B):
                    L = int(p0[r])
                    cur_ids[r, :L] = ids_full[r, :L]
                    cur_attn[r, :L] = 1

                digits = [[] for _ in range(B)]
                started = [False] * B              # seen a digit yet? (skip the leading
                                                    # separator token before it)
                done = torch.zeros(B, dtype=torch.bool, device=device)
                fired = torch.zeros(B, dtype=torch.bool, device=device)

                for t in range(max_steps):
                    if bool(done.all()):
                        break
                    col = p0 + t                    # column the NEXT token lands in
                    pred_pos = (col - 1).clamp(max=T - 1)   # its predictor position
                    hidden = model.model(input_ids=cur_ids, attention_mask=cur_attn,
                                         use_cache=False).last_hidden_state
                    logit = answer_logits(model, hidden, pred_pos.unsqueeze(1)).squeeze(1)
                    nxt = logit.argmax(-1)
                    if gate_on:
                        fired |= (blk.last["mass"] > 0.5)
                    for r in range(B):
                        if done[r]:
                            continue
                        tid = int(nxt[r])
                        s = tok.decode([tid])
                        is_digit = len(s) == 1 and s.isdigit()
                        if not is_digit and started[r]:
                            done[r] = True         # first non-digit after the digits: stop
                            continue
                        if is_digit:
                            started[r] = True
                            digits[r].append(s)
                        c = int(col[r])
                        if c < T:                   # feed the chosen token back in
                            cur_ids[r, c] = tid
                            cur_attn[r, c] = 1

                if not gate_on:
                    blk.gate.data.copy_(saved_gate)

                for r, p in enumerate(chunk):
                    if p.op == "off":
                        if gate_on:
                            fired_off += int(fired[r])
                        continue
                    ok = bool(digits[r]) and int("".join(digits[r])) == p.ans
                    hit[name] += int(ok)
                    if gate_on and not ok and len(examples) < 5:
                        examples.append((p.op, p.cell, p.a, p.b, p.ans,
                                         "".join(digits[r]) or "<empty>"))

            n_arith += int(arith.sum())
            n_off += int((~arith).sum())

    blk.learned_spans = was_learned
    blk.train()
    out = {"n_arith": n_arith, "n_off": n_off}
    for k in ("host", "block"):
        out[k] = hit[k] / max(1, n_arith)
    out["fire_on_off"] = fired_off / max(1, n_off)
    out["examples"] = examples
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-1.7B")
    ap.add_argument("--data", default="data")
    ap.add_argument("--split", default="test")
    ap.add_argument("--ckpt", default="runs/demo/block.pt")
    ap.add_argument("--bs", type=int, default=32)
    ap.add_argument("--out", default="")
    ap.add_argument("--decode", choices=["teacher_forced", "greedy"],
                    default="teacher_forced",
                    help="teacher_forced (default): unchanged. greedy: ALSO free-run the "
                         "answer (see run_greedy_eval) and print host_greedy/block_greedy "
                         "columns and the off-row fire rate alongside the table above.")
    ap.add_argument("--decode-rows", type=int, default=40,
                    help="greedy decoding is one forward pass per generated digit, so it "
                         "samples at most this many rows per (op, cell) rather than "
                         "scoring the whole split.")
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
          f"gate {blk.gate.item():+.4f}")

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

    out_obj = {"ckpt": args.ckpt, "split": args.split, "table": table}

    if args.decode == "greedy":
        print(f"\ngreedy decode (free-running, up to {args.decode_rows} rows sampled "
              f"per cell):\n")
        header2 = f"{'op':<5} {'cell':<6} {'rows':>5} {'host_greedy':>11} " \
                  f"{'block_greedy':>12}"
        print(header2)
        print("-" * len(header2))
        gtable = []
        examples = []
        for op in ops:
            for cell in cells:
                sub = [p for p in rows if p.op == op and p.cell == cell][:args.decode_rows]
                if not sub:
                    continue
                gev = run_greedy_eval(model, blk, tok, sub, args, device,
                                      bs=min(args.bs, 16))
                examples.extend(gev.pop("examples"))
                gev.update(op=op, cell=cell)
                gtable.append(gev)
                print(f"{op:<5} {cell:<6} {gev['n_arith']:>5} {gev['host']:>11.4f} "
                      f"{gev['block']:>12.4f}")

        off_sub = [p for p in rows if p.op == "off"][:args.decode_rows]
        if off_sub:
            gev = run_greedy_eval(model, blk, tok, off_sub, args, device,
                                  bs=min(args.bs, 16))
            gev.pop("examples")
            gev.update(op="off", cell="")
            gtable.append(gev)
            print(f"\noff rows (greedy): {gev['n_off']}  fired anyway "
                  f"{gev['fire_on_off']:.4f}")

        if examples:
            print("\nfirst mismatches (block, greedy) -- op cell a b gold decoded:")
            for ex in examples[:5]:
                print("  ", *ex)

        out_obj["greedy"] = gtable

    out = args.out or os.path.join(os.path.dirname(args.ckpt) or ".",
                                   f"eval_{args.split}.json")
    with open(out, "w") as f:
        json.dump(out_obj, f, indent=1)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
