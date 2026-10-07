# ASDiv rows: license

The rows in this folder are derived from **ASDiv** ("A Diverse Corpus for Evaluating and Developing English Math Word
Problem Solvers", Miao, Liang and Su, ACL 2020; https://github.com/chaochun/nlu-asdiv-dataset), which is distributed
under the **Creative Commons Attribution-NonCommercial 4.0 International** license (CC BY-NC 4.0,
https://creativecommons.org/licenses/by-nc/4.0/).

The license travels with these files: use them for non-commercial research and teaching only, and keep this
attribution with any copy. Changes made here: the problems were reformatted into prompts ending at " The answer is",
each row carries a parsed gold program, a digit-run record and a fold label, and only folds 1-4 of the project's
def-use pool are included (see ../README.md). The `asdiv_source` field keeps the per-problem source the dataset lists.
