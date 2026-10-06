#!/bin/bash
# The def-use CPU steps (tests, reader B fit, LOFO decodes, gate). No GPU.
#
#   sbatch sbatch/defuse_cpu.sbatch tests
#   sbatch sbatch/defuse_cpu.sbatch fit-b  --rows R.jsonl --dump dumps/T_rows_operandstate.pt --relabel 9:20,11:24,13:28 --out fitB
#   sbatch sbatch/defuse_cpu.sbatch lofo-b --rows R.jsonl --dump ... --relabel ... --fit fitB --out lofo
#
# CPU WORK GOES TO THE CPU PARTITION. numpy uses one BLAS thread per job here (the project saw an OpenBLAS crash at
# 4 threads on large Gram matrices); raise it only after a small run.
#
#SBATCH --job-name=defuse-cpu
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=2
#SBATCH --mem=24G
#SBATCH --time=04:00:00
#SBATCH --export=ALL
#SBATCH --output=logs/%x-%j.out

set -eu
cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1

# ---- PLACEHOLDER: point this at your own environment (numpy; pytest for the tests; torch to read .pt dumps) ----
source "$HOME/venv/bin/activate"
# ----------------------------------------------------------------------------------------------------------------

if [ "${1:-tests}" = "tests" ]; then
    python -m pytest -q tests/test_defuse_cpu.py
else
    python -m defuse.run "$@"
fi
