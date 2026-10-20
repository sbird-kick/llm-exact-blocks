# MathQA rows: license

Derived from the **train split of MathQA** ("MathQA: Towards Interpretable Math Word Problem Solving with
Operation-Based Formalisms", Amini et al., NAACL 2019; https://math-qa.github.io/), whose dataset page
(https://huggingface.co/datasets/allenai/math_qa) states: "The dataset is licensed under the Apache License, Version
2.0" (http://www.apache.org/licenses/LICENSE-2.0).

Changes made here: prompts ending at " The answer is", the `linear_formula` as gold program, a digit-run record and a
fold label. Rows are the MathQA problems that are `train` in the project's in-force split and not already in
`data/wild/mathqa/`.
