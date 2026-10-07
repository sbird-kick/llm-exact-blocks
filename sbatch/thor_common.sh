# Sourced by the sbatch/thor_*.sbatch files: the Thor's rules for every job, in one place.
#   * PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True in every job (set again after the venv is activated);
#   * a GPU job asks for its GPU explicitly (--gres=shard:1) and samples GPU utilisation with nvidia-smi into
#     logs/gpu-<job>.csv (a missing nvidia-smi never fails the job);
#   * --mem is tight and comes from measured peak memory (RUN_ON_THOR.md): the 122 GB pool is shared with other users;
#   * never reboot the board to free memory, and never touch other users' jobs or files.
set -eu
cd "${SLURM_SUBMIT_DIR:-$PWD}"
mkdir -p logs
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
       HF_HUB_DISABLE_PROGRESS_BARS=1 OMP_NUM_THREADS=${THREADS:-2} OPENBLAS_NUM_THREADS=${THREADS:-2} MKL_NUM_THREADS=${THREADS:-2}
# ---- PLACEHOLDER: your environment (RUN_ON_THOR.md, steps 1-2). VENV and HF_HOME may also be passed with --export.
set +u; source "${VENV:-$HOME/defuse-venv}/bin/activate"; set -u
export HF_HOME="${HF_HOME:-$HOME/hf_cache}"
# -------------------------------------------------------------------------------------------------------------------
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

gpu_sampler() {                       # call once in a GPU job; stops itself when the job ends
    ( nvidia-smi --query-gpu=timestamp,utilization.gpu --format=csv,noheader -l 5 > "logs/gpu-${SLURM_JOB_ID:-local}.csv" 2>/dev/null || true ) &
    SAMPLER=$!
    trap 'kill $SAMPLER 2>/dev/null || true; gpu_summary' EXIT
}
gpu_summary() {
    local f="logs/gpu-${SLURM_JOB_ID:-local}.csv"
    [ -s "$f" ] && awk -F', ' '{gsub(/ %/,"",$2); if ($2 ~ /^[0-9]+$/) {s+=$2; n++; if ($2>m) m=$2}} END {if (n) printf "GPU util: mean %.0f%%, max %d%% over %d samples (5 s apart; the GPU is shared, so this counts every user)\n", s/n, m, n}' "$f" || true
}
peak() {                              # run one step; print its wall time and peak resident memory
    python -c 'import resource, subprocess, sys, time
t = time.time(); rc = subprocess.run(sys.argv[1:]).returncode
print("STEP %s: rc %d, wall %.0f s, peak RSS %.2f GB" % (" ".join(sys.argv[1:5]), rc, time.time() - t,
      resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 2**20), flush=True)
sys.exit(rc)' "$@"
}
