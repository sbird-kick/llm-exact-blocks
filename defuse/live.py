"""live.py -- one prompt through the host and the fitted readers, the same way the dump and the scoring path see it.
NEW CODE (written for the students' demo; it adds no modelling).

    host = LiveHost("Qwen/Qwen3-1.7B", layers=[16, 19, 22], relabel={16: 20, 19: 24, 22: 28})
    sys_ = LiveSystem(host, fit_dir="runs/fitB", gate_path="runs/gate.json")
    out = sys_.predict("Tom has 12 pencils and buys 15 more. How many pencils does he have?")

Parity with the dump. `prepare` repeats the dumper's pass 0 (defuse/dump.py: `text.rstrip()`, the `direct` character set,
the digit-run locator, one appended space token unless the text ends in a `direct` character) and `features` repeats
its per-row extraction for a batch of one (H_run_last = the state at the last token of each run, H_space = the state at
the answer position, H_slot = the last prompt token, A_space = the attention mass from the answer position onto each
run, every layer and head, all rounded to float16 as the dump stores them; the greedy answer = `--greedy` new tokens,
kept as its first 32 characters, as the dump keeps it). The readers then run on a one-row dump through the SAME
functions the scoring path uses (`reader_a.assemble`, `reader_b.row_inputs` / `best_program`, `reader_a.du_ag`,
`run.host_fields`, `gate.apply_gate`). `python -m defuse.live check ...` measures the parity on rows you dumped:
live features against the dump's tensors, and the programs and decisions read from both.

A live prompt has no gold equation, so its row is built from the prompt itself: each digit run is one written number
(the project's demo did the same). A decimal such as 3.5 is therefore read as the two numbers 3 and 5.
"""
import argparse
import json
import os
import time
from fractions import Fraction

import numpy as np

from . import data as D
from . import dump as DU
from . import fit_b as FB
from . import gate as GT
from . import guard as G
from . import reader_a as A
from . import reader_b as B
from . import run as RUN

CUE = "The answer is"
DIRECT = "([{-–—/«「（$£€¥－"                       # the dumper's `direct` set (dump.py, pass 0)
R = 5                                                # the dump's --max-runs for the def-use readers


def with_cue(text, append_cue=True):
    t = text.rstrip()
    if append_cue and not t.endswith(CUE):
        t = t + " " + CUE
    return t


def prepare(tok, text, locator="single"):
    """the dumper's pass 0 for one prompt: the token ids fed to the host, the digit runs, the prompt length"""
    digit_runs = DU.digit_runs_single if locator == "single" else DU.digit_runs_grouped
    text = text.rstrip()
    direct = bool(text) and text[-1] in DIRECT
    space_id = tok(" ", add_special_tokens=False)["input_ids"]
    assert len(space_id) == 1, space_id
    pid = tok(text, add_special_tokens=False)["input_ids"]
    runs = digit_runs(tok, pid)
    ids = list(pid) + ([] if direct else [space_id[0]])
    return dict(text=text, pid=pid, runs=runs, ids=ids, direct=direct, P=len(pid),
                run_values=[tok.decode([pid[i] for i in run]) for run in runs])


def live_row(prep, row_id="live"):
    """a prompt as the row dict the readers read: each digit run is one written number"""
    rv = [str(v).strip() for v in prep["run_values"]]
    return dict(row_id=row_id, text=prep["text"], numerals_written=list(rv), status="scored",
                prov=dict(n_runs=len(rv), run_values=list(rv), gold_run_idx=[]))


def live_record(models, asms, row, host):
    """fit_b.decode_record for a row without a gold answer: the same fields, minus the gold ones"""
    bprog, lp = {}, {}
    for L in A.LAYERS:
        q, h, valid, rv = B.row_inputs(asms[L], 0)
        bprog[L], lp[L] = B.best_program(models[L], q, h, valid, rv, beam=FB.B_GRID["beam"])
    du = A.du_ag(bprog, host["host1"], host["host1_none"], A.numeral_values(row))
    return dict(row_id=row["row_id"], fold=None, n_numerals=len(row.get("numerals_written") or []),
                host1=host["host1"], host1_none=bool(host["host1_none"]),
                canon={str(L): (A.canon(bprog[L]) if bprog[L] is not None else None) for L in A.LAYERS},
                lp={str(L): (None if bprog[L] is None else round(float(lp[L]), 6)) for L in A.LAYERS},
                nleaves={str(L): (len(A.leaves_of(bprog[L])) if bprog[L] is not None else None) for L in A.LAYERS},
                steps24=(A.n_steps(bprog[24]) if bprog[24] is not None else None),
                value24=(str(A.execute(bprog[24])) if bprog[24] is not None else None), fire=bool(du["fire"]),
                du_reason=du["reason"], host_class=du.get("host_class"), du_value=(None if du.get("v") is None else str(du["v"])),
                _progs=bprog)


def gate_score(rec, gate):
    """the gate's score for one record (None if DU-AG did not fire): apply_gate's own steps, kept for display"""
    if gate is None or not rec["fire"]:
        return None
    x = dict(rec)
    GT._prep(x, gate["side"], None)
    return float(GT.score_logit(gate["model"], [GT._feats(x, gate["side"], None)])[0])


class LiveHost:
    """the host model, loaded once (bf16, eager attention: the attention mass needs it)"""

    def __init__(self, model, layers, space_layers=None, relabel=None, device="cuda", locator="single", greedy=12,
                 dtype="bf16"):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        self.name, self.device, self.locator, self.greedy = model, device, locator, greedy
        self.layers = [int(x) for x in layers]
        self.space_layers = [int(x) for x in (space_layers or layers)]
        self.relabel = {int(k): int(v) for k, v in (relabel or {}).items()}
        self.tok = AutoTokenizer.from_pretrained(model)
        dt = {"bf16": torch.bfloat16, "fp32": torch.float32, "fp16": torch.float16}[dtype]
        self.model = AutoModelForCausalLM.from_pretrained(model, dtype=dt, attn_implementation="eager").to(device).eval()
        self.nl, self.nh = self.model.config.num_hidden_layers, self.model.config.num_attention_heads
        self.d = self.model.config.hidden_size
        self.pad_id = self.tok.pad_token_id if self.tok.pad_token_id is not None else self.tok.eos_token_id

    def features(self, prep, topk=10):
        """the dump's tensors for one prompt, as a one-row dump dict (relabelled if a map was given), + display extras"""
        torch = self.torch
        runs, ids, P = prep["runs"], prep["ids"], prep["P"]
        if len(runs) > R:
            raise ValueError("the prompt has %d numbers; the readers see at most %d" % (len(runs), R))
        nL, nS = len(self.layers), len(self.space_layers)
        HL = torch.zeros(1, R, nL, self.d, dtype=torch.float16); HS = torch.zeros(1, nS, self.d, dtype=torch.float16)
        HT = torch.zeros(1, nS, self.d, dtype=torch.float16); AS = torch.zeros(1, R, self.nl, self.nh, dtype=torch.float16)
        RM = torch.zeros(1, R, dtype=torch.bool)
        with torch.no_grad():
            inp = torch.tensor([ids], device=self.device)
            out = self.model(input_ids=inp, attention_mask=torch.ones_like(inp), output_hidden_states=True,
                             output_attentions=True)
            hs, att = out.hidden_states, out.attentions
            A_all = torch.stack([att[l] for l in range(self.nl)])
            last = len(ids) - 1
            a_space = A_all[:, 0, :, last, :].float()
            for k, run in enumerate(runs):
                idx = torch.tensor(run, device=self.device)
                HL[0, k] = torch.stack([hs[Li][0, run[-1]].float() for Li in self.layers]).half().cpu()
                AS[0, k] = a_space[:, :, idx].sum(-1).half().cpu()
                RM[0, k] = True
            HS[0] = torch.stack([hs[Li][0, last].float() for Li in self.space_layers]).half().cpu()
            HT[0] = torch.stack([hs[Li][0, P - 1].float() for Li in self.space_layers]).half().cpu()
            pr = torch.softmax(out.logits[0, last].float(), -1)
            tp, ti = torch.topk(pr, topk)
            top = [dict(token=self.tok.decode([int(i)]), p=float(p)) for p, i in zip(tp.tolist(), ti.tolist())]
            del out, hs, att, A_all
            raw = ""
            if self.greedy:
                gen = self.model.generate(input_ids=inp, attention_mask=torch.ones_like(inp), max_new_tokens=self.greedy,
                                          do_sample=False, pad_token_id=self.pad_id)
                raw = self.tok.decode(gen[0, len(ids):], skip_special_tokens=True)
        meta = dict(row_id="live", n_runs=len(runs), run_values=prep["run_values"], greedy_raw=raw[:32],
                    greedy_int=DU.first_int(raw))
        st = dict(meta=[meta], layers=list(self.layers), space_layers=list(self.space_layers), H_run_last=HL.numpy(),
                  H_space=HS.numpy(), H_slot=HT.numpy(), A_space=AS.numpy(), run_mask=RM.numpy())
        if self.relabel:
            D.relabel_layers(st, self.relabel)
        return st, dict(topk=top, greedy_full=raw)


class LiveSystem:
    """the fitted readers (+ gate) on top of a LiveHost"""

    def __init__(self, host, fit_dir, gate_path=None):
        self.host = host
        self.models = {L: B.ReaderB.from_state(np.load(os.path.join(fit_dir, "READERB_L%d.npz" % L))) for L in A.LAYERS}
        self.files = {"READERB_L%d.npz" % L: G.md5f(os.path.join(fit_dir, "READERB_L%d.npz" % L)) for L in A.LAYERS}
        self.gate = None
        if gate_path:
            self.gate = json.load(open(gate_path))
            if self.gate.get("probes"):
                raise SystemExit("REFUSE: this gate was fitted with host-outcome probe scores; the live demo supports the "
                                 "no-probe gate (run.py fit-gate without --probes)")
            self.files[os.path.basename(gate_path)] = G.md5f(gate_path)

    def decide(self, st, row):
        asms = {L: A.assemble([row], st, [0], L, R) for L in A.LAYERS}
        host = RUN.host_fields(st["meta"][0], dict(row, gold_frac="0"))
        rec = live_record(self.models, asms, row, host)
        sc = gate_score(rec, self.gate)
        fire = rec["fire"] and (self.gate is None or (sc is not None and sc >= self.gate["cut"]))
        return rec, sc, fire

    def predict(self, prompt, append_cue=True):
        t0 = time.time()
        prep = prepare(self.host.tok, with_cue(prompt, append_cue), self.host.locator)
        row = live_row(prep)
        st, extra = self.host.features(prep)
        rec, sc, fire = self.decide(st, row)
        progs = rec.pop("_progs")
        return dict(prompt=prep["text"], tokens=[self.host.tok.decode([t]) for t in prep["ids"]], runs=prep["runs"],
                    numerals=[dict(i=k, text=v, token_pos=prep["runs"][k]) for k, v in enumerate(row["numerals_written"])],
                    host=dict(greedy_text=extra["greedy_full"], host1=rec["host1"], host1_none=rec["host1_none"],
                              topk=extra["topk"]),
                    record=rec, programs={str(L): (None if progs[L] is None else infix(progs[L])) for L in A.LAYERS},
                    layers_agree=(len(set(rec["canon"].values())) == 1 and None not in rec["canon"].values()),
                    gate=None if self.gate is None else dict(cut=self.gate["cut"], tau=self.gate["tau"], score=sc),
                    decision="FIRE" if fire else "ABSTAIN",
                    system_answer=(rec["du_value"] if fire else rec["host1"]),
                    why=why(rec, sc, self.gate, fire), files=self.files, time_s=round(time.time() - t0, 3))


def why(rec, sc, gate, fire):
    if fire:
        return ("FIRE: the three layers read the same program, the host's answer is %s%s"
                % (rec["host_class"], "" if gate is None else ", gate score %.3f >= cut %.3f" % (sc, gate["cut"])))
    if rec["fire"]:
        return "ABSTAIN: DU-AG would fire (host %s) but the gate score %.3f < cut %.3f" % (rec["host_class"], sc, gate["cut"])
    return "ABSTAIN: %s" % rec["du_reason"]


def infix(t):
    k = t[0]
    if k in ("n", "c"):
        v = Fraction(t[2])
        return str(v.numerator) if v.denominator == 1 else "%d/%d" % (v.numerator, v.denominator)
    if k == "u":
        return ("%s%%" % infix(t[2])) if t[1] == "pct" else "-(%s)" % infix(t[2])
    return "(%s %s %s)" % (infix(t[2]), {"add": "+", "sub": "-", "mul": "x", "div": "/"}[t[1]], infix(t[3]))


# ------------------------------------------------------------------ parity check against a dump
def check(a):
    """live features vs the dump's tensors on the first --n rows of a dump; programs and decisions read from both"""
    rel = RUN._relabel(a.relabel) if a.relabel else None
    host = LiveHost(a.host, [int(x) for x in a.layers.split(",")], relabel=rel, device=a.device, locator=a.locator,
                    greedy=a.greedy)
    sysm = LiveSystem(host, a.fit, a.gate)
    st = D.load_dump(a.dump)
    if rel:
        D.relabel_layers(st, rel)
    by = {r["row_id"]: r for r in D.load_rows(a.rows, fit=True)}
    c = dict(rows=0, run_values=0, greedy=0, programs3=0, fire=0, decision=0)
    dmax = dict(H_run_last=0.0, H_space=0.0, A_space=0.0)
    for j, m in enumerate(st["meta"][:a.n]):
        r = by[m["row_id"]]
        prep = prepare(host.tok, r["text"], host.locator)
        lst, _ = host.features(prep)
        c["rows"] += 1
        c["run_values"] += [v.strip() for v in prep["run_values"]] == [str(v).strip() for v in m["run_values"]]
        c["greedy"] += lst["meta"][0]["greedy_raw"] == m.get("greedy_raw")
        one = dict(meta=[m], layers=st["layers"], space_layers=st["space_layers"])
        for k in ("H_run_last", "H_space", "A_space", "run_mask"):
            one[k] = A._np(A._take(st[k], [j])) if k != "run_mask" else np.asarray(A._take(st[k], [j]))
        for k in dmax:
            dmax[k] = max(dmax[k], float(np.abs(A._np(lst[k]) - one[k]).max()))
        row = dict(r, row_id="live")
        rec_d, sc_d, f_d = sysm.decide(dict(one, meta=[dict(m, row_id="live")]), row)
        rec_l, sc_l, f_l = sysm.decide(lst, row)
        c["programs3"] += rec_d["canon"] == rec_l["canon"]
        c["fire"] += rec_d["fire"] == rec_l["fire"]
        c["decision"] += f_d == f_l
    n = c["rows"]
    print("live vs dump on %d rows (%s): run values %s, greedy text %s, B programs at all 3 layers %s, DU-AG fire %s, "
          "final decision %s; max |diff| %s" % (n, a.dump, A.nt(c["run_values"], n), A.nt(c["greedy"], n),
                                                A.nt(c["programs3"], n), A.nt(c["fire"], n), A.nt(c["decision"], n),
                                                json.dumps({k: round(v, 5) for k, v in dmax.items()})))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("check", help="live features vs a dump you made (parity check for the demo)")
    p.add_argument("--host", required=True); p.add_argument("--dump", required=True); p.add_argument("--rows", required=True)
    p.add_argument("--layers", required=True, help="the real layers the dump used, e.g. 16,19,22")
    p.add_argument("--relabel", default="", help="real:label pairs, e.g. 16:20,19:24,22:28")
    p.add_argument("--fit", required=True); p.add_argument("--gate", default=None)
    p.add_argument("--n", type=int, default=50); p.add_argument("--device", default="cuda")
    p.add_argument("--locator", default="single", choices=["single", "grouped"]); p.add_argument("--greedy", type=int, default=12)
    a = ap.parse_args()
    check(a)


if __name__ == "__main__":
    main()
