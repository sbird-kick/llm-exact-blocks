#!/usr/bin/env python3
"""Train the exact-arithmetic block on a FROZEN Qwen3 host.

    python train.py --model Qwen/Qwen3-1.7B --data data --out runs/demo

FOUR LOSSES, AND EACH PART OF THE BLOCK HAS ITS OWN. The exact calculator is not
differentiable -- it argmaxes the probe's digits and then does integer arithmetic -- so
the LM loss alone would never reach the probe, the tagger or (through them) anything that
matters. Each component is therefore supervised directly, from labels build_batch already
knows, and the LM loss is left to train only what it can actually reach:

    lm     cross-entropy of the frozen LM head at the answer positions
           -> trains `write`, `gate`, `gate_head`, and the router through `mass`
    probe  digit cross-entropy at the operand lanes           -> trains `probe`
    span   3-class token cross-entropy over the prompt        -> trains `span`
    route  cross-entropy over add / sub / mul / off           -> trains `control`, route_q

THE HOST NEVER MOVES. Its parameters are requires_grad_(False) and it stays in eval mode;
the only tensors with gradients are the block's ~0.1 M. Because the block reads the host
at layer 8/16 (no grad) and writes at layer 24, autograd only has to keep the activations
of layers 25-27, which is why this trains in minutes on one GPU.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time

import torch
import torch.nn.functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer

from exact_block.block import CalcBlock, build_batch
from exact_block.calc import OPS, decode_places
from exact_block.data import read_jsonl


def ce(logits, target, **kw):
    """Cross-entropy that returns 0 instead of nan when every target is ignored."""
    if (target != -100).sum() == 0:
        return logits.sum() * 0.0
    return F.cross_entropy(logits, target, ignore_index=-100, **kw)


def digit_token_ids(tok):
    ids = []
    for k in range(10):
        t = tok(str(k), add_special_tokens=False)["input_ids"]
        assert len(t) == 1, (
            f"this tokenizer renders {k} as {len(t)} tokens. The whole block assumes one "
            f"token per digit; Qwen3 does that, some other families do not.")
        ids.append(t[0])
    return ids


def warm_start_write(blk, model, tok):
    """Point `write`'s ten columns at the ten digit directions of the frozen LM head.

    NOT a correctness requirement -- gate is zero at step 0 either way, so the model is
    bitwise unchanged and the block would find these directions on its own. It is a
    SPEED requirement: without it the first few hundred steps are spent rediscovering
    what the host's own unembedding already says a "7" looks like.
    """
    W = model.lm_head.weight if hasattr(model, "lm_head") else \
        model.get_output_embeddings().weight
    with torch.no_grad():
        for k, tid in enumerate(digit_token_ids(tok)):
            v = W[tid].detach().float()
            blk.write.weight[:, k] = v / v.norm().clamp_min(1e-6)


def answer_logits(model, hidden, w_pos):
    """LM-head logits at the answer positions only. (B, 2*dmax, V).

    Running the head over the WHOLE sequence would materialise (B, T, 151936) twice (once
    forward, once for the backward) for no reason: only 32 positions per row carry a
    target.
    """
    B, T, d = hidden.shape
    g = hidden.gather(1, w_pos.clamp_min(0).unsqueeze(-1).expand(B, w_pos.shape[1], d))
    head = model.lm_head if hasattr(model, "lm_head") else model.get_output_embeddings()
    return head(g)


def run_eval(model, blk, tok, rows, args, device, bs=32, limit=None):
    """Answer / route / span / calc accuracy on a list of problems. Counts, then rates."""
    rows = rows[:limit] if limit else rows
    blk.eval()
    was_learned = blk.learned_spans
    blk.learned_spans = True                       # deployment: locate with the tagger
    n = dict(arith=0, off=0)
    hit = dict(host=0, block=0, route=0, span=0, calc=0, fire_off=0)
    with torch.no_grad():
        for i in range(0, len(rows), bs):
            chunk = rows[i:i + bs]
            ids, attn, ctx = build_batch(tok, chunk, args.dmax, device, ops=blk.ops)
            blk.ctx = ctx
            gold_a, gold_b = ctx["a_pos"], ctx["b_pos"]
            arith = ctx["op_label"] < blk.n_ops

            saved = blk.gate.detach().clone()
            blk.gate.data.zero_()                  # gate = 0 IS the frozen host, exactly
            h0 = model.model(input_ids=ids, attention_mask=attn,
                                  use_cache=False).last_hidden_state
            lg0 = answer_logits(model, h0, ctx["w_pos"])
            blk.gate.data.copy_(saved)

            h1 = model.model(input_ids=ids, attention_mask=attn,
                                  use_cache=False).last_hidden_state
            lg1 = answer_logits(model, h1, ctx["w_pos"])
            last = blk.last

            live = ctx["w_tok"] != -100
            for name, lg in (("host", lg0), ("block", lg1)):
                ok = ((lg.argmax(-1) == ctx["w_tok"]) | ~live).all(1) & arith
                hit[name] += int(ok.sum())
            hit["route"] += int((last["control"].argmax(-1) == ctx["op_label"]).sum())
            span_ok = ((last["a_pos"] == gold_a).all(1)
                       & (last["b_pos"] == gold_b).all(1) & arith)
            hit["span"] += int(span_ok.sum())
            # did the calculator produce the right integer from what it read?
            got = decode_places(last["R"])
            hit["calc"] += sum(1 for j, p in enumerate(chunk)
                               if p.op != "off" and got[j] == p.ans)
            hit["fire_off"] += int(((last["mass"] > 0.5) & ~arith).sum())
            n["arith"] += int(arith.sum())
            n["off"] += int((~arith).sum())
    blk.learned_spans = was_learned
    blk.train()
    tot = n["arith"] + n["off"]
    out = {"n_arith": n["arith"], "n_off": n["off"], "n_rows": tot}
    for k in ("host", "block", "span", "calc"):
        out[k] = hit[k] / max(1, n["arith"])
    out["route"] = hit["route"] / max(1, tot)
    out["fire_on_off"] = hit["fire_off"] / max(1, n["off"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-1.7B")
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="runs/demo")
    ap.add_argument("--ops", default=",".join(OPS))
    ap.add_argument("--dmax", type=int, default=16)
    ap.add_argument("--read-layer", type=int, default=8)
    ap.add_argument("--route-layer", type=int, default=16)
    ap.add_argument("--write-layer", type=int, default=24)
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--bs", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--off-bias", type=float, default=2.0)
    ap.add_argument("--aux-weight", type=float, default=1.0, help="probe digit CE")
    ap.add_argument("--span-weight", type=float, default=1.0)
    ap.add_argument("--route-weight", type=float, default=1.0)
    ap.add_argument("--warm-write", type=int, default=1)
    ap.add_argument("--eval-every", type=int, default=500)
    ap.add_argument("--eval-rows", type=int, default=512)
    ap.add_argument("--log-every", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    os.makedirs(args.out, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    ops = tuple(args.ops.split(","))

    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, dtype=torch.bfloat16 if device == "cuda" else torch.float32)
    model.to(device).eval().requires_grad_(False)          # THE HOST NEVER MOVES

    blk = CalcBlock(model.config.hidden_size, dmax=args.dmax, ops=ops,
                    off_bias=args.off_bias).to(device).float()
    if args.warm_write:
        warm_start_write(blk, model, tok)
    blk.attach(model, args.read_layer, args.route_layer, args.write_layer)
    n_par = sum(p.numel() for p in blk.parameters())
    print(f"host {args.model}: {sum(p.numel() for p in model.parameters()):,} frozen "
          f"params, {len(model.model.layers)} layers, d={model.config.hidden_size}")
    print(f"block: {n_par:,} trainable params "
          f"(read {args.read_layer} / route {args.route_layer} / write {args.write_layer})")
    for name, p in blk.named_parameters():
        print(f"  {name:<18} {tuple(p.shape)}  {p.numel():,}")

    train_rows = read_jsonl(os.path.join(args.data, "train.jsonl"))
    val_rows = read_jsonl(os.path.join(args.data, "val.jsonl"))
    print(f"train rows {len(train_rows)}, val rows {len(val_rows)}")

    opt = torch.optim.AdamW(blk.parameters(), lr=args.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.steps)
    history = {"args": vars(args), "train": [], "evals": []}
    order, cursor = list(range(len(train_rows))), 0
    random.shuffle(order)
    t0 = time.time()

    for step in range(1, args.steps + 1):
        if cursor + args.bs > len(order):
            random.shuffle(order)
            cursor = 0
        chunk = [train_rows[i] for i in order[cursor:cursor + args.bs]]
        cursor += args.bs

        ids, attn, ctx = build_batch(tok, chunk, args.dmax, device, ops=ops)
        blk.ctx = ctx
        blk.learned_spans = False          # train with SUPPLIED positions + a span loss
        hidden = model.model(input_ids=ids, attention_mask=attn,
                             use_cache=False).last_hidden_state
        logits = answer_logits(model, hidden, ctx["w_pos"])
        last = blk.last

        V = logits.shape[-1]
        lm = ce(logits.reshape(-1, V).float(), ctx["w_tok"].reshape(-1))
        probe = (ce(last["a_logits"].reshape(-1, 10), ctx["a_dig"].reshape(-1))
                 + ce(last["b_logits"].reshape(-1, 10), ctx["b_dig"].reshape(-1)))
        span = ce(last["span_logits"].reshape(-1, last["span_logits"].shape[-1]),
                  ctx["span_labels"].reshape(-1))
        route = F.cross_entropy(last["ctl_logits"], ctx["op_label"])
        loss = (lm + args.aux_weight * probe + args.span_weight * span
                + args.route_weight * route)

        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(blk.parameters(), 1.0)
        opt.step()
        sched.step()

        if step % args.log_every == 0 or step == 1:
            rec = dict(step=step, loss=float(loss), lm=float(lm), probe=float(probe),
                       span=float(span), route=float(route),
                       gate=float(blk.gate), mass=float(last["mass"].mean()),
                       secs=round(time.time() - t0, 1))
            history["train"].append(rec)
            print(f"step {step:>5} loss {rec['loss']:.4f} lm {rec['lm']:.4f} "
                  f"probe {rec['probe']:.4f} span {rec['span']:.4f} "
                  f"route {rec['route']:.4f} gate {rec['gate']:+.3f} "
                  f"mass {rec['mass']:.3f} {rec['secs']}s", flush=True)

        if step % args.eval_every == 0 or step == args.steps:
            ev = run_eval(model, blk, tok, val_rows, args, device, limit=args.eval_rows)
            ev["step"] = step
            history["evals"].append(ev)
            print(f"  [val @ {step}] rows {ev['n_rows']} "
                  f"(arith {ev['n_arith']}, off {ev['n_off']})  "
                  f"host {ev['host']:.4f}  block {ev['block']:.4f}  "
                  f"route {ev['route']:.4f}  span {ev['span']:.4f}  "
                  f"calc {ev['calc']:.4f}  fire-on-off {ev['fire_on_off']:.4f}",
                  flush=True)
            torch.save({"state_dict": blk.state_dict(), "args": vars(args),
                        "step": step}, os.path.join(args.out, "block.pt"))
            with open(os.path.join(args.out, "history.json"), "w") as f:
                json.dump(history, f, indent=1)

    print(f"done in {time.time() - t0:.0f}s -> {args.out}/block.pt")


if __name__ == "__main__":
    main()
