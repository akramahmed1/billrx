"""Deterministic lookup tools for the Reviewer agent.

Each tool returns FACTS, never verdicts. The agent reasons over the facts and
decides KEEP or REJECT. These same functions are wired as Strands @tools in
live mode and called directly by the scripted fallback in mock mode.
"""
from __future__ import annotations

from ..refdata import get_reference_data


def lookup_ncci_edit(code_a: str, code_b: str) -> dict:
    """Look up whether two CPT codes form an NCCI unbundling edit pair.

    Returns the policy FACT; it does not judge the bill.
    """
    a, b = code_a.strip(), code_b.strip()
    ref = get_reference_data()
    edit = ref.ptp_edit(a, b)
    if edit is None or edit.modifier_indicator == "9":
        return {"match": False, "source": ref.source,
                "detail": f"No NCCI unbundling edit exists between {a} and {b}."}
    return {
        "match": True,
        "source": ref.source,
        "component_code": edit.column2,
        "comprehensive_code": edit.column1,
        "relationship": "component-to-comprehensive",
        "description": edit.rationale,
        "modifier_bypass_possible": edit.modifier_indicator == "1",
        "note": ("Both may be billed together only with a documented modifier (e.g. 59/XS)."
                 if edit.modifier_indicator == "1"
                 else "No modifier can bypass this edit."),
        "effective": edit.effective.isoformat(),
    }


def lookup_eob_remark(carc_code: str) -> dict:
    """Explain a Claim Adjustment Reason Code from the EOB. Facts only."""
    code = carc_code.strip().upper()
    explanation = get_reference_data().carc(code)
    if explanation:
        return {"code": code, "found": True, "explanation": explanation}
    return {"code": code, "found": False,
            "explanation": "Unknown or unlisted remark code."}


def inspect_evidence(citation: str, bill_text: str) -> dict:
    """Return the bill lines a citation points at, so the agent can verify context.

    Citations look like "Bill p.1, lines 2 and 3". Only text that exists in the
    bill is returned; nothing is invented. Falls back to the start of the bill
    when no line numbers can be read from the citation.
    """
    import re

    wanted = {int(n) for n in re.findall(r"\b(\d+)\b", citation.split(",", 1)[-1])}
    matched = [ln for ln in bill_text.splitlines()
               if (m := re.match(r"Line (\d+):", ln)) and int(m.group(1)) in wanted]
    context = "\n".join(matched) if matched else bill_text[:2000]
    return {"citation": citation, "context": context, "matched_lines": len(matched)}
