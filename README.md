# grir-agent

**grir-agent triages open GR/IR items in SAP.** It groups every posting by purchase order line, nets it, names the mechanical cause, assigns an owner, and separates the lines that are a real exposure from the lines that already balance. A model is used only on the exceptions no rule can explain.

Sample data is synthetic. There are no real vendors or purchase orders in this repo.

```
GR/IR open items (FBL3N / MB5S export)
        │
        ├─► group by PO line           (rules)   every posting on one line, netted
        ├─► classify the cause         (rules)   7 categories, checked in order
        ├─► age and size it            (rules)   buckets, exposure, MR11 shortlist
        ├─► triage the residual        (claude)  only what no rule explained
        └─► you decide the write-off   (human)   nothing here posts anything
```

---

## What is GR/IR and why does the account never get smaller?

GR/IR (goods received / invoice received) is the holding account between receiving goods and receiving the invoice. A goods receipt credits it. The invoice debits it. When both land, the PO line nets to zero and automatic clearing takes it off the books.

When they do not net, the item sits there. Every GR/IR account with any age on it has thousands of these. The usual treatment is to age them, stare at them, and write off whatever the auditor asks about.

## The finding this tool exists to surface

**Most aged GR/IR lines are not a finance problem. They already balance.**

Automatic clearing (`F.13`) groups on the assignment field, `ZUONR`. When a goods receipt carries `GR20260418` and the matching invoice carries `INV-SL-88120`, the line nets to zero perfectly and `F.13` still cannot see it. So it ages. And an aged GR/IR report shows you the line, not the fact that it already balances.

On the synthetic sample here that is **45% of the account**, carrying **zero** real exposure:

| Cause | Lines | Exposure |
|---|---:|---:|
| `assignment_mismatch` | 5 | 0 |
| `goods_not_invoiced` | 1 | 412,800 |
| `invoiced_not_received` | 1 | 74,400 |
| `price_difference` | 2 | 13,540 |
| `quantity_difference` | 1 | 2,700 |
| `clearable` | 1 | 0 |

Separating those two groups is the whole job. Everything else is detail.

## The seven causes, and why the order matters

`classify()` returns the first category that fits. The order is the design:

| # | Category | Means | Owner |
|---|---|---|---|
| 1 | `assignment_mismatch` | Nets to zero, but the assignment fields differ so `F.13` cannot group it | Finance systems |
| 2 | `clearable` | Nets to zero and can be cleared | Finance |
| 3 | `goods_not_invoiced` | Only a goods receipt exists | Procurement |
| 4 | `invoiced_not_received` | Only an invoice exists | Receiving |
| 5 | `quantity_difference` | Quantity does not net | Receiving |
| 6 | `price_difference` | Quantity nets, value does not | Procurement |
| 7 | `needs_judgement` | No mechanical cause. A person reads the PO | Finance |

Two ordering decisions carry real weight.

**Balanced lines are checked first**, because they are the cheapest and most common, and because leaving them mixed into the ageing report makes the account look like an exposure it is not.

**Quantity is checked before price.** A short delivery moves both quantity and value. Classify it on value first and you send it to Procurement to argue about pricing, when the actual question is for Receiving and it is "did we get 95 or 100?". That one is a test:

```python
def test_quantity_is_checked_before_price():
    grp = g(item("GR", -100, -54_000, ...), item("IR", 95, 51_300, ...))
    assert classify(grp) == "quantity_difference"
```

## Where the model is used

Only on `needs_judgement`, `goods_not_invoiced` and `invoiced_not_received`. It is handed one PO line and its postings, never the account, and it is told explicitly that **"unclear" is a correct answer**:

> "unclear" is a correct answer. Say it, set confidence low, and name what you would need to resolve it. Never invent a plausible cause to look useful.

It is also forbidden from proposing a write-off, and its `owner` is validated against the four teams the report routes to, so it cannot invent a fifth.

With no `ANTHROPIC_API_KEY` the deterministic action table carries every line and the report still ships.

## Write-offs

`writeoff_candidate` is advisory and narrow: small (under the limit you pass), old (over 90 days), and not already balancing. Nothing in this repo posts an `MR11`, a journal, or anything else to any system. A write-off is a human decision with a value threshold attached to someone's name.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000     # then open http://127.0.0.1:8000
pytest -q                                      # 31 passed
```

Optional, for Claude triage on the exceptions: `export ANTHROPIC_API_KEY=sk-ant-...`

## Input format

Export open items on the GR/IR account (`FBL3N`, or `MB5S` for the PO view) to CSV:

```
doc_id,po,po_line,kind,qty,value,posted_on,vendor,assignment,text
```

`kind` is `GR` or `IR`. Sign convention: **goods receipt negative, invoice positive**, so a PO line that nets to zero sums to zero. That makes every test an assertion about a single number.

## API

| Method | Path | Does |
|---|---|---|
| `GET` | `/` | Demo page |
| `GET` | `/healthz` | Liveness |
| `POST` | `/api/demo` | Runs the synthetic sample |
| `POST` | `/api/triage` | Your `open_items` CSV, with optional `asof` and `writeoff_limit` |

## FAQ

**Does this touch SAP?** No. It reads a CSV export and returns a report. There is no connector on purpose: an export is auditable, and a live connection to the ledger is a much larger security conversation than this tool deserves.

**Why not let a model do the matching?** Because netting is arithmetic and a model right 99% of the time is wrong on a balance sheet. You can regression test a rule. You cannot regression test a vibe.

**Can it clear items automatically?** No, and it should not. The useful output is a shorter list with a named owner against each line. An aged GR/IR item with no owner is the reason the account never gets smaller.

**Deploying it anywhere?** Set `GRIR_API_TOKEN` and send `Authorization: Bearer <token>`. Every exception line can cost a model call. Other limits: `GRIR_MAX_BYTES` (4 MB), `GRIR_MAX_ROWS` (50,000), `GRIR_MAX_TRIAGE` (25 model calls per run, the tail falls back to rules).

## Licence

Apache-2.0.

---

Built by [Arpita Tiwari](https://www.linkedin.com/in/arpita-tiwari-5b955a307). FP&A and record to report by day, agents for finance workflows in my own time. Tell me where the logic breaks.
