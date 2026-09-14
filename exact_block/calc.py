"""THE CALCULATOR. Zero parameters. Exact column arithmetic on decoded digits.

The block's probe hands this file two operands as digit DISTRIBUTIONS, (B, dmax, 10) and
LSD-first. It hands back R, (B, 2*dmax, 10), one digit distribution per result place --
in fact one HARD one-hot per place, because the arithmetic here is exact.

=== WHY COLUMNS AND NOT PYTHON INTS ===
Python ints would also be exact, and the deployed block keeps a Python path for exactly
that reason. Columns are used here because they are (a) vectorised over the batch, (b)
the same shape as the answer the block writes, and (c) where the two REFUSALS fall out
for free: `resolve_carry` returns the digits AND the carry that ran off the top of the
lane vector, and

    carry < 0  =>  the result is negative        (a - b with a < b)
    carry > 0  =>  the result is wider than 2*dmax

are precisely the two cases with no honest rendering in the answer lanes -- there is no
sign channel and no overflow channel -- so the block abstains and the host's own logits
stand. The third refusal (an operand wider than dmax) is caught earlier, by the locator.

=== FP32, ALWAYS, AND THIS IS NOT A STYLE CHOICE ===
A 16x16 product's column sum reaches 16 * 9 * 9 = 1296 plus carry. bf16 has 8 mantissa
bits and is exact only to 256, so a bf16 column sum is silently WRONG in the middle of a
number that is otherwise perfect. The host runs in bf16; everything in this file is cast
to fp32 on the way in.

The multiplication table M[i, j, k] = 1 iff a_i * b_j belongs in place k IS the compiled
program: schoolbook is k == i + j, and swapping M would swap algorithm.
"""
from __future__ import annotations

import torch
import torch.nn.functional as F

OPS = ("add", "sub", "mul")

# op name -> the Python operator, used by the corpus generator and by the tests to say
# what the right answer IS, independently of anything in this file's tensors.
PY_OPS = {
    "add": lambda a, b: a + b,
    "sub": lambda a, b: a - b,
    "mul": lambda a, b: a * b,
}


def exact_answer(a: int, b: int, op: str) -> int:
    return PY_OPS[op](a, b)


def place_routing(dmax: int, device=None) -> torch.Tensor:
    """M[i, j, k] = 1 iff the partial product a_i * b_j lands in place k. (dmax, dmax, 2*dmax)."""
    M = torch.zeros(dmax, dmax, 2 * dmax, device=device)
    i = torch.arange(dmax, device=device)
    M[i.view(-1, 1), i.view(1, -1), i.view(-1, 1) + i.view(1, -1)] = 1.0
    return M


def hard_digits(dist: torch.Tensor) -> torch.Tensor:
    """(B, D, 10) distributions -> (B, D) float digit VALUES, by argmax. Exact."""
    return dist.argmax(-1).to(torch.float32)


def columns(a: torch.Tensor, b: torch.Tensor, op: str, routing: torch.Tensor) -> torch.Tensor:
    """Digit values (B, dmax) -> unresolved column sums (B, 2*dmax). No carry yet."""
    if op == "mul":
        P = a.unsqueeze(-1) * b.unsqueeze(-2)              # (B, dmax, dmax)
        return torch.einsum("bij,ijk->bk", P, routing)
    pad = torch.zeros_like(a)
    if op == "add":
        return torch.cat([a + b, pad], -1)
    if op == "sub":
        return torch.cat([a - b, pad], -1)
    raise ValueError(f"unknown op {op!r}; this block ships {OPS}")


def resolve_carry(s: torch.Tensor):
    """Column sums -> (digits, carry-out). Exact for integral inputs, borrow included.

    d_k = t - 10 * floor(t / 10) is t mod 10. Floor division on a negative column gives
    the correct BORROW with no special case at all: 10 - 3 has columns [-3, 1], and the
    loop turns them into digits [7, 0] with carry 0.

    The carry that survives the last place is returned rather than dropped: it is the
    block's overflow (> 0) and negative-result (< 0) detector, and dropping it is how a
    calculator silently writes a ten's complement.
    """
    out, c = [], torch.zeros_like(s[..., 0])
    for k in range(s.shape[-1]):
        t = s[..., k] + c
        c = torch.div(t, 10, rounding_mode="floor")
        out.append(t - 10 * c)
    return torch.stack(out, -1), c


class Calc:
    """Stateless, parameter-free. A class only so the routing table is built once."""

    def __init__(self, dmax: int = 16, ops=OPS):
        self.dmax = int(dmax)
        self.ops = tuple(ops)
        assert all(o in OPS for o in self.ops), self.ops
        self._routing = None                      # built lazily, on the right device

    def routing(self, device) -> torch.Tensor:
        if self._routing is None or self._routing.device != device:
            self._routing = place_routing(self.dmax, device)
        return self._routing

    def __call__(self, A: torch.Tensor, B: torch.Tensor, op_index: torch.Tensor):
        """A, B: (B, dmax, 10) LSD-first digit distributions. op_index: (B,) into self.ops.

        Returns (R, refused):
            R        (B, 2*dmax, 10) one-hot digit distributions, LSD-first
            refused  (B,) float mask, 1.0 where this row has no honest rendering
        """
        A, B = A.float(), B.float()
        a, b = hard_digits(A), hard_digits(B)
        rt = self.routing(a.device)
        digs, carries = [], []
        for op in self.ops:                        # every body, then select by the router
            d, c = resolve_carry(columns(a, b, op, rt))
            digs.append(d)
            carries.append(c)
        D = torch.stack(digs, 0)                   # (n_ops, B, 2*dmax)
        C = torch.stack(carries, 0)                # (n_ops, B)
        idx = op_index.view(1, -1, 1).expand(1, D.shape[1], D.shape[2])
        chosen = D.gather(0, idx).squeeze(0)       # (B, 2*dmax)
        carry = C.gather(0, op_index.view(1, -1)).squeeze(0)
        refused = (carry != 0).to(A.dtype)         # negative OR wider than 2*dmax
        R = F.one_hot(chosen.long().clamp(0, 9), 10).to(A.dtype)
        return R, refused


def decode_places(R: torch.Tensor) -> list[int]:
    """(B, W, 10) LSD-first digit distributions -> one Python int per row."""
    d = R.argmax(-1).cpu().tolist()
    return [sum(v * 10 ** k for k, v in enumerate(row)) for row in d]
