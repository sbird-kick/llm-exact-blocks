"""A tiny exact-arithmetic block for a frozen Qwen3 host (binary integer ops).

Four files, in the order a token meets them:

    numerals.py  the locator   -- which tokens are the digits of which number
    calc.py      the calculator -- exact add / sub / mul on decoded digits
    block.py     the block      -- probe, tagger, router, gate, write + hooks
    data.py      the corpus     -- templated prose problems with distractors
"""

__all__ = ["numerals", "calc", "block", "data"]
