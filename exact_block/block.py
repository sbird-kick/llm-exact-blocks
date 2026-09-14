"""THE BLOCK. ~0.1 M trainable parameters bolted onto a FROZEN Qwen3 by forward hooks.

Three attach points on the host's decoder stack, and the order matters:

    READ   layer  8 (of 28)   stash h. The digit probe and the span tagger read it, and
                              so does the gate's gain. Digit identity is linearly
                              available EARLY.
    ROUTE  layer 16           stash h. Only the router reads it: what the sentence is
                              ASKING linearises later than what its digits ARE.
    WRITE  layer 24           add gate * gain * delta at the answer positions. Layers
                              25-27 then read the digits out through the frozen LM head.

Everything the block owns:

    probe      Linear(d, 10)   one head shared across every place and both operands
    span       Linear(d, 3)    per token: none / A-digit / B-digit
    control    Linear(d, 4)    add / sub / mul / off, with a +2.0 bias prior on `off`
    route_q    (d,)            zero-init attention query, pools the prompt for the router
    write      Linear(10, d)   digit distribution -> residual vector, NO BIAS (see below)
    gate       (1,)            zero-init scalar: at step 0 the model is BITWISE unchanged
    gate_head  Linear(d, 1)    zero-init, per-example gain g = gate * (1 + gate_head(h_P))

WHY `write` HAS NO BIAS. Abstention has to scale the WHOLE message. With a bias,
write(R) = R @ W.T + bias and the bias does not depend on R, so multiplying by mass=0
would still leave `bias` injected at every answer position, gated only by `gate`. The
deployed block normalises the mixture to work around that; here the bias is simply not
there, which is the same guarantee with one fewer moving part.

WHY THE GAIN IS MULTIPLICATIVE. `gate = 0` must make the block inert EVERYWHERE, with no
call-site changes, because every "frozen host" baseline in eval.py is produced by zeroing
exactly that one scalar. gate * (1 + head(h)) is zero whenever gate is; gate + head(h) is
not, and the baseline would silently stop being the baseline.
"""
from __future__ import annotations

import torch
import torch.nn as nn

from . import numerals
from .calc import OPS, Calc

SPAN_CLASSES = 3          # 0 = none, 1 = A digit, 2 = B digit


class CalcBlock(nn.Module):
    def __init__(self, d_model: int, dmax: int = 16, ops=OPS, off_bias: float = 2.0):
        super().__init__()
        self.dmax = int(dmax)
        self.ops = tuple(ops)
        self.calc = Calc(dmax=self.dmax, ops=self.ops)
        self.n_ops = len(self.ops)
        self.off_index = self.n_ops

        self.probe = nn.Linear(d_model, 10)
        self.span = nn.Linear(d_model, SPAN_CLASSES)
        self.control = nn.Linear(d_model, self.n_ops + 1)
        self.route_q = nn.Parameter(torch.zeros(d_model))
        self.write = nn.Linear(10, d_model, bias=False)
        self.gate = nn.Parameter(torch.zeros(1))
        self.gate_head = nn.Linear(d_model, 1)
        with torch.no_grad():
            self.control.bias.zero_()
            self.control.bias[self.off_index] = off_bias   # "do not fire without reason"
            self.gate_head.weight.zero_()
            self.gate_head.bias.zero_()

        # Deployment switches. Plain attributes, never in state_dict: they are policy, and
        # a checkpoint must not carry one run's policy into another.
        self.learned_spans = False   # True: locate operands with the tagger, not the batch
        self.ctx = None              # set per batch by build_batch
        self.last = {}               # per-forward diagnostics, read by train.py / eval.py
        self.handles = []
        self._h_read = None
        self._pending = None
        self._gain = None

    # ------------------------------------------------------------------ reading digits
    def read_operand(self, h: torch.Tensor, pos: torch.Tensor):
        """h (B, T, d), pos (B, dmax) LSD-first token positions, -1 = no such place.

        Returns ((B, dmax, 10) distributions, (B, dmax, 10) logits). A -1 lane is forced
        to a HARD one-hot zero, which is exact: a leading zero changes no sum and no
        partial product, so short operands need no separate code path.
        """
        B, T, d = h.shape
        D = pos.shape[1]
        gathered = h.gather(1, pos.clamp_min(0).unsqueeze(-1).expand(B, D, d))
        logits = self.probe(gathered.float())
        dist = torch.softmax(logits, -1)
        zero = torch.zeros_like(dist)
        zero[..., 0] = 1.0
        return torch.where((pos >= 0).unsqueeze(-1), dist, zero), logits

    # ------------------------------------------------------------------ the whole block
    def compute(self, h_read: torch.Tensor, h_route: torch.Tensor):
        """The ungated residual delta for one forward pass, (B, T, d) fp32, or None."""
        if self.ctx is None:
            return None
        ctx = self.ctx
        a_pos, b_pos, w_pos = ctx["a_pos"], ctx["b_pos"], ctx["w_pos"]
        ctl_pos, p0 = ctx["ctl_pos"], ctx["p0"]
        assert a_pos.shape[1] == self.dmax and w_pos.shape[1] == 2 * self.dmax, (
            f"this block has dmax={self.dmax} (operand lanes {self.dmax}, answer lanes "
            f"{2 * self.dmax}) but the batch carries {a_pos.shape[1]}/{w_pos.shape[1]}. "
            f"build_batch must be passed the same dmax the block was built with.")
        B, T, d = h_read.shape

        # --- the span tagger, over every position. Graph kept: train.py's span CE runs on
        # this tensor, and a loss on a detached tensor trains nothing, silently.
        span_logits = self.span(h_read.float())
        span_fail = torch.zeros(B, device=h_read.device)
        if self.learned_spans:
            a_pos, b_pos, span_fail = spans_from_logits(span_logits, p0, self.dmax)
            a_pos, b_pos = a_pos.to(h_read.device), b_pos.to(h_read.device)
            span_fail = span_fail.to(h_read.device)

        # --- the digit probe, at the operand lanes
        A, a_logits = self.read_operand(h_read, a_pos)
        Bo, b_logits = self.read_operand(h_read, b_pos)

        # --- the gain reads the CONTROL position: the place that decides whether to fire
        # is the natural place to decide how hard to fire.
        h_ctl = h_read.gather(1, ctl_pos.view(B, 1, 1).expand(B, 1, d)).squeeze(1).float()
        self._gain = (1.0 + self.gate_head(h_ctl).squeeze(-1)).view(-1, 1, 1)

        # --- the router, attention-pooled over the PROMPT of the route layer.
        # The mask is `positions <= ctl_pos`, and it is load-bearing: one position further
        # is the answer itself, and a router that reads the answer does not crash, it
        # returns a spectacular number that means nothing.
        hs = h_route.float()
        pm = torch.arange(T, device=hs.device).view(1, T) <= ctl_pos.view(-1, 1)
        scores = (hs @ self.route_q.float()) / (d ** 0.5)
        w = torch.softmax(scores.masked_fill(~pm, float("-inf")), -1)
        ctl_logits = self.control((w.unsqueeze(-1) * hs).sum(1))

        # --- how much of the message survives. STRAIGHT-THROUGH: an exact 0/1 decision in
        # the forward pass (so `off` means EXACTLY nothing written, not 1 - p_off of
        # something) with a soft backward pass (so the router is still trainable; a plain
        # argmax has no grad_fn and every routing loss would be silently dead).
        soft = torch.softmax(ctl_logits, -1)[:, :self.n_ops].sum(-1)
        hard = (ctl_logits.argmax(-1) < self.n_ops).to(soft.dtype)
        mass = soft + (hard - soft).detach()

        # --- the calculator
        op_index = ctl_logits[:, :self.n_ops].argmax(-1)
        R, refused = self.calc(A, Bo, op_index)
        mass = mass * (1.0 - span_fail) * (1.0 - refused)

        # --- the write. `write` is bias-free, so this multiplication IS exact attenuation.
        delta = self.write(R) * mass.view(-1, 1, 1)            # (B, 2*dmax, d)
        out = torch.zeros(B, T, d, device=h_read.device, dtype=torch.float32)
        live = (w_pos >= 0).unsqueeze(-1)
        out.scatter_add_(1, w_pos.clamp_min(0).unsqueeze(-1).expand_as(delta),
                         delta * live)

        self.last = {
            "A": A.detach(), "B": Bo.detach(), "R": R.detach(),
            "a_logits": a_logits, "b_logits": b_logits,
            "span_logits": span_logits,
            # ctl_logits keeps its graph -- the route CE trains through it. Anything that
            # only REPORTS reads the detached copies.
            "ctl_logits": ctl_logits,
            "control": ctl_logits.detach(),
            "op_index": op_index.detach(),
            "mass": mass.detach(),
            "span_fail": span_fail.detach(),
            "calc_refused": refused.detach(),
            "a_pos": a_pos.detach(), "b_pos": b_pos.detach(),
            "gain": self._gain.detach().view(-1),
        }
        return out

    # ------------------------------------------------------------------------- the hooks
    def attach(self, model, read_layer: int, route_layer: int, write_layer: int):
        """Register the three forward hooks on a HF causal LM. Returns the handles."""
        layers = model.model.layers
        assert 0 <= read_layer < route_layer < write_layer < len(layers), (
            f"need read < route < write, all inside a {len(layers)}-layer host; got "
            f"{read_layer}/{route_layer}/{write_layer}. The delta is built at the route "
            f"hook from the read layer's tensor and applied at the write hook.")
        blk = self
        self.remove()
        blk._h_read = blk._pending = None

        def read_hook(mod, inp, out):
            h = out[0] if isinstance(out, tuple) else out
            # Every per-forward reset lives at the hook guaranteed to fire first, so a
            # forward that dies mid-stack cannot leave the next one reading stale state.
            blk._h_read, blk._pending = h, None
            return out

        def route_hook(mod, inp, out):
            h = out[0] if isinstance(out, tuple) else out
            if blk._h_read is None:
                blk._pending = None
                return out
            blk._pending = blk.compute(blk._h_read, h)
            blk._h_read = None
            return out

        def write_hook(mod, inp, out):
            h = out[0] if isinstance(out, tuple) else out
            if blk._pending is None:
                return out
            h = h + (blk.gate * blk._gain * blk._pending).to(h.dtype)
            return (h,) + tuple(out[1:]) if isinstance(out, tuple) else h

        self.handles = [
            layers[read_layer].register_forward_hook(read_hook),
            layers[route_layer].register_forward_hook(route_hook),
            layers[write_layer].register_forward_hook(write_hook),
        ]
        return self.handles

    def remove(self):
        for h in self.handles:
            h.remove()
        self.handles = []


# ---------------------------------------------------------------- the deployed locator
def spans_from_logits(span_logits: torch.Tensor, p0: torch.Tensor, dmax: int):
    """Tagger argmax -> LSD-first operand positions. The longest run of each class wins.

    Only the PROMPT region (positions < p0) is read: padding sits after the answer, so
    `< p0` is always real prompt and the tagger can never point at the answer it is
    supposed to help write. A row missing EITHER run FAILS (fail = 1.0) and the caller
    must abstain on it -- firing on invented positions injects garbage silently.

    Returns CPU tensors: (B, dmax) a_pos, (B, dmax) b_pos, (B,) fail.
    """
    tags = span_logits.detach().argmax(-1).cpu()
    p0c = p0.detach().cpu()
    B = tags.shape[0]
    a_out = torch.full((B, dmax), -1, dtype=torch.long)
    b_out = torch.full((B, dmax), -1, dtype=torch.long)
    fail = torch.zeros(B)
    for i in range(B):
        t = tags[i, :int(p0c[i])].tolist()
        runs = {}
        for cls in (1, 2):
            best, cur = [], []
            for j, v in enumerate(t):
                if v == cls:
                    cur.append(j)
                else:
                    if len(cur) > len(best):
                        best = cur
                    cur = []
            runs[cls] = cur if len(cur) > len(best) else best
        if not runs[1] or not runs[2]:
            fail[i] = 1.0
            continue
        for out, cls in ((a_out, 1), (b_out, 2)):
            for k, j in enumerate(reversed(runs[cls][-dmax:])):
                out[i, k] = j
    return a_out, b_out, fail


# -------------------------------------------------------------------------- the batcher
def build_batch(tok, problems, dmax: int = 16, device: str = "cpu", ops=OPS):
    """Tokenise, locate every operand digit, and compute every position the block needs.

    Returns (input_ids, attention_mask, ctx). The ctx is what CalcBlock.compute reads:

        a_pos, b_pos   (B, dmax)    LSD-first operand token positions, -1 = no such place
        w_pos          (B, 2*dmax)  where each result place is WRITTEN. Note the -1 in
                                    `P + adig[...] - 1`: the block writes at the position
                                    whose hidden state PREDICTS the digit, which is the
                                    token before it.
        w_tok          (B, 2*dmax)  the gold digit token id at each answer position,
                                    -100 where there is no lane. This is the LM target.
        ctl_pos        (B,)         the last prompt token = the answer slot P
        p0             (B,)         len(prompt), i.e. where the prompt stops
        span_labels    (B, T)       0 none / 1 A / 2 B, -100 = ignore (padding, and every
                                    position of an `off` row: see data.py)
        op_label       (B,)         index into block.ops, or n_ops for `off`
        a_dig, b_dig   (B, dmax)    gold digits per lane, -100 where there is no lane

    The located runs are ASSERTED to decode back to the operands. A silent mislocation
    here looks exactly like a block that will not learn.
    """
    ops = tuple(ops)
    rows = []
    for p in problems:
        op_label = len(ops) if p.op == "off" else ops.index(p.op)
        pid = tok(p.prompt, add_special_tokens=False)["input_ids"]
        cid = (tok(p.completion, add_special_tokens=False)["input_ids"]
               if p.completion else [])
        runs = numerals.digit_runs(tok, pid)
        assert len(runs) == len(p.roles), (
            f"the locator found {len(runs)} number runs but the template rendered "
            f"{len(p.roles)} numbers: {p.prompt!r}")
        a_run = b_run = None
        for run, role in zip(runs, p.roles):
            if role == "a":
                a_run = run
            elif role == "b":
                b_run = run
        assert (a_run is None) == (b_run is None)
        span = [0] * len(pid)
        if a_run is not None:
            assert numerals.run_value(tok, pid, a_run) == p.a, p.prompt
            assert numerals.run_value(tok, pid, b_run) == p.b, p.prompt
            a_pos = numerals.lanes_lsd(a_run, dmax)
            b_pos = numerals.lanes_lsd(b_run, dmax)
            for j in a_run:
                span[j] = 1
            for j in b_run:
                span[j] = 2
            a_dig = numerals.digits_lsd(p.a, dmax)
            b_dig = numerals.digits_lsd(p.b, dmax)
            for k in range(dmax):                       # no lane -> no digit target
                if a_pos[k] < 0:
                    a_dig[k] = -100
                if b_pos[k] < 0:
                    b_dig[k] = -100
        else:                                            # an `off` row: nothing to locate
            a_pos = b_pos = [-1] * dmax
            a_dig = b_dig = [-100] * dmax
            span = [-100] * len(pid)

        P = len(pid)
        adig = [i for i in range(len(cid)) if numerals.is_digit_token(tok, cid[i])]
        w_pos, w_tok = [-1] * (2 * dmax), [-100] * (2 * dmax)
        if adig:
            n = len(adig)
            assert n == len(str(p.ans)), (
                f"the completion {p.completion!r} tokenised to {n} digit tokens but the "
                f"answer {p.ans} has {len(str(p.ans))} digits")
            assert n <= 2 * dmax, (
                f"a {n}-digit answer does not fit {2 * dmax} answer lanes")
            for k in range(n):
                w_pos[k] = P + adig[n - 1 - k] - 1       # LSD-first, predictor position
                w_tok[k] = cid[adig[n - 1 - k]]
        rows.append(dict(ids=pid + cid, span=span, a_pos=a_pos, b_pos=b_pos,
                         a_dig=a_dig, b_dig=b_dig, w_pos=w_pos, w_tok=w_tok,
                         ctl_pos=len(pid) - 1, p0=len(pid), op=op_label))

    T = max(len(r["ids"]) for r in rows)
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else 0
    L = torch.long

    def stack(key, dtype=L):
        return torch.tensor([r[key] for r in rows], dtype=dtype, device=device)

    input_ids = torch.tensor([r["ids"] + [pad_id] * (T - len(r["ids"])) for r in rows],
                             dtype=L, device=device)
    attn = torch.tensor([[1] * len(r["ids"]) + [0] * (T - len(r["ids"])) for r in rows],
                        dtype=L, device=device)
    span_labels = torch.tensor(
        [r["span"] + [-100] * (T - len(r["span"])) for r in rows], dtype=L, device=device)
    ctx = dict(a_pos=stack("a_pos"), b_pos=stack("b_pos"),
               a_dig=stack("a_dig"), b_dig=stack("b_dig"),
               w_pos=stack("w_pos"), w_tok=stack("w_tok"),
               ctl_pos=stack("ctl_pos"), p0=stack("p0"),
               op_label=stack("op"), span_labels=span_labels)
    return input_ids, attn, ctx
