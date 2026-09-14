"""End-to-end pipeline test in mock mode: the 4-candidate demo contract."""
import os
from decimal import Decimal

os.environ["MODEL_PROVIDER"] = "mock"

from src.pipeline import Pipeline

BILL = "data/synthetic_bill.json"
EOB = "data/synthetic_eob.json"


def test_demo_contract():
    p = Pipeline()
    res = p.run(BILL, EOB)

    assert len(res.candidates) == 4
    kept = [r for r in res.reviewed if r.verdict == "KEEP"]
    rejected = [r for r in res.reviewed if r.verdict == "REJECT"]
    assert len(kept) == 3
    assert len(rejected) == 1
    assert rejected[0].candidate.finding_id == "F-BUNDLE-36415"
    # the rejection must be evidence-based, not a shrug
    assert "NCCI" in rejected[0].reason

    # every reviewer decision called at least one real tool
    for r in res.reviewed:
        assert len(r.tools_called) >= 1, r.candidate.finding_id

    # claim delta
    assert res.bill_total == Decimal("7842.00")
    assert res.eob_allowed == Decimal("6000.00")
    assert res.delta == Decimal("1842.00")

    # draft cites evidence and carries the disclaimer
    assert "Bill p.1" in res.draft
    assert "Not legal or insurance advice" in res.draft

    # trace covers the full loop incl. the approval gate
    kinds = [t.kind for t in res.trace]
    assert "gate" in kinds
    agents = {t.agent for t in res.trace}
    assert {"Extractor", "Checker", "Reviewer", "Drafter", "ApprovalGate"} <= agents
