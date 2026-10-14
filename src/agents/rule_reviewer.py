"""Deterministic rule-based Reviewer for findings outside the demo script.

Mock mode used to know only the four demo finding ids, so any real bill crashed
it. This reviewer handles every finding kind with the same lookup tools and the
same evidence standard, so mock mode (and the live-agent fallback) work on real
bills. Rules:

  duplicate        KEEP: same code, date and amount twice is always worth asking.
  unbundling       KEEP if the NCCI lookup confirms an active edit, else REJECT.
  discrepancy      KEEP: the arithmetic was done in deterministic code.
  possible_bundle  KEEP only if the NCCI lookup finds an edit, else REJECT.
"""
from __future__ import annotations

import re
from typing import Callable

from ..models import CandidateFinding

EM_CODE_RE = re.compile(r"\b(9928[1-5]|9920[2-5]|9921[1-5]|9922[1-3]|9923[1-3])\b")


def _codes_from_id(finding_id: str) -> list[str]:
    return re.findall(r"\b([0-9A-Z]\d{3}[0-9A-Z])\b", finding_id)


def rule_review(c: CandidateFinding, tools: dict[str, Callable], bill_text: str,
                emit: Callable[[str, str, str], None]) -> dict:
    called: list[str] = []

    def call(name: str, **kwargs):
        emit("Reviewer", "tool", f"calling {name}({kwargs})")
        result = tools[name](**kwargs, bill_text=bill_text) if name == "inspect_evidence" \
            else tools[name](**kwargs)
        called.append(name)
        emit("Reviewer", "tool", f"{name} returned: {str(result)[:160]}")
        return result

    if c.kind == "duplicate":
        call("inspect_evidence", citation=c.evidence[0] if c.evidence else c.title)
        verdict, reason = "KEEP", (
            "The same code was billed twice on the same date for the same amount. "
            "Worth asking the billing office whether these were separate services.")
    elif c.kind == "unbundling":
        codes = _codes_from_id(c.finding_id)
        res = call("lookup_ncci_edit", code_a=codes[0], code_b=codes[1]) if len(codes) >= 2 \
            else {"match": False}
        if res.get("match"):
            verdict, reason = "KEEP", (
                f"NCCI lists {res['component_code']} as a component of "
                f"{res['comprehensive_code']}, and no bypass modifier was found on the "
                "component line. Worth asking whether the component charge should stand.")
        else:
            verdict, reason = "REJECT", (
                "The NCCI lookup found no active edit for this pair, so there is not "
                "enough evidence to question it.")
    elif c.kind == "possible_bundle":
        codes = _codes_from_id(c.finding_id)
        em = EM_CODE_RE.search(bill_text)
        res = call("lookup_ncci_edit", code_a=codes[0], code_b=em.group(1)) if codes and em \
            else {"match": False}
        if res.get("match"):
            verdict, reason = "KEEP", "NCCI lists an edit for this pair. Worth asking."
        else:
            verdict, reason = "REJECT", (
                "No NCCI edit exists between these codes, so the line is separately "
                "payable. Insufficient evidence to question it.")
    else:  # discrepancy and anything new: math is deterministic, ask for reconciliation
        carcs = sorted(set(re.findall(r"\b(?:CO|PR|OA|PI)-\d+\b", " ".join(c.evidence))))
        for code in carcs[:3]:
            call("lookup_eob_remark", carc_code=code)
        if not carcs:
            call("inspect_evidence", citation=c.evidence[0] if c.evidence else c.title)
        verdict, reason = "KEEP", (
            "The amounts do not reconcile, and that arithmetic was checked in "
            "deterministic code. Worth asking for a reconciliation before paying.")

    emit("Reviewer", "decision", f"{c.finding_id}: {verdict} - {reason[:120]}")
    return {"verdict": verdict, "reason": reason, "tools_called": called}
