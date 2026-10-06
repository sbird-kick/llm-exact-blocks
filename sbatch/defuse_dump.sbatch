#!/bin/bash
# The def-use reader's only GPU step: dump the host's hidden states at the cue (defuse/dump.py).
#
#   sbatch sbatch/defuse_dump.sbatch <hf-model> <tag> <rows.jsonl> <layers> [locator]
#   sbatch sbatch/defuse_dump.sbatch meta-llama/Llama-3.2-1B l1b data/my_rows.jsonl 9,11,13 grouped
#
# EVERY GPU JOB GOES TO --partition=batch. Never dev. Ask for ONE GPU: the dump is one forward pass per row
# (plus --greedy 12 new tokens for the host's own answer). Size --time from a small first run (--max-rows 200).
#
#SBATCH --job-name=defuse-dump
#SBATCH --partition=batch
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=01:00:00
#SBATCH --export=ALL
#SBATCH --output=logs/%x-%j.out

set -eu
cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs dumps
MODEL=${1:?hf model}; TAG=${2:?tag}; ROWS=${3:?rows.jsonl}; LAYERS=${4:?layers, e.g. 9,11,13}; LOC=${5:-single}

export HF_HUB_OFFLINE=1           # the weights must already be in HF_HOME
export TOKENIZERS_PARALLELISM=false

# ---- PLACEHOLDER: point this at your own environment (torch + transformers + numpy) and set HF_HOME ----------
source "$HOME/venv/bin/activate"
# --------------------------------------------------------------------------------------------------------------

python -m defuse.dump --host "$MODEL" --tag "$TAG" --out dumps --banks "rows=$ROWS" \
    --layers "$LAYERS" --max-runs 5 --greedy 12 --batch 8 --locator "$LOC"
