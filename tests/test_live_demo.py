"""The live path of the demo (defuse/live.py) and its server (demo/serve.py), without a model: CPU, numpy + pytest.
The parity of live features with a real dump needs the host and a GPU: `python -m defuse.live check` (RUN_ON_THOR.md)."""
import collections
import json
import os
import sys
import threading
import urllib.request

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import test_defuse_cpu as T            # noqa: E402  (the synthetic rows / states)
from defuse import fit_b as FB         # noqa: E402
from defuse import gate as GT          # noqa: E402
from defuse import live as LV          # noqa: E402
from defuse import reader_a as A       # noqa: E402
from defuse import reader_b as B       # noqa: E402
from defuse import run as RUN          # noqa: E402

sys.path.insert(0, os.path.join(HERE, "..", "demo"))
import serve as SV                     # noqa: E402


class CharTok:
    """a stand-in tokenizer: one token per character (so every digit is its own token, as in Qwen3)"""

    def __init__(self):
        self.vocab = {}

    def _id(self, ch):
        return self.vocab.setdefault(ch, len(self.vocab))

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [self._id(c) for c in text]}

    def decode(self, ids):
        inv = {v: k for k, v in self.vocab.items()}
        return "".join(inv[i] for i in ids)


def test_prepare_is_the_dumpers_pass_0():
    tok = CharTok()
    t = LV.with_cue("Tom has 12 pencils and buys 7 more.")
    assert t.endswith("more. The answer is") and LV.with_cue(t) == t and LV.with_cue("x", append_cue=False) == "x"
    p = LV.prepare(tok, t + "  ")
    assert p["text"] == t and p["P"] == len(t) and len(p["ids"]) == len(t) + 1          # one appended space
    assert tok.decode([p["ids"][-1]]) == " " and not p["direct"]
    assert p["run_values"] == ["12", "7"] and [len(r) for r in p["runs"]] == [2, 1]
    q = LV.prepare(tok, "costs $")                                                        # a `direct` ending: no space
    assert q["direct"] and len(q["ids"]) == q["P"]
    row = LV.live_row(p)
    assert row["numerals_written"] == ["12", "7"] and row["prov"]["n_runs"] == 2 and A.align_numerals(row) == [0, 1]


def _models(d, seed=0):
    return {L: B.ReaderB(d, dg=8, de=4, seed=seed + L) for L in A.LAYERS}


def test_live_record_equals_the_scoring_record():
    """the demo's record for a row = fit_b.decode_record's (the scoring path) on every shared field"""
    rows = T.syn_rows(12, seed=5)
    st = T.syn_states(rows, d=16)
    asms = {L: A.assemble(rows, st, list(range(len(rows))), L, 5) for L in A.LAYERS}
    models = _models(16)
    for i, r in enumerate(rows):
        host = dict(host1="7", host1_none=False, host1_right=False)
        want = FB.decode_record(models, asms, i, r, host)
        one = {k: (v[i:i + 1] if hasattr(v, "shape") else v) for k, v in st.items()}
        one["meta"] = [st["meta"][i]]
        got = LV.live_record(models, {L: A.assemble([r], one, [0], L, 5) for L in A.LAYERS}, r, host)
        for k in ("row_id", "n_numerals", "host1", "host1_none", "canon", "lp", "nleaves", "steps24", "value24", "fire"):
            assert got[k] == want[k], (k, got[k], want[k])


def test_gate_score_agrees_with_apply_gate():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(60, 10)); y = (X[:, 0] + 0.3 * rng.normal(size=60) > 0).astype(float)
    gate = dict(side="b", probes=False, model=GT.fit_logit(X, y), cut=0.1, tau=0.0075)
    seen = collections.Counter()
    recs = []
    for i in range(80):
        lp = {L: float(-rng.random() * 3) for L in ("20", "24", "28")}
        recs.append(dict(row_id="r%d" % i, fire=bool(i % 4), n_numerals=int(rng.integers(1, 6)), steps24=int(rng.integers(0, 5)),
                         lp=lp, nleaves={L: int(rng.integers(1, 5)) for L in lp}))
    gate["cut"] = float(np.median([LV.gate_score(x, gate) for x in recs if x["fire"]]))
    for rec in recs:
        sc = LV.gate_score(rec, gate)
        ids = GT.apply_gate([dict(rec)], gate)
        assert (sc is None) == (not rec["fire"])
        if rec["fire"]:
            assert (sc >= gate["cut"]) == (rec["row_id"] in ids)
            seen[sc >= gate["cut"]] += 1
    assert seen[True] and seen[False]


def test_host_fields_on_live_meta():
    assert RUN.host_fields(dict(greedy_raw=" 27 pencils"), dict(gold_frac="0"))["host1"] == "27"
    assert RUN.host_fields(dict(greedy_raw=" twenty"), dict(gold_frac="0"))["host1_none"]


def test_config_validation(tmp_path):
    base = json.load(open(os.path.join(HERE, "..", "demo", "config.example.json")))
    p = tmp_path / "c.json"
    p.write_text(json.dumps(base))
    cfg = SV.load_config(str(p))
    assert cfg["relabel"] == {16: 20, 19: 24, 22: 28} and cfg["bind"] == "127.0.0.1"
    assert cfg["fit_dir"].endswith(os.path.join("runs", "q17", "fitB")) and os.path.isabs(cfg["fit_dir"])
    for bad in (dict(base, relabel={"16": 20, "19": 24, "21": 28}), dict(base, bind="0.0.0.0"),
                {k: v for k, v in base.items() if k != "fit_dir"}):
        p.write_text(json.dumps(bad))
        with pytest.raises(SystemExit):
            SV.load_config(str(p))


class FakeApp:
    cfg = dict(label="fake")

    def status(self):
        return dict(label="fake", loaded=True, memory={}, caveat="c", files={})

    def predict(self, body):
        if not body.get("prompt"):
            raise ValueError("empty prompt")
        return dict(model="fake", decision="ABSTAIN", echo=body["prompt"])


def test_server_routes():
    srv = SV.ThreadingHTTPServer(("127.0.0.1", 0), SV.make_handler(FakeApp()))
    th = threading.Thread(target=srv.serve_forever, daemon=True); th.start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        page = urllib.request.urlopen(base + "/").read().decode()
        assert "/api/predict" in page and "Def-use live reader" in page
        assert json.loads(urllib.request.urlopen(base + "/api/status").read())["loaded"]
        assert len(json.loads(urllib.request.urlopen(base + "/api/examples").read())) >= 3
        req = urllib.request.Request(base + "/api/predict", data=json.dumps(dict(prompt="2 and 3")).encode(),
                                     headers={"Content-Type": "application/json"})
        assert json.loads(urllib.request.urlopen(req).read())["echo"] == "2 and 3"
        bad = urllib.request.Request(base + "/api/predict", data=b"{}", headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(bad)
        assert e.value.code == 400
    finally:
        srv.shutdown()
