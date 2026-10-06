"""evaluate.py -- score decoded records by GOLD STEPS, with n/total everywhere. NEW CODE (not a port); the ledger
and the R1 words come from gate.py (ported).

A record is one row after decoding (fit_b.decode_record writes them): host1_right / host1_none (the host's own
answer), fire / right (the system after the DU-AG rule), value24 (the program read at the middle layer label,
executed exactly), gold_value, gold_steps, decodable.

Two tables, the project's habit:
  1. value-right by gold steps: how often the program READ from the host executes to the gold value (whether or not
     it fires), beside how often the host itself is right, per gold-step bucket (0, 1, 2, 3, 4+, no gold program).
  2. the R1 ledger: fires, broken / host-right, fixed / host-wrong, net, system right, R1 word, for the ungated
     rule and, if a gate is given, the gated rule.

    python -m defuse.evaluate --records dec.jsonl [--gate gate.json --probes probes.jsonl] [--label "Llama-3.2-1B, <gpu>"]
"""
import argparse
import collections
import json
from fractions import Fraction

from . import gate as GT

BUCKETS = ("0", "1", "2", "3", "4+", "no gold program")


def bucket(x):
    s = x.get("gold_steps")
    if s is None:
        return "no gold program"
    return str(s) if s < 4 else "4+"


def value_right(x):
    v = x.get("value24")
    return v is not None and Fraction(v) == Fraction(x["gold_value"])


def by_gold_steps(recs):
    """{bucket: dict(rows, reader_value_right, host_right, system_right)}; all counts out of `rows`"""
    out = collections.OrderedDict((b, collections.Counter()) for b in BUCKETS)
    for x in recs:
        c = out[bucket(x)]
        c["rows"] += 1
        c["reader_value_right"] += value_right(x)
        c["host_right"] += bool(x["host1_right"])
        c["system_right"] += bool(x["right"]) if x["fire"] else bool(x["host1_right"])
    return out


def steps_table(recs, label=""):
    T = by_gold_steps(recs)
    L = ["value-right by gold steps%s" % (" (%s)" % label if label else ""), "",
         "| gold steps | rows | reader value-right | host right | system right (ungated DU-AG) |", "|---|---|---|---|---|"]
    tot = collections.Counter()
    for b, c in T.items():
        if not c["rows"]:
            continue
        n = c["rows"]
        L.append("| %s | %d | %s | %s | %s |" % (b, n, GT.nt(c["reader_value_right"], n), GT.nt(c["host_right"], n),
                                                GT.nt(c["system_right"], n)))
        tot.update(c)
    n = tot["rows"]
    L.append("| all | %d | %s | %s | %s |" % (n, GT.nt(tot["reader_value_right"], n), GT.nt(tot["host_right"], n),
                                              GT.nt(tot["system_right"], n)))
    return "\n".join(L)


def ledger_table(recs, gate=None, probes=None, label=""):
    L = ["R1 ledger%s" % (" (%s)" % label if label else ""), "",
         "| rule | fires | broken / host-right | fixed / host-wrong | net | system right | R1 |", "|---|---|---|---|---|---|---|"]

    def row(name, d):
        return "| %s | %s | %s | %s | %+d | %s | %s (bar %d) |" % (
            name, GT.nt(d["fires"], d["rows"]), GT.nt(d["broken"], d["HR"]), GT.nt(d["fixed"], d["host_wrong"]), d["net"],
            GT.nt(d["HR"] + d["net"], d["rows"]), d["r1"], d["bar"])
    L.append(row("DU-AG ungated", GT.ledger(recs)))
    if gate is not None:
        ids = GT.apply_gate(recs, gate, probes)
        L.append(row("DU-AG + gate (tau %.2f%%)" % (100 * gate["tau"]), GT.ledger(recs, lambda x: x["row_id"] in ids)))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--records", required=True)
    ap.add_argument("--gate", default=None)
    ap.add_argument("--probes", default=None, help="jsonl of {row_id, slot, space} if the gate was fitted with probes")
    ap.add_argument("--label", default="", help="host and hardware, e.g. 'Llama-3.2-1B, A100'")
    a = ap.parse_args()
    recs = [json.loads(l) for l in open(a.records, encoding="utf-8") if l.strip()]
    gate = json.load(open(a.gate)) if a.gate else None
    probes = None
    if a.probes:
        probes = {x["row_id"]: x for x in (json.loads(l) for l in open(a.probes, encoding="utf-8") if l.strip())}
    print(steps_table(recs, a.label)); print()
    print(ledger_table(recs, gate, probes, a.label))


if __name__ == "__main__":
    main()
