"""Deterministic checker. Pure Python, no LLM. THE MODEL NEVER CALCULATES MONEY.

Takes extracted bill lines + EOB records and produces CandidateFindings:
hypotheses with exact citations, never verdicts. The Reviewer agent decides.
"""
from __future__ import annotations

from decimal import Decimal

from datetime import date
from itertools import combinations

from .models import BillLine, CandidateFinding, EOBLine
from .refdata import NCCI_BYPASS_MODIFIERS, ReferenceData, get_reference_data

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


def _dos(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def check_unbundling(lines: list[BillLine],
                     refdata: ReferenceData | None = None) -> list[CandidateFinding]:
    """NCCI PTP edits between codes billed on the same date of service.

    Uses the edit active on that date. Indicator "1" edits are bypassed when the
    component line carries an NCCI-associated modifier; indicator "0" edits can
    never be bypassed; indicator "9" edits are not applicable.
    """
    ref = refdata or get_reference_data()
    findings: list[CandidateFinding] = []
    seen: set[tuple[str, str]] = set()
    by_date: dict[str, list[BillLine]] = {}
    for ln in lines:
        by_date.setdefault(ln.date, []).append(ln)
    for dos_str, day_lines in by_date.items():
        codes = sorted({ln.code for ln in day_lines})
        for a, b in combinations(codes, 2):
            edit = ref.ptp_edit(a, b, _dos(dos_str))
            if edit is None or edit.modifier_indicator == "9":
                continue
            component, comprehensive = edit.column2, edit.column1
            comp = [ln for ln in day_lines if ln.code == component]
            if edit.modifier_indicator == "1":
                comp = [ln for ln in comp if not (set(ln.modifiers) & NCCI_BYPASS_MODIFIERS)]
            if not comp or (component, comprehensive) in seen:
                continue
            seen.add((component, comprehensive))
            pages = sorted({ln.page for ln in comp})
            question = (
                "Was a modifier documented to justify billing these two codes together? "
                "If not, can the component charge be reviewed?"
                if edit.modifier_indicator == "1" else
                "NCCI does not allow these two codes to be billed together on the same "
                "date, even with a modifier. Can the component charge be reviewed?")
            findings.append(CandidateFinding(
                finding_id=f"F-UNB-{component}-{comprehensive}",
                kind="unbundling",
                title=f"Possible unbundling: {component} billed alongside {comprehensive}",
                question=question,
                evidence=[f"Bill p.{','.join(map(str, pages))}, line(s) "
                          f"{', '.join(str(ln.line_no) for ln in comp)} (code {component})",
                          f"NCCI relationship: {edit.rationale}"],
                amount_at_stake=sum((ln.amount for ln in comp), Decimal("0")),
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
                   stated_total: Decimal, statement_balance: Decimal,
                   refdata: ReferenceData | None = None) -> list[CandidateFinding]:
    findings: list[CandidateFinding] = []
    findings += check_bill_total(lines, stated_total)
    findings += check_duplicates(lines)
    findings += check_unbundling(lines, refdata)
    findings += check_possible_bundle(lines)
    findings += check_patient_balance(lines, eob, statement_balance)
    return findings
