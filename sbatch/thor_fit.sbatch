#!/bin/bash
# CPU, no GPU: reader B on folds 1-4 (fit-b), its leave-one-fold-out decodes (lofo-b), the gate (fit-gate), the tables.
#   sbatch sbatch/thor_fit.sbatch runs/q17
# Reads runs/q17/rows.jsonl and runs/q17/q17_wild_operandstate.pt; writes runs/q17/{fitB,lofo,gate.json,RESULTS.md}.
#SBATCH --job-name=defuse-fit
#SBATCH --partition=main
#SBATCH --cpus-per-task=2
#SBATCH --mem=10G
#SBATCH --time=06:00:00
#SBATCH --output=logs/%x-%j.out
source sbatch/thor_common.sh
D=${1:?run folder}
ROWS=$D/rows.jsonl; DUMP=$D/q17_wild_operandstate.pt; MAP=16:20,19:24,22:28
LABEL=${LABEL:-"Qwen3-1.7B, Thor"}
[ -s "$D/fitB/READERB_L28.npz" ] || peak python -m defuse.run fit-b  --rows "$ROWS" --dump "$DUMP" --relabel $MAP --out "$D/fitB"
[ -s "$D/lofo/OOF.jsonl" ]       || peak python -m defuse.run lofo-b --rows "$ROWS" --dump "$DUMP" --relabel $MAP --fit "$D/fitB" --out "$D/lofo"
peak python -m defuse.run fit-gate --records "$D/lofo/OOF.jsonl" --tau 0.0075 --out "$D/gate.json"
python -m defuse.evaluate --records "$D/lofo/OOF.jsonl" --gate "$D/gate.json" --label "$LABEL" \
    --reference data/wild/reference/qwen3-1.7b_h100.json | tee "$D/RESULTS.md"
