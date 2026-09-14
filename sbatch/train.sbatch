#!/bin/bash
# Generate the corpus, then train the block on one GPU.
#
#   sbatch sbatch/train.sbatch                 # defaults below
#   sbatch sbatch/train.sbatch myrun 3000 64   # name, steps, batch size
#
# EVERY GPU JOB GOES TO --partition=batch. Never dev.
#
# The reference run (3000 steps, bs 64, Qwen3-1.7B) took 4m14s wall including corpus
# generation and the full test eval, so --time is set to 40 minutes: room for a much
# longer run, still tight enough to schedule on a busy queue.
#
#SBATCH --job-name=exact-block-train
#SBATCH --partition=batch
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:40:00
#SBATCH --export=ALL
#SBATCH --output=logs/%x-%j.out

set -eu
cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs runs data

export HF_HOME=${HF_HOME:-$HOME/ctrn/hf_cache}
export HF_HUB_OFFLINE=1           # the weights must already be in HF_HOME
export OMP_NUM_THREADS=4
export TOKENIZERS_PARALLELISM=false

# ---- PLACEHOLDER: point this at your own environment -------------------------
source "$HOME/ctrn/venv/bin/activate"
# ------------------------------------------------------------------------------

RUN="${1:-demo}"
STEPS="${2:-3000}"
BS="${3:-64}"
MODEL="${MODEL:-Qwen/Qwen3-1.7B}"

nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
echo "run=$RUN steps=$STEPS bs=$BS model=$MODEL"

# The corpus is deterministic in --seed, so regenerating it is free and the
# training job is self-contained.
python -m exact_block.data --out data --seed 0

python train.py --model "$MODEL" --data data --out "runs/$RUN" \
  --steps "$STEPS" --bs "$BS" \
  --read-layer 8 --route-layer 16 --write-layer 24

python eval.py --model "$MODEL" --data data --ckpt "runs/$RUN/block.pt" --split test
