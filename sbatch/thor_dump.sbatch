#!/bin/bash
# GPU, once: dump Qwen3-1.7B's hidden states at the cue for every row (defuse/dump.py), with its own greedy answer.
#   sbatch sbatch/thor_dump.sbatch runs/q17/rows.jsonl runs/q17
# Layers 16 / 19 / 22 of 28 (the project's 1.7B layers; relabelled 20 / 24 / 28 when fitting). One job writes one .pt.
#SBATCH --job-name=defuse-dump
#SBATCH --partition=main
#SBATCH --gres=shard:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out
source sbatch/thor_common.sh
ROWS=${1:?rows.jsonl}; OUT=${2:?output folder}; MODEL=${MODEL:-Qwen/Qwen3-1.7B}
mkdir -p "$OUT"
gpu_sampler
peak python -m defuse.dump --host "$MODEL" --tag q17 --out "$OUT" --banks "wild=$ROWS" \
    --layers 16,19,22 --max-runs 5 --greedy 12 --batch 8 --locator single
