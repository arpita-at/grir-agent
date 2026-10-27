"""FastAPI wrapper. Returns a report. Posts nothing to any system, ever."""
from __future__ import annotations

import csv
import hmac
import io
import os
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from .grir import OpenItem, load
from .pipeline import run

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
MAX_BYTES = int(os.environ.get("GRIR_MAX_BYTES", 4 * 1024 * 1024))
MAX_ROWS = int(os.environ.get("GRIR_MAX_ROWS", 50_000))
TOKEN = os.environ.get("GRIR_API_TOKEN")

app = FastAPI(title="grir-agent", version="0.1.0",
              description="GR/IR open item triage. Rules first, a model only on the real exceptions.")


def auth(authorization: str | None = Header(default=None)) -> None:
    """No token set means local use. Set GRIR_API_TOKEN before exposing this, or
    every exception line can cost a model call on somebody else's bill."""
    if not TOKEN:
        return
    if not hmac.compare_digest(authorization or "", f"Bearer {TOKEN}"):
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (Path(__file__).resolve().parent / "index.html").read_text(encoding="utf-8")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/api/demo", dependencies=[Depends(auth)])
def demo() -> JSONResponse:
    return JSONResponse(run(load(SAMPLES / "open_items.csv"), asof=date(2026, 7, 31)))


@app.post("/api/triage", dependencies=[Depends(auth)])
async def triage_upload(open_items: UploadFile = File(...),
                        asof: str | None = None,
                        writeoff_limit: float = 1_000.0) -> JSONResponse:
    if writeoff_limit < 0:
        raise HTTPException(422, "writeoff_limit must be zero or more")
    raw = await open_items.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, f"open_items is larger than {MAX_BYTES} bytes")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if len(rows) > MAX_ROWS:
        raise HTTPException(413, f"open_items has more than {MAX_ROWS} rows")
    try:
        items = [OpenItem(doc_id=r["doc_id"].strip(), po=r["po"].strip(),
                          po_line=r["po_line"].strip(), kind=r["kind"].strip().upper(),
                          qty=float(r["qty"]), value=float(r["value"]),
                          posted_on=date.fromisoformat(r["posted_on"].strip()),
                          vendor=r["vendor"].strip(), assignment=r["assignment"].strip(),
                          text=r.get("text", "").strip())
                 for r in rows]
    except (KeyError, ValueError) as e:
        raise HTTPException(422, f"Bad open_items CSV: {e}")
    when = date.fromisoformat(asof) if asof else date.today()
    return JSONResponse(run(items, asof=when, writeoff_limit=writeoff_limit))
