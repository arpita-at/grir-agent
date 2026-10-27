from datetime import date

from app.grir import load
from app.pipeline import run

ASOF = date(2026, 7, 31)
ITEMS = load("samples/open_items.csv")


def test_the_sample_account_is_mostly_noise():
    """The finding the whole tool exists to surface: most aged GR/IR lines are
    already balanced and are only sitting there because clearing cannot group them."""
    d = run(ITEMS, asof=ASOF)
    assert d["summary"]["noise_lines"] >= 4
    assert d["summary"]["noise_share"] > 0.3


def test_open_exposure_excludes_lines_that_already_net_to_zero():
    d = run(ITEMS, asof=ASOF)
    zeroed = [r for r in d["lines"] if r["category"] in {"assignment_mismatch", "clearable"}]
    assert all(r["exposure"] == 0.0 for r in zeroed)
    assert d["summary"]["open_exposure"] == sum(
        r["exposure"] for r in d["lines"]
        if r["category"] not in {"assignment_mismatch", "clearable"})


def test_every_line_gets_a_named_owner():
    """An aged GR/IR item with no owner is why the account never gets smaller."""
    for r in run(ITEMS, asof=ASOF)["lines"]:
        assert r["owner"] in {"Procurement", "Receiving", "Finance",
                              "Finance systems", "Vendor"}
        assert r["action"]


def test_nothing_that_still_balances_is_ever_a_writeoff_candidate():
    for r in run(ITEMS, asof=ASOF)["lines"]:
        if r["category"] in {"assignment_mismatch", "clearable"}:
            assert r["writeoff_candidate"] is False


def test_writeoff_candidates_are_small_and_old_only():
    d = run(ITEMS, asof=ASOF, writeoff_limit=1_000.0)
    for r in d["lines"]:
        if r["writeoff_candidate"]:
            assert r["exposure"] <= 1_000.0
            assert r["age_days"] > 90


def test_the_model_is_never_called_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    d = run(ITEMS, asof=ASOF)
    assert d["summary"]["sent_to_model"] == 0
    assert all(r["triaged_by"] == "rules" for r in d["lines"])


def test_lines_are_ranked_by_exposure_so_the_biggest_number_is_first():
    rows = run(ITEMS, asof=ASOF)["lines"]
    assert rows == sorted(rows, key=lambda r: (-r["exposure"], -r["age_days"]))


def test_a_model_that_fails_every_call_still_runs_the_budget_down(monkeypatch):
    """Counting successes instead of attempts turns the cap into no cap: a bad key
    never decrements the budget, so every eligible line gets another doomed call."""
    import app.triage as t
    calls = []

    def always_fails(g, asof):
        calls.append(g.po)
        return None

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(t, "claude_triage", always_fails)
    monkeypatch.setattr("app.pipeline.MAX_TRIAGE", 1)
    d = run(ITEMS, asof=ASOF)
    assert len(calls) == 1
    assert d["summary"]["sent_to_model"] == 1


def test_the_budget_is_only_spent_on_lines_a_model_could_help_with(monkeypatch):  # noqa: D103
    import app.triage as t
    seen = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(t, "claude_triage",
                        lambda g, asof: seen.append(g.po) or
                        {"cause": "c", "owner": "Finance", "action": "a", "confidence": "low"})
    d = run(ITEMS, asof=ASOF)
    cats = {(r["po"], r["category"]) for r in d["lines"]}
    for po in seen:
        assert any(p == po and c in t.TRIAGEABLE for p, c in cats)


def test_attempted_never_leaks_into_the_report():
    for r in run(ITEMS, asof=ASOF)["lines"]:
        assert "attempted" not in r
