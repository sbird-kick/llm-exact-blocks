"""The Thor recipe's files (RUN_ON_THOR.md, sbatch/thor_*.sbatch) and its small helpers. CPU only, no SLURM needed."""
import glob
import json
import os
import re
import shutil

import pytest

from defuse import gate as GT
from defuse import run as RUN
from defuse import wild as W

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = sorted(glob.glob(os.path.join(ROOT, "sbatch", "thor_*.sbatch")))
COMMON = open(os.path.join(ROOT, "sbatch", "thor_common.sh")).read()


def directives(text):
    return dict(m.groups() for m in re.finditer(r"^#SBATCH --([a-z-]+)=(\S+)", text, re.M))


def mem_gb(s):
    return float(s[:-1]) * (1024 if s.endswith("T") else 1) if s[-1] in "GT" else float(s[:-1]) / 1024


def test_every_thor_job_follows_the_thor_rules():
    assert {os.path.basename(p) for p in SB} == {"thor_dump.sbatch", "thor_fit.sbatch", "thor_demo.sbatch", "thor_smoke.sbatch"}
    assert COMMON.count("export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True") == 2      # before and after the venv
    assert "nvidia-smi --query-gpu=timestamp,utilization.gpu" in COMMON
    assert not set(re.findall(r"""(?:^|[\s"'=(])(/[\w./-]+)""", COMMON, re.M)) - {"/dev/null"}
    for p in SB:
        t = open(p).read(); d = directives(t)
        assert "source sbatch/thor_common.sh" in t, p
        assert d["partition"] == "main" and "mem" in d and mem_gb(d["mem"]) <= 16, (p, d)
        assert "time" in d and "output" in d
        gpu = "defuse.dump" in t or "serve.py" in t
        if gpu:
            assert d.get("gres") == "shard:1" and "gpu_sampler" in t, p                       # explicit GPU + sampler
        else:
            assert "gres" not in d, p                                                         # CPU work holds no GPU
        assert not re.search(r"\breboot\b", t), p
        absolute = set(re.findall(r"""(?:^|[\s"'=(])(/[\w./-]+)""", t, re.M)) - {"/dev/null"}
        assert not absolute, (p, absolute)                                                    # no machine-specific paths


def test_smoke_job_is_small():
    d = directives(open(os.path.join(ROOT, "sbatch", "thor_smoke.sbatch")).read())
    assert mem_gb(d["mem"]) <= 16 and d["time"] <= "00:45:00"


def test_rows_file_from_the_shipped_wild_rows(tmp_path):
    out = tmp_path / "rows.jsonl"
    assert W.concat(str(out), per_file=3) == 24
    rows = [json.loads(l) for l in open(out)]
    assert {r["fold"] for r in rows} == {1, 2, 3, 4} and {r["source_set"] for r in rows} == {"asdiv", "mathqa"}
    bad = tmp_path / "wild"
    shutil.copytree(os.path.join(ROOT, "data", "wild"), bad)
    with open(bad / "asdiv" / "fold1.jsonl", "a") as f:
        f.write("\n")
    with pytest.raises(SystemExit):
        W.concat(str(tmp_path / "x.jsonl"), wild=str(bad))


def test_smoke_grid_is_one_setting_and_fit_gate_refuses_thin_data():
    assert len(RUN.SMOKE_GRID["l2"]) == len(RUN.SMOKE_GRID["lr"]) == len(RUN.SMOKE_GRID["epochs"]) == 1
    recs = [dict(row_id="r%d" % i, fold=1 + i % 4, fire=(i < 3), right=True, host1_right=False, steps24=1, n_numerals=2,
                 lp={"20": -1.0, "24": -1.0, "28": -1.0}, nleaves={"20": 2, "24": 2, "28": 2}) for i in range(40)]
    with pytest.raises(SystemExit, match="too few fixed / broken fires"):
        GT.fit_gate(recs, 0.0075)


def test_recipe_document_names_every_step():
    t = open(os.path.join(ROOT, "RUN_ON_THOR.md")).read()
    for s in ("thor_dump.sbatch", "thor_fit.sbatch", "thor_demo.sbatch", "thor_smoke.sbatch", "python -m defuse.wild",
              "--reference", "Qwen/Qwen3-1.7B", "16:20,19:24,22:28", "expandable_segments", "fold 5"):
        assert s in t, s
