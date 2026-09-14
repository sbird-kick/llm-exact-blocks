#!/bin/bash
# The CPU test battery. No GPU, no model weights, no network.
#
#   sbatch sbatch/cpu_tests.sbatch
#
# CPU WORK GOES TO THE CPU PARTITION. The login node is for editing and squeue;
# anything that imports torch belongs in a job, even when it takes nine seconds.
#
#SBATCH --job-name=exact-block-cputests
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:15:00
#SBATCH --export=ALL
#SBATCH --output=logs/%x-%j.out

set -eu
cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs

export HF_HOME=${HF_HOME:-$HOME/ctrn/hf_cache}
export HF_HUB_OFFLINE=1           # fail loudly rather than silently download
export OMP_NUM_THREADS=4
export TOKENIZERS_PARALLELISM=false

# ---- PLACEHOLDER: point this at your own environment -------------------------
# Replace with your venv / conda / module lines. Anything that puts torch 2.13
# and transformers 5.15 on the path will do.
source "$HOME/ctrn/venv/bin/activate"
# ------------------------------------------------------------------------------

python -V
python tests/test_cpu.py
