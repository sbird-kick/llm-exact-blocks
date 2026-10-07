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
                              [--reference data/wild/reference/qwen3-1.7b_h100.json]

With --reference, a third table puts the project's own numbers on the SAME shipped rows beside yours (summed over the
(set, fold) cells your records cover; a cell where your row count differs from the reference's is flagged, since then
the rows are not the same). Read RUN_ON_THOR.md, step 7, for what should and should not match.
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


def _set_of(x):
    p = str(x["row_id"]).split(":")
    return p[1] if len(p) > 2 and p[0] == "we" else None


def reference_table(recs, ref, gate=None, probes=None, label=""):
    """NEW: your headline numbers beside the reference file's, on the (set, fold) cells your records cover"""
    covered = collections.Counter("%s|%s" % (_set_of(x), x["fold"]) for x in recs)
    cells = {k: ref["cells"][k] for k in covered if k in ref["cells"]}
    L = ["yours%s beside the reference (the project's run: %s, %s)" % (" (%s)" % label if label else "", ref["host"], ref["hardware"]), ""]
    if not cells:
        return "\n".join(L + ["reference not available for these rows (the reference covers the shipped data/wild rows only: "
                              "cells %s; yours: %s)" % (", ".join(ref["cells"]), ", ".join(sorted(covered)))])
    mine = [x for x in recs if "%s|%s" % (_set_of(x), x["fold"]) in cells]
    other = len(recs) - len(mine)
    bad = ["%s (yours %d, reference %d)" % (k, covered[k], cells[k]["rows"]) for k in sorted(cells) if covered[k] != cells[k]["rows"]]
    tot = collections.Counter(); st = collections.Counter(); gt = {g: collections.Counter() for g in ("gate_no_probe", "gate_project")}
    for c in cells.values():
        tot.update({k: c[k] for k in ("rows", "HR", "host_none", "fires", "broken", "fixed")})
        for b in c["steps"].values():
            st.update(b)
        for g in gt:
            gt[g].update(c[g])
    n, m = len(mine), tot["rows"]
    yl = GT.ledger(mine)
    T = by_gold_steps(mine)
    vr = sum(c["reader_value_right"] for c in T.values())
    L += ["| quantity | yours | reference |", "|---|---|---|",
          "| rows | %d | %d |" % (n, m),
          "| host right | %s | %s |" % (GT.nt(yl["HR"], n), GT.nt(tot["HR"], m)),
          "| host silent (no number) | %s | %s |" % (GT.nt(sum(bool(x["host1_none"]) for x in mine), n), GT.nt(tot["host_none"], m)),
          "| reader value-right (L24 program, ungated) | %s | %s |" % (GT.nt(vr, n), GT.nt(st["reader_value_right"], m)),
          "| DU-AG ungated: fires | %s | %s |" % (GT.nt(yl["fires"], n), GT.nt(tot["fires"], m)),
          "| DU-AG ungated: broken / host-right | %s | %s |" % (GT.nt(yl["broken"], yl["HR"]), GT.nt(tot["broken"], tot["HR"])),
          "| DU-AG ungated: fixed / host-wrong | %s | %s |" % (GT.nt(yl["fixed"], n - yl["HR"]), GT.nt(tot["fixed"], m - tot["HR"]))]
    if gate is not None:
        ids = GT.apply_gate(mine, gate, probes)
        g = GT.ledger(mine, lambda x: x["row_id"] in ids)
        r = gt["gate_no_probe"]
        L += ["| gated (yours: your gate; reference: the same no-probe gate recipe on its decodes): fires | %s | %s |" % (GT.nt(g["fires"], n), GT.nt(r["fires"], m)),
              "| gated: broken / host-right | %s | %s |" % (GT.nt(g["broken"], g["HR"]), GT.nt(r["broken"], tot["HR"])),
              "| gated: fixed / host-wrong | %s | %s |" % (GT.nt(g["fixed"], n - g["HR"]), GT.nt(r["fixed"], m - tot["HR"])),
              "| gated: system right | %s | %s |" % (GT.nt(g["HR"] + g["net"], n), GT.nt(tot["HR"] - r["broken"] + r["fixed"], m))]
    r = gt["gate_project"]
    L += ["| context: the project's frozen 1.7B gate (with host-outcome probes) on the reference decodes: fires / broken / fixed "
          "| - | %d / %d / %d |" % (r["fires"], r["broken"], r["fixed"]), ""]
    L.append("reference readers: " + ref["readers"] + ".")
    L.append("reference host labels: " + ref["host_labels"] + ".")
    L.append("Host difference: the reference dumps were made on an H100; your host runs the same weights in bf16 on other "
             "hardware, so expect a few percent of rows to flip (host answer or a near-tie in the readers), not a different picture.")
    if other:
        L.append("NOTE: %d of your records are outside the reference's cells and are left out of this table." % other)
    if bad:
        L.append("NOT THE SAME ROWS in %d cell(s): %s. The dumper skips rows whose run count differs, and --max-rows "
                 "takes a prefix; compare rates, not counts, there." % (len(bad), "; ".join(bad)))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--records", required=True)
    ap.add_argument("--gate", default=None)
    ap.add_argument("--probes", default=None, help="jsonl of {row_id, slot, space} if the gate was fitted with probes")
    ap.add_argument("--label", default="", help="host and hardware, e.g. 'Llama-3.2-1B, A100'")
    ap.add_argument("--reference", default=None, help="a reference file (data/wild/reference/) to print beside yours")
    a = ap.parse_args()
    recs = [json.loads(l) for l in open(a.records, encoding="utf-8") if l.strip()]
    gate = json.load(open(a.gate)) if a.gate else None
    probes = None
    if a.probes:
        probes = {x["row_id"]: x for x in (json.loads(l) for l in open(a.probes, encoding="utf-8") if l.strip())}
    print(steps_table(recs, a.label)); print()
    print(ledger_table(recs, gate, probes, a.label))
    if a.reference:
        print(); print(reference_table(recs, json.load(open(a.reference)), gate, probes, a.label))


if __name__ == "__main__":
    main()
