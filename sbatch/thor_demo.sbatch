#!/bin/bash
# GPU: the live demo with your readers (demo/serve.py), on 127.0.0.1:<port> of the Thor, until --time or scancel.
#   sbatch sbatch/thor_demo.sbatch demo/config.json
# Then, on your laptop: ssh -N -L <port>:127.0.0.1:<port> <you>@<the Thor>   and open http://localhost:<port>/
#SBATCH --job-name=defuse-demo
#SBATCH --partition=main
#SBATCH --gres=shard:1
#SBATCH --cpus-per-task=2
#SBATCH --mem=6G
#SBATCH --time=03:00:00
#SBATCH --output=logs/%x-%j.out
source sbatch/thor_common.sh
CFG=${1:?config.json}
gpu_sampler
python demo/serve.py --config "$CFG"
