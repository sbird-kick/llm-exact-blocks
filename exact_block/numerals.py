"""THE LOCATOR. Zero parameters, runs before the forward pass, needs no torch.

Qwen3's pre-tokenizer splits every run of digits into ONE TOKEN PER DIGIT, and a digit
token never carries the preceding space. So "the total of 331 and 976 is" contains two
maximal runs of single-digit tokens, and the digit string of a run is just the decoded
tokens joined. That is the whole grammar this file needs: find the maximal runs, read
their values, and lay each run's token positions out LSD-FIRST (place 0 = units) into a
fixed-width lane vector, because every downstream tensor in the block is indexed by
DECIMAL PLACE and not by position in the sentence.

This file deliberately knows nothing about thousands separators, decimal points, or
non-ASCII digits. The corpus in data.py writes plain ASCII integers and nothing else;
see the README's "deliberately left out" list.
"""
from __future__ import annotations

_DIGITS = "0123456789"

# id(tokenizer) -> {token id: is it a single ASCII digit?}. Decoding one token is cheap
# but not free, and build_batch asks the question for every token of every row of every
# batch, so the answer is remembered. Keyed by the tokenizer object because the answer is
# a property of ITS vocabulary and would be silently wrong under another one.
_IS_DIGIT_CACHE: dict[int, dict[int, bool]] = {}


def is_digit_token(tok, tid: int) -> bool:
    """Does token id `tid` decode to exactly one ASCII digit?"""
    cache = _IS_DIGIT_CACHE.setdefault(id(tok), {})
    known = cache.get(tid)
    if known is None:
        s = tok.decode([tid])
        known = len(s) == 1 and s in _DIGITS
        cache[tid] = known
    return known


def digit_runs(tok, ids) -> list[list[int]]:
    """Maximal runs of consecutive single-digit tokens. -> [[pos, ...], ...] in text order."""
    runs: list[list[int]] = []
    cur: list[int] = []
    for i, tid in enumerate(ids):
        if is_digit_token(tok, tid):
            cur.append(i)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def run_value(tok, ids, run) -> int:
    """The integer a located run denotes."""
    return int("".join(tok.decode([ids[i]]) for i in run))


def number_runs(tok, ids) -> list[tuple[list[int], int]]:
    """[(token positions, value), ...] for every number in the sequence."""
    return [(r, run_value(tok, ids, r)) for r in digit_runs(tok, ids)]


def lanes_lsd(run, dmax: int) -> list[int]:
    """Token positions of a run, LSD-first, padded to `dmax` lanes with -1.

    Lane k holds the token position of the 10^k place. `-1` means "this operand has no
    such place", and CalcBlock.read_operand turns a -1 lane into a hard one-hot ZERO --
    which is exact, since a leading zero contributes nothing to any sum or product.
    """
    assert len(run) <= dmax, (
        f"a {len(run)}-digit number does not fit {dmax} lanes; raise --dmax or narrow "
        f"the corpus (the block REFUSES over-wide operands rather than truncating them)")
    out = [-1] * dmax
    for k, pos in enumerate(reversed(run)):        # reversed = least significant first
        out[k] = pos
    return out


def digits_lsd(n: int, width: int) -> list[int]:
    """The decimal digits of a non-negative int, LSD-first, zero-padded to `width`."""
    assert n >= 0, n
    out = [0] * width
    for k in range(width):
        n, out[k] = divmod(n, 10)
    assert n == 0, f"{width} places cannot hold this number"
    return out
