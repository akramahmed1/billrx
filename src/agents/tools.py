"""Deterministic lookup tools for the Reviewer agent.

Each tool returns FACTS, never verdicts. The agent reasons over the facts and
decides KEEP or REJECT. These same functions are wired as Strands @tools in
live mode and called directly by the scripted fallback in mock mode.
"""
from __future__ import annotations

# Synthetic NCCI Procedure-to-Procedure edit table, scoped to the demo scenario.
# (component_code, comprehensive_code) -> policy fact.
NCCI_PTP_EDITS = {
    ("80048", "80053"): {
        "relationship": "component-to-comprehensive",
        "description": "Basic Metabolic Panel (80048) is a component of Comprehensive "
                       "Metabolic Panel (80053).",
        "modifier_bypass_possible": True,
        "note": "Both may be billed together only with a documented modifier (e.g. 59/XS).",
    },
    ("43235", "43239"): {
        "relationship": "component-to-comprehensive",
        "description": "Diagnostic EGD (43235) is bundled into EGD with biopsy (43239).",
        "modifier_bypass_possible": True,
        "note": "Both may be billed together only with a documented modifier.",
    },
}

# Synthetic Claim Adjustment Reason Code (CARC) explanations, demo scope.
EOB_CARC_CODES = {
    "CO-45": "Charge exceeds fee schedule / maximum allowable amount. Contractual adjustment; "
             "not the patient's responsibility.",
    "CO-97": "The benefit for this service is included in the payment/allowance for another "
             "service already adjudicated.",
    "PR-1": "Deductible amount. Patient responsibility.",
    "PR-2": "Coinsurance amount. Patient responsibility.",
    "PR-3": "Copayment amount. Patient responsibility.",
}


def lookup_ncci_edit(code_a: str, code_b: str) -> dict:
    """Look up whether two CPT codes form an NCCI unbundling edit pair.

    Returns the policy FACT; it does not judge the bill.
    """
    a, b = code_a.strip(), code_b.strip()
    for pair in ((a, b), (b, a)):
        if pair in NCCI_PTP_EDITS:
            return {"match": True, "component_code": pair[0],
                    "comprehensive_code": pair[1], **NCCI_PTP_EDITS[pair]}
    return {"match": False,
            "detail": f"No NCCI unbundling edit exists between {a} and {b}."}


def lookup_eob_remark(carc_code: str) -> dict:
    """Explain a Claim Adjustment Reason Code from the EOB. Facts only."""
    code = carc_code.strip().upper()
    if code in EOB_CARC_CODES:
        return {"code": code, "found": True, "explanation": EOB_CARC_CODES[code]}
    return {"code": code, "found": False,
            "explanation": "Unknown or unlisted remark code."}


def inspect_evidence(citation: str, bill_text: str) -> dict:
    """Return the raw bill text around a citation so the agent can verify context.

    In the demo this searches the synthetic bill text; it never invents content.
    """
    return {"citation": citation, "context": bill_text[:2000]}
