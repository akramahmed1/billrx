"""BillRx pipeline: extract -> deterministic check -> reviewer -> draft -> approval.

Trace events are emitted for every stage in both live (Bedrock) and mock mode,
so the UI's event sidebar and the demo video show the same story either way.

Fallback contract (pre-written, not improvised): if the live Reviewer agent
fails to call tools or returns unparseable output, the pipeline falls back to
scripted_review(), which calls the same deterministic tools directly.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from . import deterministic_checker as checker
from .agents import tools as det_tools
from .llm import ScriptedAgent, build_bedrock_model, get_provider
from .models import BillLine, CandidateFinding, EOBLine, ReviewedFinding, TraceEvent

# The 4-candidate demo contract: finding_id -> scripted tool-calling review.
# Used in mock mode and as the pre-written fallback for live mode.
REVIEW_SCRIPT = {
    "F-DUP-80053": {
        "tool_calls": [
            ("inspect_evidence", {"citation": "Bill p.1, lines 2 and 3"}),
            ("lookup_eob_remark", {"carc_code": "CO-97"}),
        ],
        "verdict": "KEEP",
        "reason": "Two identical 80053 charges on the same date, and the EOB allowed "
                  "only one of them (second adjusted under CO-97, included in another "
                  "service). Worth asking the billing office to confirm.",
    },
    "F-UNB-80048-80053": {
        "tool_calls": [
            ("lookup_ncci_edit", {"code_a": "80048", "code_b": "80053"}),
            ("inspect_evidence", {"citation": "Bill p.1, lines 2 and 4"}),
        ],
        "verdict": "KEEP",
        "reason": "NCCI treats 80048 as a component of 80053. Both were billed together "
                  "with no modifier documented. Worth asking whether the component "
                  "charge should stand.",
    },
    "F-BAL": {
        "tool_calls": [
            ("lookup_eob_remark", {"carc_code": "CO-45"}),
        ],
        "verdict": "KEEP",
        "reason": "CO-45 adjustments are contractual and not patient responsibility, "
                  "yet the statement demands $2,484.00 against an EOB patient "
                  "responsibility of $642.00. Worth asking for a reconciliation.",
    },
    "F-BUNDLE-36415": {
        "tool_calls": [
            ("lookup_ncci_edit", {"code_a": "36415", "code_b": "99283"}),
        ],
        "verdict": "REJECT",
        "reason": "No NCCI edit exists between venipuncture (36415) and the emergency "
                  "visit (99283). Routine venipuncture is separately payable. "
                  "Insufficient evidence to question this line.",
    },
}


@dataclass
class PipelineResult:
    bill_total: Decimal
    eob_allowed: Decimal
    statement_balance: Decimal
    eob_owes: Decimal
    delta: Decimal
    candidates: list[CandidateFinding]
    reviewed: list[ReviewedFinding]
    draft: str
    phone_script: str
    trace: list[TraceEvent] = field(default_factory=list)


class Pipeline:
    def __init__(self):
        self.provider = get_provider()
        self._trace: list[TraceEvent] = []
        self._seq = 0

    # ---- trace ----
    def emit(self, agent: str, kind: str, text: str):
        self._seq += 1
        self._trace.append(TraceEvent(seq=self._seq, agent=agent, kind=kind, text=text))

    # ---- load ----
    @staticmethod
    def load(bill_path: str | Path, eob_path: str | Path):
        bill = json.loads(Path(bill_path).read_text())
        eob = json.loads(Path(eob_path).read_text())
        lines = [BillLine(line_no=r["line_no"], code=r["code"], description=r["description"],
                          date=r["date"], amount=Decimal(r["amount"])) for r in bill["lines"]]
        eob_lines = [EOBLine(code=r["code"], billed=Decimal(r["billed"]),
                             allowed=Decimal(r["allowed"]),
                             adjustment=Decimal(r["adjustment"]), carc=r["carc"],
                             patient_owes=Decimal(r["patient_owes"])) for r in eob["lines"]]
        bill_text = "\n".join(
            f"Line {r['line_no']}: {r['code']} {r['description']} ${r['amount']} ({r['date']})"
            for r in bill["lines"])
        return lines, eob_lines, bill, eob, bill_text

    # ---- run ----
    def run(self, bill_path: str | Path, eob_path: str | Path) -> PipelineResult:
        lines, eob_lines, bill, eob, bill_text = self.load(bill_path, eob_path)

        self.emit("Extractor", "start", f"Ingested {len(lines)} line items from bill")
        self.emit("Extractor", "done", f"Ingested {len(eob_lines)} payment records from EOB")

        self.emit("Checker", "start", "Running deterministic checks (code, not the model)")
        candidates = checker.run_all_checks(
            lines, eob_lines,
            stated_total=Decimal(bill["statement_total"]),
            statement_balance=Decimal(bill["statement_balance_due"]))
        self.emit("Checker", "done", f"Produced {len(candidates)} candidate findings")

        reviewed = self._review(candidates, bill_text)

        kept = [r for r in reviewed if r.verdict == "KEEP"]
        self.emit("Drafter", "start", f"Drafting appeal from {len(kept)} retained findings")
        draft = build_appeal_draft(kept, bill, eob)
        phone_script = build_phone_script(kept)
        self.emit("Drafter", "done", "Appeal draft ready")
        self.emit("ApprovalGate", "gate", "Paused. Awaiting human approval before finalizing.")

        bill_total = Decimal(bill["statement_total"])
        eob_allowed = Decimal(eob["total_allowed"])
        statement_balance = Decimal(bill["statement_balance_due"])
        eob_owes = Decimal(eob["patient_responsibility_total"])
        return PipelineResult(
            bill_total=bill_total, eob_allowed=eob_allowed,
            statement_balance=statement_balance, eob_owes=eob_owes,
            delta=statement_balance - eob_owes,
            candidates=candidates, reviewed=reviewed,
            draft=draft, phone_script=phone_script, trace=list(self._trace))

    # ---- review ----
    def _review(self, candidates: list[CandidateFinding], bill_text: str) -> list[ReviewedFinding]:
        tools = {"lookup_ncci_edit": det_tools.lookup_ncci_edit,
                 "lookup_eob_remark": det_tools.lookup_eob_remark,
                 "inspect_evidence": det_tools.inspect_evidence}
        if self.provider == "bedrock":
            try:
                return self._review_live(candidates, tools, bill_text)
            except Exception as exc:  # pre-written fallback, never improvised
                self.emit("Reviewer", "tool",
                          f"Live agent failed ({type(exc).__name__}); using deterministic fallback")
        return self._review_scripted(candidates, tools, bill_text)

    def _review_scripted(self, candidates, tools, bill_text) -> list[ReviewedFinding]:
        agent = ScriptedAgent("Reviewer", REVIEW_SCRIPT, self.emit)
        out = []
        for c in candidates:
            r = agent.review(c.finding_id, tools, bill_text)
            out.append(ReviewedFinding(candidate=c, verdict=r["verdict"],
                                      reason=r["reason"], tools_called=r["tools_called"]))
        return out

    def _review_live(self, candidates, tools, bill_text) -> list[ReviewedFinding]:
        from strands import Agent, tool as strands_tool
        from pydantic import BaseModel, Field
        from typing import Literal

        class ReviewVerdict(BaseModel):
            include_in_appeal_draft: bool = Field(description=(
                "True if a reasonable patient would want this question included "
                "in their appeal letter to the provider or insurer. Answer true "
                "when the evidence raises a question worth asking, even if the "
                "answer is not yet known. Answer false only when the tools show "
                "the finding is factually baseless, for example the codes do not "
                "appear on the bill or all amounts reconcile."))
            reason: str = Field(description=(
                "One or two sentences explaining the decision, phrased as an "
                "investigative question, never an accusation."))
            reason: str = Field(description=(
                "One or two sentences explaining the decision, phrased as an "
                "investigative question, never an accusation."))

        @strands_tool
        def lookup_ncci_edit(code_a: str, code_b: str) -> dict:
            """Look up whether two CPT codes form an NCCI unbundling edit pair.
            Returns the policy fact; it does not judge the bill."""
            return det_tools.lookup_ncci_edit(code_a, code_b)

        @strands_tool
        def lookup_eob_remark(carc_code: str) -> dict:
            """Explain a Claim Adjustment Reason Code from the EOB. Facts only."""
            return det_tools.lookup_eob_remark(carc_code)

        @strands_tool
        def inspect_evidence(citation: str) -> dict:
            """Return the bill text around a citation to verify context."""
            return det_tools.inspect_evidence(citation, bill_text)

        live_tools = [lookup_ncci_edit, lookup_eob_remark, inspect_evidence]
        tool_names = ("lookup_ncci_edit", "lookup_eob_remark", "inspect_evidence")
        seen_tools: set[str] = set()

        def cb(**kwargs):
            try:
                blob = json.dumps(kwargs, default=str)
            except Exception:
                blob = ""
            if "tooluse" in blob.lower():
                for name in tool_names:
                    if name in blob and name not in seen_tools:
                        seen_tools.add(name)
                        self.emit("Reviewer", "tool", f"called {name}")

        agent = Agent(model=build_bedrock_model(), tools=live_tools,
                      callback_handler=cb, name="Reviewer",
                      system_prompt=(
                          "You are a careful billing-review assistant screening "
                          "candidate findings for questions worth investigating. "
                          "You are NOT proving billing errors; the deterministic "
                          "checker already did the math. Your job is to challenge "
                          "each candidate with evidence.\n"
                          "For each candidate finding you MUST call at least one "
                          "lookup tool before deciding. Tools return facts, never "
                          "verdicts. Reason over the facts.\n"
                          "Interpretation guide: a duplicate charge means the same "
                          "CPT code billed twice on the same date. An unbundling "
                          "candidate means two codes with an NCCI edit pair billed "
                          "together; the lookup tells you whether the pair is an "
                          "edit, and the bill text tells you whether a modifier "
                          "justifies it.\n"
                          "When the evidence raises a legitimate question, verdict "
                          "KEEP. Verdict REJECT only when the evidence does not "
                          "support even asking the question.\n"
                          "The appeal draft is a request for clarification, not a "
                          "list of proven errors.\n"
                          "Phrase reasons as investigative questions, never accusations."))
        out = []
        for c in candidates:
            seen_tools.clear()
            mark = len(agent.messages)
            self.emit("Reviewer", "start", f"Challenging {c.finding_id}: {c.title}")
            prompt = (f"Candidate finding: {c.title}\nQuestion: {c.question}\n"
                      f"Evidence: {'; '.join(c.evidence)}\n"
                      f"Amount at stake: ${c.amount_at_stake}\n"
                      f"Bill context:\n{bill_text}\n"
                      "Call the relevant tools, then give your verdict. "
                      "Remember: KEEP means worth investigating and included in "
                      "the appeal draft; REJECT means insufficient support, drop it.")
            result = agent(prompt, structured_output_model=ReviewVerdict)
            called = self._scan_tool_use(agent.messages[mark:], tool_names) | seen_tools
            if not called:
                raise RuntimeError(f"Reviewer did not call any tool for {c.finding_id}")
            v = result.structured_output
            if not isinstance(v, ReviewVerdict):
                raise RuntimeError(f"Reviewer returned no structured verdict for {c.finding_id}")
            verdict = "KEEP" if v.include_in_appeal_draft else "REJECT"
            self.emit("Reviewer", "decision", f"{c.finding_id}: {verdict} - {v.reason[:120]}")
            out.append(ReviewedFinding(candidate=c, verdict=verdict, reason=v.reason,
                                      tools_called=sorted(called)))
        return out

    @staticmethod
    def _scan_tool_use(messages, tool_names: tuple[str, ...]) -> set[str]:
        """Authoritative tool-call check: scan new agent messages for toolUse blocks."""
        found: set[str] = set()
        for m in messages:
            content = m.get("content", []) if isinstance(m, dict) else []
            for block in content:
                if isinstance(block, dict) and "toolUse" in block:
                    name = block["toolUse"].get("name", "")
                    if name in tool_names:
                        found.add(name)
        return found


def build_appeal_draft(kept: list[ReviewedFinding], bill: dict, eob: dict) -> str:
    lines = [
        f"Re: Request for review of statement dated {bill['date_of_service']}",
        f"Patient: {bill['patient']} | Payer: {eob['payer']}",
        "",
        "Dear Billing Department,",
        "",
        "I am writing to ask for a review of the following items on my statement. "
        "For each item I have noted the evidence and a specific question:",
        "",
    ]
    for i, r in enumerate(kept, 1):
        c = r.candidate
        lines += [f"{i}. {c.title} (${c.amount_at_stake})",
                  f"   Evidence: {'; '.join(c.evidence)}",
                  f"   Review note: {r.reason}",
                  f"   Question: {c.question}", ""]
    lines += ["Please respond in writing within 30 days.",
              "",
              "Sincerely,",
              bill["patient"],
              "",
              "---",
              "Draft prepared by BillRx from synthetic demo data. Not legal or insurance advice."]
    return "\n".join(lines)


def build_phone_script(kept: list[ReviewedFinding]) -> str:
    bullets = ["Phone script: what to ask the billing office"]
    for i, r in enumerate(kept, 1):
        bullets.append(f"{i}. {r.candidate.question}")
    bullets.append("Close: 'Can you send the corrected statement in writing?'")
    return "\n".join(bullets)
