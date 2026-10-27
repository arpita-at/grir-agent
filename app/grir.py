"""GR/IR open item analysis. Deterministic. No model is called in this file.

Background, because the account is the point:

GR/IR (goods received / invoice received) is the holding account between receiving
goods and receiving the invoice. Post a goods receipt and SAP credits GR/IR. Post
the invoice and it debits GR/IR. When both sides land, the PO line nets to zero and
automatic clearing (F.13) takes it off the books.

When they do not net, the item sits there. Forever, in practice. Every GR/IR account
with any age on it has thousands of these, and the usual treatment is to age them,
stare at them, and write off whatever the auditor asks about.

Sign convention here: goods receipt is negative, invoice receipt is positive, so a
PO line that nets to zero sums to zero. That makes every test an assertion about a
single number.

The categories below are ordered. `classify` returns the first one that fits, and
the order is the whole design: cheap mechanical explanations first, judgement last.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Netting tolerance. Rounding and small FX movements should not create work.
TOL_VALUE = 1.00
TOL_QTY = 0.001


@dataclass(frozen=True)
class OpenItem:
    doc_id: str
    po: str
    po_line: str
    kind: str          # "GR" | "IR"
    qty: float         # signed, GR negative
    value: float       # signed, GR negative
    posted_on: date
    vendor: str
    assignment: str    # SAP ZUONR. The field F.13 groups on
    text: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.po, self.po_line)


@dataclass(frozen=True)
class Group:
    """Every open item on one PO line."""
    po: str
    po_line: str
    items: list[OpenItem]

    @property
    def qty_delta(self) -> float:
        return round(sum(i.qty for i in self.items), 6)

    @property
    def value_delta(self) -> float:
        return round(sum(i.value for i in self.items), 2)

    @property
    def exposure(self) -> float:
        """What writing this line off would hit. Always positive."""
        return abs(self.value_delta)

    @property
    def vendor(self) -> str:
        return self.items[0].vendor

    @property
    def oldest(self) -> date:
        return min(i.posted_on for i in self.items)

    @property
    def assignments(self) -> set[str]:
        return {i.assignment for i in self.items}

    def age(self, asof: date) -> int:
        return (asof - self.oldest).days

    def has(self, kind: str) -> bool:
        return any(i.kind == kind for i in self.items)


def nets_to_zero(g: Group) -> bool:
    return abs(g.value_delta) <= TOL_VALUE and abs(g.qty_delta) <= TOL_QTY


def classify(g: Group) -> str:
    """The mechanical cause, or `needs_judgement` if there is not one.

    Order matters and is deliberate:

    1. `assignment_mismatch` is checked before everything else because it is the
       cheapest and most common. The line already nets to zero. F.13 simply cannot
       see it, because the goods receipt and the invoice carry different values in
       the assignment field, and F.13 groups on that field. These are not a finance
       problem at all. They are noise, and on most accounts they are the single
       largest bucket. Nobody looks for them because an aged GR/IR report shows the
       line and not the fact that it already balances.
    2. Then the one-sided cases, which are a real exposure.
    3. Then quantity before price, because a quantity difference usually explains
       the value difference too and leading with price sends people to the wrong team.
    """
    if nets_to_zero(g):
        return "assignment_mismatch" if len(g.assignments) > 1 else "clearable"
    if not g.has("IR"):
        return "goods_not_invoiced"
    if not g.has("GR"):
        return "invoiced_not_received"
    if abs(g.qty_delta) > TOL_QTY:
        return "quantity_difference"
    if abs(g.value_delta) > TOL_VALUE:
        return "price_difference"
    return "needs_judgement"


#: Who owns each cause, and what actually resolves it. The owner is the point:
#: an aged GR/IR item with no named owner is why the account never gets smaller.
ACTION = {
    "assignment_mismatch": ("Finance systems", "Already nets to zero. Clear manually (F-03) or fix the F.13 grouping so it self-clears"),
    "clearable":           ("Finance", "Nets to zero. Run automatic clearing"),
    "goods_not_invoiced":  ("Procurement", "Chase the vendor invoice, or reverse the receipt if the goods were never delivered"),
    "invoiced_not_received": ("Receiving", "Post the goods receipt, or dispute the invoice"),
    "quantity_difference": ("Receiving", "Confirm the delivered quantity, then correct the receipt or the invoice"),
    "price_difference":    ("Procurement", "Reconcile PO price to invoice price. Price change, FX or a missed amendment"),
    "needs_judgement":     ("Finance", "No mechanical cause. Needs a person to read the PO"),
}


def age_bucket(days: int) -> str:
    if days <= 30:
        return "0-30"
    if days <= 60:
        return "31-60"
    if days <= 90:
        return "61-90"
    if days <= 180:
        return "91-180"
    return "180+"


def load(path: str | Path) -> list[OpenItem]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [
            OpenItem(
                doc_id=r["doc_id"].strip(), po=r["po"].strip(), po_line=r["po_line"].strip(),
                kind=r["kind"].strip().upper(), qty=float(r["qty"]), value=float(r["value"]),
                posted_on=date.fromisoformat(r["posted_on"].strip()),
                vendor=r["vendor"].strip(), assignment=r["assignment"].strip(),
                text=r.get("text", "").strip(),
            )
            for r in csv.DictReader(fh)
        ]


def group(items: list[OpenItem]) -> list[Group]:
    buckets: dict[tuple[str, str], list[OpenItem]] = defaultdict(list)
    for i in items:
        buckets[i.key].append(i)
    return [Group(po, line, sorted(v, key=lambda x: x.posted_on))
            for (po, line), v in sorted(buckets.items())]


def ageing(groups: list[Group], asof: date) -> dict[str, dict]:
    """The report a controller actually asks for, by bucket."""
    out: dict[str, dict] = {}
    for b in ("0-30", "31-60", "61-90", "91-180", "180+"):
        hits = [g for g in groups if age_bucket(g.age(asof)) == b]
        out[b] = {"lines": len(hits), "exposure": round(sum(g.exposure for g in hits), 2)}
    return out
