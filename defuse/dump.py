"""dump.py -- dump a frozen host's hidden states at the cue: the def-use reader's only GPU step.

    python -m defuse.dump --host <HF model name> --tag <name> --out <dir> --banks NAME=rows.jsonl[,NAME2=...] \
        --layers 20,24,28 [--space-layers 20,24,28] --max-runs 5 [--greedy 12] [--batch 8] [--locator single|grouped]

For every row: the hidden state at the LAST token of each digit run (H_run_last) and the mean over the run
(H_run_mean) at --layers; the state at the answer position, i.e. after the cue plus one appended space (H_space),
and at the last prompt token (H_slot) at --space-layers; the attention MASS from those two positions onto each run,
every layer and head (A_space, A_slot); and, with --greedy N, the host's own greedy answer (N new tokens), which is
what the host-outcome labels (host right / host silent) are computed from. Output: <out>/<tag>_<NAME>_operandstate.pt.

PORTED, NOT REWRITTEN: the project's pinned batched dumper `hsig_operandstate_v2b.py` (md5
6a583426e23e8cb08cf2ef8184061dda), which is already host-agnostic (--host is any Hugging Face causal LM). Patches
(PROVENANCE.md): the locator is no longer imported from a cluster path; `digit_runs_single` below is the project's
pinned locator (`block.digit_runs`, block.py md5 aed2e8163bc97ab2db7e077036e87187; logic verbatim, comment shortened).
NEW: `--locator grouped` for tokenizers that put up to three digits in one token (Llama 3): a run is a maximal span
of tokens that decode to decimal digits only. The default `single` reproduces the project's dumps on Qwen3.

Rows must carry: row_id, text (the prompt, ending at the cue), status == "scored", prov.gold_run_idx (indices of
the gold operand runs, may be empty) and prov.n_runs (the run count the row's builder saw; a row whose tokenisation
gives another count is SKIPPED and counted, never truncated). Layer indices are hidden_states indices (0 = the
embeddings), as in the project; pick the layers for your host by depth (the project used 20/24/28 of 36 at 8B,
16/19/22 of 28 at 1.7B / 0.6B, 42/48/56 of 64 at 32B). The eager attention implementation is required for the
attention mass. Original header follows.
"""
"""hsig_operandstate_v2b.py -- BATCHED twin of hsig_operandstate_v2.py (md5 0f47f7d4b70162b8a5cc42f22978c4cf).
Same outputs, same schema, same tensors; the forward pass and the greedy pass run over batches of rows.

WHY A NEW FILE AND NOT AN EDIT. Every dump this project has quoted was produced by v2, and its sbatch scripts
record it as UNMODIFIED. Editing it would retroactively make those dumps unreproducible. v2 stays frozen; this is
the twin, and nothing from it may be quoted until `agree_batchdump.py` shows the two agree to the row.

THE ORIGINAL IS BATCH-1 BY CONSTRUCTION: its docstring says "One forward per row, no block attached", the loop is
`for r in rows:` and the model call is `model(input_ids=ids_t, ...)` with a leading dim of 1. Every prompt in the
bank is independent, so this is pure sequential waste -- 2,500 forwards of a 36-layer 8B model, one at a time.

WHY RIGHT PADDING FOR THE FORWARD PASS, AND WHY LEFT PADDING WOULD HAVE BEEN A TRAP.
  * The script records ABSOLUTE positions: each digit run's token indices, `P-1` (the last prompt token), and
    `-1` (the answer position). Left padding slides every one of those by that row's pad count.
  * Worse, and quietly: a bare `model(input_ids=..., attention_mask=...)` does NOT rebuild `position_ids` from the
    mask -- it defaults to arange(T). Under left padding the real tokens would then start at position pad_k
    instead of 0, shifting RoPE for every row by a different amount. Nothing raises. The hidden states would
    simply be wrong, and wrong in a way that still looks like plausible hidden states.
  * Right padding has neither problem. The mask is CAUSAL, so trailing pads are already invisible to every real
    query position -- a real token at position i attends only to <= i, and the pads are all > i. Run indices and
    P-1 keep their values. position_ids = arange is correct for the real prefix. The single change needed is that
    `-1` (the answer position) must become the explicit per-row last real index, L_k - 1.
  * The attention MASS is therefore unchanged too. Softmax normalises over the keys a query can see, which under
    a causal mask with trailing pads is exactly the same key set as in the unpadded run.

THE GREEDY PASS IS THE EXCEPTION and it is the expensive half: `generate(max_new_tokens=12)` is twelve sequential
forwards per row against the dump's one. HF requires LEFT padding for batched generation (a right-padded row would
continue from a pad token), so that pass left-pads, and `generate` does build position_ids from the mask, which is
why it is safe there and not in the raw forward. Rows are trimmed back per row by their own input length.

LENGTH BUCKETING, because `output_attentions=True` materialises [B, nh, T, T] for every one of the 36 layers:
at T=120, B=8, nh=32 that is ~2 GB; at T=512 it is ~38 GB. Rows are sorted by token length, batched among
neighbours, and the outputs are scattered back into ORIGINAL BANK ORDER so the saved .pt is row-for-row
comparable with a batch-1 dump. Order is part of the contract: the probe indexes meta and the tensors together."""
import argparse, hashlib, json, os, re, sys, time


# ---- helpers COPIED VERBATIM from hsig_operandstate_v2.py (md5 0f47f7d4b70162b8a5cc42f22978c4cf). Do not
# "improve" them: any difference here shows up as a batch-vs-batch-1 disagreement and gets blamed on batching.
# I wrote my own versions first and all three were wrong -- first_int by a hand-rolled loop with different
# semantics, load_bank by dropping both the status/prov filter and encoding="utf-8" (which would have mangled
# 24 of the 25 languages on a node without a UTF-8 locale), file_md5 by truncating the digest.


def file_md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def load_bank(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                if r.get("status") == "scored" and isinstance(r.get("prov"), dict) and r["prov"].get("gold_run_idx") is not None:
                    rows.append(r)
    return rows


INT_RE = re.compile(r"-?\d[\d,]*")


def first_int(s):
    m = INT_RE.search(s)
    if not m: return None
    try: return int(m.group(0).replace(",", ""))
    except ValueError: return None


# ---- the locator. digit_runs_single: the project's pinned block.digit_runs (block.py aed2e816), logic verbatim.
def digit_runs_single(tok, ids):
    """Maximal runs of single-digit tokens. Qwen3 puts one digit per token, so a rendered number IS a contiguous
    run. On a tokenizer that merges digits this returns the wrong thing (use --locator grouped there)."""
    runs, cur = [], []
    for i, t in enumerate(ids):
        s = tok.decode([t])
        # .isdecimal(), NOT .isdigit(): a superscript two is a "digit" but int() rejects it, so it must not join a
        # number run; genuine non-ASCII decimal digits (Arabic-Indic, Devanagari, ...) are decimals and do join.
        if len(s) == 1 and s.isdecimal():
            cur.append(i)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def digit_runs_grouped(tok, ids):
    """NEW (not in the project): maximal runs of tokens that decode to one or more decimal digits and nothing else
    (Llama 3 writes 1234567 as '123' '456' '7'). A token with a leading space or any other character ends a run, so
    two numbers separated by a space stay two runs. Check the run count against the row's prov.n_runs (the dumper
    does, and skips mismatches) before trusting it on a new tokenizer."""
    runs, cur = [], []
    for i, t in enumerate(ids):
        s = tok.decode([t])
        if s and s.isdecimal():
            cur.append(i)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True); ap.add_argument("--tag", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--banks", required=True); ap.add_argument("--layers", default="13,17,21,25")
    ap.add_argument("--space-layers", default=""); ap.add_argument("--max-runs", type=int, default=12)
    ap.add_argument("--greedy", type=int, default=0); ap.add_argument("--greedy-banks", default="")
    ap.add_argument("--max-rows", type=int, default=0); ap.add_argument("--device", default="cuda")
    ap.add_argument("--locator", default="single", choices=["single", "grouped"],
                    help="single = the project's locator (one digit per token, Qwen3); grouped = NEW, multi-digit tokens (Llama 3)")
    ap.add_argument("--batch", type=int, default=8, help="forward-pass batch size; 1 reproduces v2's shape of work")
    ap.add_argument("--greedy-batch", type=int, default=0, help="0 = same as --batch")
    ap.add_argument("--dtype", default="bf16", choices=["bf16", "fp32", "fp16"],
                    help="DIAGNOSTIC ONLY. bf16 = production, identical to v2. fp32 isolates bf16 rounding.")
    ap.add_argument("--pad-to", type=int, default=0,
                    help="DIAGNOSTIC ONLY. Right-pad every forward batch to at least this many tokens, so T can be\n                         varied with B held at 1 -- separates padding from the batch dimension.")
    ap.add_argument("--max-batch-tokens", type=int, default=250000,
                    help="cap on batch * T^2 / 1000 so the [B,nh,T,T] attention tensors stay bounded")
    a = ap.parse_args()
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    digit_runs = digit_runs_single if a.locator == "single" else digit_runs_grouped
    gb = a.greedy_batch or a.batch

    banks = []
    for item in a.banks.split(","):
        n, _, p = item.partition("=")
        banks.append((n, p))
    layers = [int(x) for x in a.layers.split(",")]
    slayers = [int(x) for x in a.space_layers.split(",")] if a.space_layers else list(layers)
    gbanks = set(a.greedy_banks.split(",")) if a.greedy_banks else {n for n, _ in banks}
    os.makedirs(a.out, exist_ok=True)

    print("  locator   : %s" % a.locator, flush=True)
    print("OPERANDSTATE-v2b start %s tag=%s host=%s layers=%s space_layers=%s max_runs=%d greedy=%d batch=%d/%d on %s"
          % (time.strftime("%F %T"), a.tag, a.host, layers, slayers, a.max_runs, a.greedy, a.batch, gb,
             sorted(gbanks)), flush=True)
    tok = AutoTokenizer.from_pretrained(a.host)
    _dt = {"bf16": torch.bfloat16, "fp32": torch.float32, "fp16": torch.float16}[a.dtype]
    model = AutoModelForCausalLM.from_pretrained(a.host, dtype=_dt, attn_implementation="eager").to(a.device).eval()
    nl, nh = model.config.num_hidden_layers, model.config.num_attention_heads
    assert max(layers) <= nl and max(slayers) <= nl, (layers, slayers, nl)
    print("  host      : layers %d heads %d hidden %d dtype %s" % (nl, nh, model.config.hidden_size, model.dtype), flush=True)
    space_id = tok(" ", add_special_tokens=False)["input_ids"]
    assert len(space_id) == 1, space_id
    space_id = space_id[0]
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    R, d = a.max_runs, model.config.hidden_size

    for name, path in banks:
        rows = load_bank(path)
        if a.max_rows: rows = rows[: a.max_rows]
        do_greedy = a.greedy > 0 and name in gbanks
        skips = {"run_count_mismatch": 0, "too_many_runs": 0, "gold_out_of_range": 0}
        t0 = time.time()

        # ---- pass 0: tokenise and filter on CPU. Identical predicates to v2, in the same order, so the kept set
        # and the skip counters are the same rows and the same numbers.
        work = []
        for r in rows:
            text = r["text"].rstrip()
            direct = bool(text) and text[-1] in "([{-–—/«「（$£€¥－"
            pid = tok(text, add_special_tokens=False)["input_ids"]
            runs = digit_runs(tok, pid)
            pv = r["prov"]; gold = [int(x) for x in pv["gold_run_idx"]]
            if pv.get("n_runs") is not None and int(pv["n_runs"]) != len(runs):
                skips["run_count_mismatch"] += 1; continue
            if len(runs) > R:
                skips["too_many_runs"] += 1; continue
            if any(g < 0 or g >= len(runs) for g in gold):
                skips["gold_out_of_range"] += 1; continue
            ids = list(pid) + ([] if direct else [space_id])
            work.append(dict(r=r, pid=pid, runs=runs, gold=gold, ids=ids, direct=direct, P=len(pid)))
        K = len(work)
        print("  kept %d/%d rows for the forward pass, skips %s" % (K, len(rows), skips), flush=True)

        HL = torch.zeros(K, R, len(layers), d, dtype=torch.float16)
        HM = torch.zeros(K, R, len(layers), d, dtype=torch.float16)
        HS = torch.zeros(K, len(slayers), d, dtype=torch.float16)
        HT = torch.zeros(K, len(slayers), d, dtype=torch.float16)
        AS = torch.zeros(K, R, nl, nh, dtype=torch.float16)
        AT = torch.zeros(K, R, nl, nh, dtype=torch.float16)
        GM = torch.zeros(K, R, dtype=torch.bool); RM = torch.zeros(K, R, dtype=torch.bool)
        metas = [None] * K

        # ---- bucket by length. `order` holds ORIGINAL indices; every write below is to work-index `j`, so the
        # saved tensors come out in bank order no matter how the batches were formed.
        order = sorted(range(K), key=lambda j: len(work[j]["ids"]))
        batches, cur = [], []
        for j in order:
            trial = cur + [j]
            T = max(len(work[i]["ids"]) for i in trial)
            if len(trial) > a.batch or (len(trial) * T * T) / 1000.0 > a.max_batch_tokens:
                if cur: batches.append(cur); cur = [j]
                else: batches.append(trial); cur = []
            else:
                cur = trial
        if cur: batches.append(cur)
        print("  %d forward batches (max %d rows, token lengths %d..%d)"
              % (len(batches), a.batch, len(work[order[0]]["ids"]), len(work[order[-1]]["ids"])), flush=True)

        if a.device.startswith("cuda"): torch.cuda.reset_peak_memory_stats()
        t_fwd0 = time.time()
        with torch.no_grad():
            for bi, bidx in enumerate(batches):
                L = [len(work[j]["ids"]) for j in bidx]
                T = max(max(L), a.pad_to)
                # RIGHT padding: causal masking already hides trailing pads from every real query position, and
                # position_ids = arange is correct for the real prefix of each row.
                inp = torch.full((len(bidx), T), pad_id, dtype=torch.long)
                att_mask = torch.zeros((len(bidx), T), dtype=torch.long)
                for b, j in enumerate(bidx):
                    ids = work[j]["ids"]; inp[b, :len(ids)] = torch.tensor(ids); att_mask[b, :len(ids)] = 1
                inp = inp.to(a.device); att_mask = att_mask.to(a.device)
                out = model(input_ids=inp, attention_mask=att_mask, output_hidden_states=True, output_attentions=True)
                hs, att = out.hidden_states, out.attentions          # att[l]: [B, nh, T, T]
                A_all = torch.stack([att[l] for l in range(nl)])     # [nl, B, nh, T, T]
                for b, j in enumerate(bidx):
                    w = work[j]; P = w["P"]; last = L[b] - 1         # v2's `-1`, made explicit
                    a_space = A_all[:, b, :, last, :].float()        # [nl, nh, T]
                    a_slot = A_all[:, b, :, P - 1, :].float()
                    for k, run in enumerate(w["runs"]):
                        idx = torch.tensor(run, device=a.device)
                        HL[j, k] = torch.stack([hs[Li][b, run[-1]].float() for Li in layers]).half().cpu()
                        HM[j, k] = torch.stack([hs[Li][b, idx].float().mean(0) for Li in layers]).half().cpu()
                        AS[j, k] = a_space[:, :, idx].sum(-1).half().cpu()
                        AT[j, k] = a_slot[:, :, idx].sum(-1).half().cpu()
                        RM[j, k] = True; GM[j, k] = k in w["gold"]
                    HS[j] = torch.stack([hs[Li][b, last].float() for Li in slayers]).half().cpu()
                    HT[j] = torch.stack([hs[Li][b, P - 1].float() for Li in slayers]).half().cpu()
                    r = w["r"]
                    metas[j] = dict(bank=name, row_id=r["row_id"], op=r.get("op"), wild_op=r.get("wild_op"),
                                    slot_mode=r.get("slot_mode"), n_runs=len(w["runs"]),
                                    run_values=[tok.decode([w["pid"][i] for i in run]) for run in w["runs"]],
                                    run_first_pos=[run[0] for run in w["runs"]], gold_run_idx=w["gold"], n_prompt=P,
                                    direct=int(w["direct"]), lang=r.get("lang"), ans=r.get("ans"),
                                    a=r.get("a"), b=r.get("b"))
                del out, hs, att, A_all
                if (bi + 1) % 25 == 0:
                    print("    forward batch %d/%d  %.0fs" % (bi + 1, len(batches), time.time() - t0), flush=True)

        t_fwd = time.time() - t_fwd0
        mem_fwd = (torch.cuda.max_memory_allocated() / 2**30) if a.device.startswith("cuda") else 0.0
        t_greedy = 0.0; mem_greedy = 0.0
        n_greedy_ok = n_greedy_scored = 0
        if do_greedy:
            # LEFT padding here, and only here: generate must continue from the final real token, and it DOES
            # build position_ids from the mask, so RoPE is right. This is the opposite choice from the forward
            # pass above and the reason is written out in the module docstring.
            if a.device.startswith("cuda"): torch.cuda.reset_peak_memory_stats()
            tg = time.time()
            gbatches, cur = [], []
            for j in order:
                cur.append(j)
                if len(cur) >= gb: gbatches.append(cur); cur = []
            if cur: gbatches.append(cur)
            with torch.no_grad():
                for gi_b, bidx in enumerate(gbatches):
                    L = [len(work[j]["ids"]) for j in bidx]; T = max(L)
                    inp = torch.full((len(bidx), T), pad_id, dtype=torch.long)
                    am = torch.zeros((len(bidx), T), dtype=torch.long)
                    for b, j in enumerate(bidx):
                        ids = work[j]["ids"]; inp[b, T - len(ids):] = torch.tensor(ids); am[b, T - len(ids):] = 1
                    gen = model.generate(input_ids=inp.to(a.device), attention_mask=am.to(a.device),
                                         max_new_tokens=a.greedy, do_sample=False, pad_token_id=pad_id)
                    for b, j in enumerate(bidx):
                        raw = tok.decode(gen[b, T:], skip_special_tokens=True)
                        gi = first_int(raw)
                        r = work[j]["r"]
                        try: gold_ans = int(str(r.get("ans")).replace(",", ""))
                        except (TypeError, ValueError): gold_ans = None
                        ok = int(gi is not None and gold_ans is not None and gi == gold_ans)
                        metas[j].update(greedy_raw=raw[:32], greedy_int=gi,
                                        greedy_ok=ok if gold_ans is not None else None)
                        if gold_ans is not None: n_greedy_scored += 1; n_greedy_ok += ok
                    if (gi_b + 1) % 25 == 0:
                        print("    greedy batch %d/%d  %.0fs" % (gi_b + 1, len(gbatches), time.time() - tg), flush=True)

        if do_greedy:
            t_greedy = time.time() - tg
            mem_greedy = (torch.cuda.max_memory_allocated() / 2**30) if a.device.startswith("cuda") else 0.0
        print("TIMING tag=%s bank=%s batch=%d greedy_batch=%d rows=%d fwd_s=%.2f greedy_s=%.2f fwd_peak_GiB=%.2f greedy_peak_GiB=%.2f"
              % (a.tag, name, a.batch, gb, K, t_fwd, t_greedy, mem_fwd, mem_greedy), flush=True)
        torch.save(dict(tag=a.tag, bank=name, host=a.host, layers=layers, space_layers=slayers, n_layers=nl,
                        n_heads=nh, max_runs=R, greedy=a.greedy if do_greedy else 0, meta=metas, skips=skips,
                        batch=a.batch, greedy_batch=gb, dtype=a.dtype, pad_to=a.pad_to,
                        H_run_last=HL, H_run_mean=HM, H_space=HS, H_slot=HT,
                        A_space=AS, A_slot=AT, gold=GM, run_mask=RM),
                   os.path.join(a.out, "%s_%s_operandstate.pt" % (a.tag, name)))
        extra = ("  host greedy right %d/%d" % (n_greedy_ok, n_greedy_scored)) if do_greedy else ""
        print("  %s %s rows=%d kept=%d skips=%s %.0fs bank md5 %s%s"
              % (a.tag, name, len(rows), K, skips, time.time() - t0, file_md5(path), extra), flush=True)
    print("OPERANDSTATE-v2b done %s" % time.strftime("%F %T"), flush=True)


if __name__ == "__main__":
    main()

