from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz():
    assert client.get("/healthz").json() == {"ok": True}


def test_demo_runs_end_to_end():
    d = client.post("/api/demo").json()
    assert d["summary"]["lines"] > 0
    assert sum(c["lines"] for c in d["by_category"].values()) == d["summary"]["lines"]


def test_a_bad_csv_is_refused_with_a_reason_not_a_stack_trace():
    files = {"open_items": ("x.csv", b"wrong,headers\n1,2\n", "text/csv")}
    r = client.post("/api/triage", files=files)
    assert r.status_code == 422
    assert "Bad open_items CSV" in r.json()["detail"]


def test_oversized_upload_is_refused():
    import app.main as m
    big = b"doc_id,po,po_line,kind,qty,value,posted_on,vendor,assignment,text\n" + \
          b"d,4500000,10,GR,-1,-1,2026-01-01,V,A,t\n" * 200_000
    assert len(big) > m.MAX_BYTES
    r = client.post("/api/triage", files={"open_items": ("x.csv", big, "text/csv")})
    assert r.status_code == 413


def test_token_auth_rejects_wrong_and_accepts_right(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "TOKEN", "s3cret")
    assert client.post("/api/demo").status_code == 401
    assert client.post("/api/demo", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.post("/api/demo", headers={"Authorization": "Bearer s3cret"}).status_code == 200
