"""Stages, in order. This is the diagram in the post."""
from __future__ import annotations

import os
from datetime import date

from .grir import Group, ageing, classify, group, nets_to_zero
from .triage import triage, wants_model

#: Lines the deterministic classifier fully explains never reach the model.
MAX_TRIAGE = int(os.environ.get("GRIR_MAX_TRIAGE", 25))


def run(items, asof: date | None = None, writeoff_limit: float = 1_000.0) -> dict:
    asof = asof or date.today()
    groups = group(items)
    rows, sent = [], 0
    for g in groups:
        cat = classify(g)
        # Budget is spent on attempts. A key that fails every call must still run
        # the budget down, or a bad key turns the cap into no cap at all.
        allow = wants_model(cat) and sent < MAX_TRIAGE
        t = triage(g, cat, asof, allow_model=allow)
        if t.pop("attempted", False):
            sent += 1
        rows.append({
            "po": g.po, "po_line": g.po_line, "vendor": g.vendor,
            "category": cat, "qty_delta": g.qty_delta, "value_delta": g.value_delta,
            "exposure": g.exposure, "age_days": g.age(asof),
            "postings": len(g.items),
            # Small, aged, and already netting: the MR11 write-off shortlist. Proposed
            # only. Nothing here posts anything.
            "writeoff_candidate": g.exposure <= writeoff_limit and g.age(asof) > 90
                                  and not nets_to_zero(g),
            **t,
        })
    rows.sort(key=lambda r: (-r["exposure"], -r["age_days"]))

    by_cat: dict[str, dict] = {}
    for r in rows:
        c = by_cat.setdefault(r["category"], {"lines": 0, "exposure": 0.0})
        c["lines"] += 1
        c["exposure"] = round(c["exposure"] + r["exposure"], 2)

    self_clearing = [r for r in rows if r["category"] == "assignment_mismatch"]
    real = [r for r in rows if r["category"] not in {"assignment_mismatch", "clearable"}]
    return {
        "summary": {
            "lines": len(rows),
            "open_exposure": round(sum(r["exposure"] for r in real), 2),
            # The headline. How much of the account is not a finance problem at all.
            "noise_lines": len(self_clearing),
            "noise_share": round(len(self_clearing) / len(rows), 4) if rows else 0.0,
            "writeoff_candidates": sum(1 for r in rows if r["writeoff_candidate"]),
            "sent_to_model": sent,
        },
        "by_category": by_cat,
        "ageing": ageing(groups, asof),
        "lines": rows,
    }
