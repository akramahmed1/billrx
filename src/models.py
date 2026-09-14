"""Core data models. All money is Decimal. The model never calculates money;
arithmetic lives in deterministic_checker.py."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class BillLine:
    line_no: int
    code: str
    description: str
    date: str
    amount: Decimal
    page: int = 1


@dataclass(frozen=True)
class EOBLine:
    code: str
    billed: Decimal
    allowed: Decimal
    adjustment: Decimal
    carc: str  # Claim Adjustment Reason Code, e.g. CO-45
    patient_owes: Decimal


@dataclass(frozen=True)
class CandidateFinding:
    """A machine-generated hypothesis. Not a verdict. The Reviewer decides."""
    finding_id: str
    kind: str  # duplicate | unbundling | discrepancy | possible_bundle
    title: str
    question: str  # investigative question for the billing office, never an accusation
    evidence: list[str]  # exact citations, e.g. "Bill p.1, lines 2 and 3"
    amount_at_stake: Decimal


@dataclass
class ReviewedFinding:
    candidate: CandidateFinding
    verdict: str  # KEEP | REJECT
    reason: str
    tools_called: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TraceEvent:
    seq: int
    agent: str
    kind: str  # start | tool | decision | gate | done
    text: str
