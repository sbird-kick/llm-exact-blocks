#!/bin/bash
# The whole recipe on a few rows, in ONE small job: dump -> fit-b (one-setting smoke grid) -> lofo-b -> fit-gate ->
# evaluate (beside the reference) -> live-vs-dump parity check -> the demo (selftest, then serve + two requests + stop).
# It tests the plumbing and measures time and memory; its numbers are not results (8 x PER_FILE rows, smoke grid).
#   sbatch sbatch/thor_smoke.sbatch                 # PER_FILE=25 -> 200 rows
#SBATCH --job-name=defuse-smoke
#SBATCH --partition=main
#SBATCH --gres=shard:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=6G
#SBATCH --time=00:20:00
#SBATCH --output=logs/%x-%j.out
source sbatch/thor_common.sh
D=runs/smoke-${SLURM_JOB_ID:-local}; MAP=16:20,19:24,22:28; MODEL=${MODEL:-Qwen/Qwen3-1.7B}
PORT=${PORT:-$((20000 + ${SLURM_JOB_ID:-0} % 20000))}
mkdir -p "$D"
gpu_sampler
echo "== smoke in $D, $(date '+%F %T')"
python -m defuse.wild --out "$D/rows.jsonl" --per-file "${PER_FILE:-25}"
peak python -m defuse.dump --host "$MODEL" --tag q17 --out "$D" --banks "wild=$D/rows.jsonl" \
    --layers 16,19,22 --max-runs 5 --greedy 12 --batch 8 --locator single
DUMP=$D/q17_wild_operandstate.pt
peak python -m defuse.run fit-b  --rows "$D/rows.jsonl" --dump "$DUMP" --relabel $MAP --out "$D/fitB" --smoke
peak python -m defuse.run lofo-b --rows "$D/rows.jsonl" --dump "$DUMP" --relabel $MAP --fit "$D/fitB" --out "$D/lofo"
GATE=null; GARG=""
if peak python -m defuse.run fit-gate --records "$D/lofo/OOF.jsonl" --tau 0.0075 --out "$D/gate.json"; then
    GATE="\"$D/gate.json\""; GARG="--gate $D/gate.json"
else
    echo "fit-gate refused on the smoke rows (expected when a few hundred rows give too few fires); demo runs ungated"
fi
python -m defuse.evaluate --records "$D/lofo/OOF.jsonl" $GARG --label "Qwen3-1.7B, Thor, SMOKE" \
    --reference data/wild/reference/qwen3-1.7b_h100.json
peak python -m defuse.live check --host "$MODEL" --dump "$DUMP" --rows "$D/rows.jsonl" --layers 16,19,22 \
    --relabel $MAP --fit "$D/fitB" $GARG --n "${CHECK_N:-40}"
cat > "$D/config.json" <<CFG
{"model": "$MODEL", "label": "Qwen3-1.7B (Thor, smoke)", "layers": [16, 19, 22], "relabel": {"16": 20, "19": 24, "22": 28},
 "fit_dir": "$D/fitB", "gate": $GATE, "port": $PORT, "bind": "127.0.0.1"}
CFG
peak python demo/serve.py --config "$D/config.json" --selftest
python demo/serve.py --config "$D/config.json" > "$D/serve.log" 2>&1 & SRV=$!
for i in $(seq 1 120); do curl -s -o /dev/null "http://127.0.0.1:$PORT/api/status" && break; sleep 1; done
curl -s "http://127.0.0.1:$PORT/api/status" | head -c 600; echo
curl -s -X POST -H 'Content-Type: application/json' -d '{"prompt": "Tom has 12 pencils. He buys 15 more pencils. How many pencils does Tom have now?"}' \
    "http://127.0.0.1:$PORT/api/predict" | python -c 'import json,sys; o=json.load(sys.stdin); print("DEMO predict:", o.get("decision"), o.get("system_answer"), o.get("programs"), o.get("why"), o.get("time_s"))'
curl -s "http://127.0.0.1:$PORT/" | grep -c "Def-use live reader" | sed 's/^/DEMO page title lines: /'
kill $SRV; wait $SRV 2>/dev/null || true
echo "== smoke done $(date '+%F %T')"
