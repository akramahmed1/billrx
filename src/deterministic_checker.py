"""Deterministic checker. Pure Python, no LLM. THE MODEL NEVER CALCULATES MONEY.

Takes extracted bill lines + EOB records and produces CandidateFindings:
hypotheses with exact citations, never verdicts. The Reviewer agent decides.
"""
from __future__ import annotations

from decimal import Decimal

from .models import BillLine, CandidateFinding, EOBLine

# Minimal NCCI-style pair table, scoped to the synthetic demo scenario.
# (code_a, code_b) -> relationship note. The Reviewer interprets these via tools.
NCCI_PAIRS = {
    ("80048", "80053"): "Basic Metabolic Panel (80048) is a component of "
                        "Comprehensive Metabolic Panel (80053). Billing both together "
                        "may be unbundling unless a modifier is documented.",
}

# E/M codes that make the checker raise a *weak* possible-bundle hypothesis
# for venipuncture. Designed to be rejected by the Reviewer (honest negative).
EM_CODES = {"99281", "99282", "99283", "99284", "99285"}


def check_bill_total(lines: list[BillLine], stated_total: Decimal) -> list[CandidateFinding]:
    total = sum((ln.amount for ln in lines), Decimal("0"))
    if total != stated_total:
        return [CandidateFinding(
            finding_id="F-TOTAL",
            kind="discrepancy",
            title="Bill total does not match the sum of line items",
            question="Can you confirm the correct statement total? The line items add up "
                     "to a different amount than the printed total.",
            evidence=[f"Bill p.1, lines {lines[0].line_no}-{lines[-1].line_no}",
                      f"Stated total ${stated_total:,.2f}"],
            amount_at_stake=abs(total - stated_total),
        )]
    return []


def check_duplicates(lines: list[BillLine]) -> list[CandidateFinding]:
    findings = []
    seen: dict[tuple[str, str, Decimal], BillLine] = {}
    for ln in lines:
        key = (ln.code, ln.date, ln.amount)
        if key in seen:
            first = seen[key]
            findings.append(CandidateFinding(
                finding_id=f"F-DUP-{ln.code}",
                kind="duplicate",
                title=f"Possible duplicate charge: {ln.code} {ln.description}",
                question="Can you confirm whether these two charges represent separate "
                         "services on the same date?",
                evidence=[f"Bill p.{first.page}, line {first.line_no}",
                          f"Bill p.{ln.page}, line {ln.line_no}",
                          f"Same code {ln.code}, same date {ln.date}, same amount ${ln.amount:,.2f}"],
                amount_at_stake=ln.amount,
            ))
        else:
            seen[key] = ln
    return findings


def check_unbundling(lines: list[BillLine]) -> list[CandidateFinding]:
    findings = []
    codes = {ln.code for ln in lines}
    for (component, comprehensive), note in NCCI_PAIRS.items():
        if component in codes and comprehensive in codes:
            comp_lines = [str(ln.line_no) for ln in lines if ln.code == component]
            findings.append(CandidateFinding(
                finding_id=f"F-UNB-{component}-{comprehensive}",
                kind="unbundling",
                title=f"Possible unbundling: {component} billed alongside {comprehensive}",
                question="Was a modifier documented to justify billing these two codes "
                         "together? If not, can the component charge be reviewed?",
                evidence=[f"Bill p.1, line(s) {', '.join(comp_lines)} (code {component})",
                          f"NCCI relationship: {note}"],
                amount_at_stake=sum(ln.amount for ln in lines if ln.code == component),
            ))
    return findings


def check_possible_bundle(lines: list[BillLine]) -> list[CandidateFinding]:
    """Weak heuristic, intentionally. The Reviewer is expected to reject it."""
    findings = []
    em_present = any(ln.code in EM_CODES for ln in lines)
    for ln in lines:
        if ln.code == "36415" and em_present:
            findings.append(CandidateFinding(
                finding_id="F-BUNDLE-36415",
                kind="possible_bundle",
                title="Venipuncture (36415) billed with an emergency visit",
                question="Is the venipuncture charge separately payable alongside the "
                         "emergency department visit?",
                evidence=[f"Bill p.{ln.page}, line {ln.line_no}"],
                amount_at_stake=ln.amount,
            ))
    return findings


def check_patient_balance(lines: list[BillLine], eob: list[EOBLine],
                          statement_balance: Decimal) -> list[CandidateFinding]:
    eob_owes = sum((r.patient_owes for r in eob), Decimal("0"))
    if statement_balance > eob_owes:
        cites = [f"EOB line {r.code}: patient owes ${r.patient_owes:,.2f} ({r.carc})" for r in eob]
        return [CandidateFinding(
            finding_id="F-BAL",
            kind="discrepancy",
            title="Statement balance exceeds the EOB patient responsibility",
            question="The statement asks for more than the explanation of benefits says "
                     "is owed. Can you reconcile the difference before I pay?",
            evidence=[f"Statement balance: ${statement_balance:,.2f}",
                      f"EOB patient responsibility: ${eob_owes:,.2f}"] + cites,
            amount_at_stake=statement_balance - eob_owes,
        )]
    return []


def run_all_checks(lines: list[BillLine], eob: list[EOBLine],
                   stated_total: Decimal, statement_balance: Decimal) -> list[CandidateFinding]:
    findings: list[CandidateFinding] = []
    findings += check_bill_total(lines, stated_total)
    findings += check_duplicates(lines)
    findings += check_unbundling(lines)
    findings += check_possible_bundle(lines)
    findings += check_patient_balance(lines, eob, statement_balance)
    return findings
