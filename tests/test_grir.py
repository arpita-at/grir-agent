"""The classifier. Getting the order wrong sends work to the wrong team."""
from datetime import date

import pytest

from app.grir import Group, OpenItem, age_bucket, ageing, classify, group, nets_to_zero

ASOF = date(2026, 7, 31)


def item(kind, qty, value, posted, assignment="X", po="4500000", line="10", vendor="V", text=""):
    return OpenItem(f"doc-{kind}-{qty}", po, line, kind, qty, value,
                    date.fromisoformat(posted), vendor, assignment, text)


def g(*items):
    return Group(items[0].po, items[0].po_line, list(items))


def test_a_balanced_line_with_different_assignments_is_the_noise_bucket():
    """The headline finding. It already nets to zero. F.13 groups on the assignment
    field and cannot see it, so it ages forever looking like a real exposure."""
    grp = g(item("GR", -40, -128_000, "2026-04-18", assignment="GR20260418"),
            item("IR", 40, 128_000, "2026-04-30", assignment="INV-SL-88120"))
    assert nets_to_zero(grp)
    assert classify(grp) == "assignment_mismatch"
    assert grp.exposure == 0.0


def test_a_balanced_line_with_one_assignment_is_simply_clearable():
    grp = g(item("GR", -10, -1_000, "2026-04-18", assignment="PO4500000"),
            item("IR", 10, 1_000, "2026-04-30", assignment="PO4500000"))
    assert classify(grp) == "clearable"


def test_quantity_is_checked_before_price():
    """A short delivery moves both quantity and value. Leading with price sends it
    to Procurement when the question is actually for Receiving."""
    grp = g(item("GR", -100, -54_000, "2026-02-09", assignment="PO1"),
            item("IR", 95, 51_300, "2026-02-27", assignment="PO1"))
    assert classify(grp) == "quantity_difference"


def test_same_quantity_different_value_is_a_price_difference():
    grp = g(item("GR", -80, -240_000, "2026-01-22", assignment="PO1"),
            item("IR", 80, 252_800, "2026-02-05", assignment="PO1"))
    assert classify(grp) == "price_difference"
    assert grp.exposure == pytest.approx(12_800.0)


def test_one_sided_lines_are_named_by_the_side_that_is_missing():
    assert classify(g(item("GR", -6, -412_800, "2026-03-11"))) == "goods_not_invoiced"
    assert classify(g(item("IR", 30, 74_400, "2026-06-14"))) == "invoiced_not_received"


def test_rounding_inside_tolerance_does_not_create_work():
    grp = g(item("GR", -10, -1_000.00, "2026-04-18", assignment="PO1"),
            item("IR", 10, 1_000.40, "2026-04-30", assignment="PO1"))
    assert nets_to_zero(grp)
    assert classify(grp) == "clearable"


def test_exposure_is_always_positive_whichever_way_the_line_leans():
    over = g(item("GR", -10, -1_000, "2026-01-01", assignment="A"),
             item("IR", 10, 1_500, "2026-01-02", assignment="A"))
    under = g(item("GR", -10, -1_500, "2026-01-01", assignment="A"),
              item("IR", 10, 1_000, "2026-01-02", assignment="A"))
    assert over.exposure == 500.0 == under.exposure


def test_age_runs_from_the_oldest_posting_not_the_newest():
    grp = g(item("GR", -10, -1_000, "2026-01-10", assignment="A"),
            item("IR", 10, 1_200, "2026-07-20", assignment="A"))
    assert grp.oldest == date(2026, 1, 10)
    assert grp.age(ASOF) == 202


@pytest.mark.parametrize("days,bucket", [
    (0, "0-30"), (30, "0-30"), (31, "31-60"), (60, "31-60"),
    (61, "61-90"), (90, "61-90"), (91, "91-180"), (180, "91-180"), (181, "180+"),
])
def test_age_buckets_do_not_overlap_or_leave_gaps(days, bucket):
    assert age_bucket(days) == bucket


def test_grouping_is_by_po_line_not_by_po():
    """Two lines on one PO are two different conversations with two different teams."""
    items = [item("GR", -5, -500, "2026-01-01", po="P1", line="10"),
             item("IR", 5, 500, "2026-01-02", po="P1", line="10"),
             item("GR", -7, -700, "2026-01-01", po="P1", line="20")]
    got = group(items)
    assert len(got) == 2
    assert {(x.po, x.po_line) for x in got} == {("P1", "10"), ("P1", "20")}


def test_ageing_totals_every_line_exactly_once():
    items = [item("GR", -10, -1_000, "2026-07-20", po="P1"),
             item("GR", -10, -5_000, "2026-01-02", po="P2"),
             item("GR", -10, -2_000, "2025-06-02", po="P3")]
    report = ageing(group(items), ASOF)
    assert sum(b["lines"] for b in report.values()) == 3
    assert sum(b["exposure"] for b in report.values()) == pytest.approx(8_000.0)
