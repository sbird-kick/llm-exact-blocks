# Ape210K rows: license

Derived from **Ape210K** ("Ape210K: A Large-Scale and Template-Rich Dataset of Math Word Problems", Liang et al.,
2020; https://github.com/Chenny0808/ape210k).

**License: not clearly stated.** The repository README (checked 2026-10-20) says only "We use the same license as
OpenNMT-py", which reads as a statement about the code; no data license is named. A third-party mirror
(https://huggingface.co/datasets/MU-NLPC/Calc-ape210k) lists MIT for its own version and asks to cite the Ape210K
paper. The rows are kept here for the owner's private use (decision of the repo owner, 2026-10-20: private
repository, not a redistribution); clear the license before making this folder public.

Changes made here: prompts ending at " The answer is", a parsed gold program, a digit-run record and a fold label.
Rows are the Ape210K problems that are `train` in the project's in-force split (and in the def-use pool: at most 5
digit runs). Includes the rows the project's older fold system had set aside as linked to evaluation rows (old fold 6);
under the in-force split rules they are train.
