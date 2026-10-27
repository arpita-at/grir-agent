"""The only place a model is used.

It never sees the whole account. It is handed one PO line that the deterministic
classifier could not explain, with the postings on it, and asked for a cause and an
owner. It is explicitly told it may answer "unclear", and the prompt exists to make
that an acceptable answer rather than a failure.

With no ANTHROPIC_API_KEY the deterministic action table carries everything, and the
report still ships. That is the point of putting rules first.
"""
from __future__ import annotations

import json
import os

from .grir import ACTION, Group

MODEL = os.environ.get("GRIR_MODEL", "claude-sonnet-5-5")

SYSTEM = """You triage one open GR/IR (goods received / invoice received) line.

You are given every posting on one purchase order line. The deterministic classifier
could not explain it, so you are looking at a genuine exception.

Answer as JSON only:
{"cause": "<one short sentence>", "owner": "Procurement|Receiving|Finance|Vendor",
 "action": "<the single next step>", "confidence": "high|medium|low"}

Rules:
- Use only the postings given. Do not infer a commercial story they do not support.
- "unclear" is a correct answer. Say it, set confidence low, and name what you would
  need to resolve it. Never invent a plausible cause to look useful.
- Never propose a write-off. A write-off is a human decision with a value threshold.
- Plain English. No em dashes.
"""


def _payload(g: Group, asof) -> dict:
    return {
        "po": g.po, "po_line": g.po_line, "vendor": g.vendor,
        "quantity_delta": g.qty_delta, "value_delta": g.value_delta,
        "age_days": g.age(asof),
        "postings": [
            {"doc": i.doc_id, "kind": i.kind, "qty": i.qty, "value": i.value,
             "posted_on": i.posted_on.isoformat(), "assignment": i.assignment,
             "text": i.text}
            for i in g.items
        ],
    }


def claude_triage(g: Group, asof) -> dict | None:
    """Returns the parsed verdict, or None on any failure. Fails closed."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        return None
    try:
        msg = Anthropic(api_key=key).messages.create(
            model=MODEL, max_tokens=300, system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(_payload(g, asof), indent=2)}],
        )
        raw = "".join(b.text for b in msg.content if b.type == "text").strip()
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        got = json.loads(raw)
    except Exception:
        return None
    if not isinstance(got, dict) or "cause" not in got or "owner" not in got:
        return None
    # The model does not get to invent an owner outside the ones we route to.
    if got.get("owner") not in {"Procurement", "Receiving", "Finance", "Vendor"}:
        got["owner"] = "Finance"
    return got


def triage(g: Group, category: str, asof, allow_model: bool = True) -> dict:
    """Deterministic owner and action, with a Claude verdict only where it helps."""
    owner, action = ACTION[category]
    out = {"owner": owner, "action": action, "cause": None,
           "confidence": None, "triaged_by": "rules"}
    if not allow_model or category not in {"needs_judgement", "goods_not_invoiced",
                                           "invoiced_not_received"}:
        return out
    got = claude_triage(g, asof)
    if not got:
        return out
    out.update(cause=got["cause"], owner=got["owner"],
               action=got.get("action") or action,
               confidence=got.get("confidence", "low"), triaged_by="claude")
    return out
