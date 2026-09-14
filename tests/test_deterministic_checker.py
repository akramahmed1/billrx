"""Tests for the deterministic checker. No LLM, no network, no AWS."""
from decimal import Decimal

from src.deterministic_checker import (
    check_bill_total,
    check_duplicates,
    check_patient_balance,
    check_possible_bundle,
    check_unbundling,
    run_all_checks,
)
from src.models import BillLine, EOBLine


def L(no, code, amt, date="2026-08-14", desc="test"):
    return BillLine(line_no=no, code=code, description=desc, date=date, amount=Decimal(amt))


def E(code, owes, carc="CO-45", billed="100.00", allowed="80.00", adj="20.00"):
    return EOBLine(code=code, billed=Decimal(billed), allowed=Decimal(allowed),
                   adjustment=Decimal(adj), carc=carc, patient_owes=Decimal(owes))


def test_bill_total_match():
    assert check_bill_total([L(1, "99283", "100.00")], Decimal("100.00")) == []


def test_bill_total_mismatch():
    out = check_bill_total([L(1, "99283", "100.00")], Decimal("120.00"))
    assert len(out) == 1 and out[0].amount_at_stake == Decimal("20.00")


def test_duplicate_detection():
    out = check_duplicates([L(1, "80053", "620.00"), L(2, "80053", "620.00")])
    assert len(out) == 1
    assert out[0].kind == "duplicate"
    assert "line 1" in out[0].evidence[0] and "line 2" in out[0].evidence[1]


def test_no_duplicate_different_dates():
    out = check_duplicates([L(1, "80053", "620.00", date="2026-08-14"),
                            L(2, "80053", "620.00", date="2026-08-15")])
    assert out == []


def test_unbundling_pair():
    out = check_unbundling([L(2, "80053", "620.00"), L(4, "80048", "290.00")])
    assert len(out) == 1 and out[0].kind == "unbundling"
    assert out[0].amount_at_stake == Decimal("290.00")


def test_possible_bundle_heuristic():
    out = check_possible_bundle([L(1, "99283", "2400.00"), L(6, "36415", "90.00")])
    assert len(out) == 1 and out[0].finding_id == "F-BUNDLE-36415"


def test_patient_balance_discrepancy():
    out = check_patient_balance([L(1, "99283", "2400.00")],
                                [E("99283", "642.00")], Decimal("2484.00"))
    assert len(out) == 1
    assert out[0].amount_at_stake == Decimal("1842.00")


def test_run_all_checks_contract():
    lines = [L(1, "99283", "2400.00"), L(2, "80053", "620.00"), L(3, "80053", "620.00"),
             L(4, "80048", "290.00"), L(6, "36415", "90.00")]
    eob = [E("99283", "642.00")]
    out = run_all_checks(lines, eob, Decimal("4020.00"), Decimal("2484.00"))
    ids = {f.finding_id for f in out}
    assert ids == {"F-DUP-80053", "F-UNB-80048-80053", "F-BUNDLE-36415", "F-BAL"}
