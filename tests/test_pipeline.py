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


def test_the_model_is_never_called_without_a_key():
    d = run(ITEMS, asof=ASOF)
    assert d["summary"]["sent_to_model"] == 0
    assert all(r["triaged_by"] == "rules" for r in d["lines"])


def test_lines_are_ranked_by_exposure_so_the_biggest_number_is_first():
    rows = run(ITEMS, asof=ASOF)["lines"]
    assert rows == sorted(rows, key=lambda r: (-r["exposure"], -r["age_days"]))
