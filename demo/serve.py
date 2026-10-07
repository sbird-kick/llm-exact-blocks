"""serve.py -- the def-use live demo with YOUR fitted readers (reader B at three layers, DU-AG, your gate).
NEW CODE: a small stand-alone server around defuse/live.py; the page (demo/index.html) keeps the project demo's layout
and style, with the panels this package can fill (the host's next token and answer, the numbers found, the decision).

    python demo/serve.py --config demo/config.json              # loads the host, then serves on 127.0.0.1:<port>
    python demo/serve.py --config demo/config.json --selftest   # three example prompts through predict(), then exit

The server binds 127.0.0.1 only. From your laptop, forward the port over ssh (RUN_ON_THOR.md, step 9) and open
http://localhost:<port>/ . It loads the host once, before it binds the port, and answers one prompt at a time.
"""
import argparse
import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
from defuse import live as LV          # noqa: E402

EXAMPLES = [
    dict(label="pencils (one step)", prompt="Tom has 12 pencils. He buys 15 more pencils. How many pencils does Tom have now?"),
    dict(label="stickers (two steps)", prompt="Maria had 48 stickers. She gave 9 stickers to each of her 3 friends. How many stickers does Maria have left?"),
    dict(label="price (percent)", prompt="A jacket costs 80 dollars. The store gives a 25 percent discount. How many dollars does the jacket cost after the discount?"),
    dict(label="speed (division)", prompt="A train travels 360 kilometers in 4 hours. How many kilometers does it travel in one hour?"),
    dict(label="no numbers", prompt="What is the capital of France?"),
]
REQUIRED = ("model", "layers", "relabel", "fit_dir", "port")


def load_config(path):
    cfg = json.load(open(path))
    miss = [k for k in REQUIRED if k not in cfg]
    if miss:
        raise SystemExit("REFUSE: config %s lacks %s" % (path, miss))
    for k in ("fit_dir", "gate"):                                     # relative paths are relative to the repo root
        if cfg.get(k) and not os.path.isabs(cfg[k]):
            cfg[k] = os.path.join(REPO, cfg[k])
    cfg.setdefault("bind", "127.0.0.1"); cfg.setdefault("device", "cuda"); cfg.setdefault("locator", "single")
    cfg.setdefault("greedy", 12); cfg.setdefault("gate", None)
    cfg.setdefault("label", cfg["model"].split("/")[-1])
    cfg["relabel"] = {int(k): int(v) for k, v in cfg["relabel"].items()}
    if sorted(cfg["relabel"].values()) != [20, 24, 28] or sorted(cfg["relabel"]) != sorted(int(x) for x in cfg["layers"]):
        raise SystemExit("REFUSE: relabel must map your three real layers %s onto the labels 20 / 24 / 28" % cfg["layers"])
    if cfg["bind"] not in ("127.0.0.1", "localhost"):
        raise SystemExit("REFUSE: the demo binds 127.0.0.1 only; reach it through an ssh port forward")
    return cfg


def memory():
    out = {}
    try:
        for l in open("/proc/self/status"):
            if l.startswith("VmRSS:"):
                out["VmRSS_GiB"] = round(int(l.split()[1]) / 2**20, 2)
        for l in open("/proc/meminfo"):
            if l.startswith("MemAvailable:"):
                out["MemAvailable_GiB"] = round(int(l.split()[1]) / 2**20, 1)
    except OSError:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            out["cuda_allocated_GiB"] = round(torch.cuda.memory_allocated() / 2**30, 2)
    except Exception:
        pass
    return out


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        t0 = time.time()
        host = LV.LiveHost(cfg["model"], cfg["layers"], relabel=cfg["relabel"], device=cfg["device"], locator=cfg["locator"],
                           greedy=cfg["greedy"])
        self.sys = LV.LiveSystem(host, cfg["fit_dir"], cfg["gate"])
        self.load_s = round(time.time() - t0, 1)
        self.lock = threading.Lock()
        self.caveat = ("Readers and gate fitted by you on folds 1-4 of your own dumps of %s (layers %s relabelled 20 / 24 / 28). "
                       "The host's answer is the first number of its %d-token greedy text after the dumper's added space. "
                       "Each digit run is read as one number (a decimal such as 3.5 is two numbers). Display only."
                       % (cfg["label"], "/".join(str(x) for x in cfg["layers"]), cfg["greedy"]))

    def status(self):
        return dict(label=self.cfg["label"], model=self.cfg["model"], loaded=True, load_s=self.load_s, memory=memory(),
                    gate=None if self.sys.gate is None else dict(cut=self.sys.gate["cut"], tau=self.sys.gate["tau"]),
                    files=self.sys.files, caveat=self.caveat)

    def predict(self, body):
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("empty prompt")
        if len(prompt) > 4000:
            raise ValueError("prompt longer than 4000 characters")
        with self.lock:
            out = self.sys.predict(prompt, append_cue=bool(body.get("append_cue", True)))
        out["model"] = self.cfg["label"]
        return out


def make_handler(app):
    page = os.path.join(HERE, "index.html")

    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj, ctype="application/json"):
            data = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if "json" in ctype or "html" in ctype else ""))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            sys.stdout.write("%s %s\n" % (time.strftime("%H:%M:%S"), fmt % args)); sys.stdout.flush()

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                return self._send(200, open(page, "rb").read(), "text/html")
            if self.path == "/api/status":
                return self._send(200, app.status())
            if self.path == "/api/examples":
                return self._send(200, EXAMPLES)
            return self._send(404, dict(error="not found"))

        def do_POST(self):
            if self.path != "/api/predict":
                return self._send(404, dict(error="not found"))
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(n, 1 << 16)) or b"{}")
                return self._send(200, app.predict(body))
            except ValueError as e:
                return self._send(400, dict(error=str(e)))
            except Exception as e:
                traceback.print_exc()
                return self._send(500, dict(error="%s: %s" % (type(e).__name__, e)))
    return H


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--selftest", action="store_true", help="run the example prompts through predict() and exit")
    a = ap.parse_args()
    cfg = load_config(a.config)
    app = App(cfg)
    print("loaded %s in %.1fs; readers %s; gate %s" % (cfg["model"], app.load_s, cfg["fit_dir"], cfg["gate"]), flush=True)
    if a.selftest:
        for ex in EXAMPLES[:3]:
            o = app.predict(dict(prompt=ex["prompt"]))
            print("SELFTEST %s: host %s | L20/24/28 %s | %s | answer %s | %.2fs" % (
                ex["label"], o["record"]["host1"], " / ".join(str(o["programs"][L]) for L in ("20", "24", "28")),
                o["decision"], o["system_answer"], o["time_s"]), flush=True)
        print("SELFTEST memory %s" % json.dumps(memory()), flush=True)
        return
    srv = ThreadingHTTPServer((cfg["bind"], int(cfg["port"])), make_handler(app))
    print("serving on http://%s:%d/  (forward this port from your laptop; Ctrl+C or scancel stops it)" % (cfg["bind"], int(cfg["port"])), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
