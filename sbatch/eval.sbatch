#!/bin/bash
# Score a trained checkpoint against its own frozen host, per width cell.
#
#   sbatch sbatch/eval.sbatch runs/demo/block.pt test
#
#SBATCH --job-name=exact-block-eval
#SBATCH --partition=batch
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:40:00
#SBATCH --export=ALL
#SBATCH --output=logs/%x-%j.out

set -eu
cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs

export HF_HOME=${HF_HOME:-$HOME/ctrn/hf_cache}
export HF_HUB_OFFLINE=1
export OMP_NUM_THREADS=4
export TOKENIZERS_PARALLELISM=false

# ---- PLACEHOLDER: point this at your own environment -------------------------
source "$HOME/ctrn/venv/bin/activate"
# ------------------------------------------------------------------------------

CKPT="${1:-runs/demo/block.pt}"
SPLIT="${2:-test}"
MODEL="${MODEL:-Qwen/Qwen3-1.7B}"

nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
python eval.py --model "$MODEL" --data data --ckpt "$CKPT" --split "$SPLIT"
