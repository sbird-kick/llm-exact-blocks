# MathQA rows: license

The rows in this folder are derived from the **train split of MathQA** ("MathQA: Towards Interpretable Math Word
Problem Solving with Operation-Based Formalisms", Amini et al., NAACL 2019; https://math-qa.github.io/), which is
distributed under the **Apache License 2.0** (https://www.apache.org/licenses/LICENSE-2.0).

Changes made here: the problems were reformatted into prompts ending at " The answer is", each row carries its
`linear_formula` as the gold program, a digit-run record and a fold label, and only folds 1-4 of the project's def-use
pool, train split only, are included (see ../README.md). MathQA's own dev and test splits are not included.
