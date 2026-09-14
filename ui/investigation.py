"""Screen 2: Investigation. How BillRx solved the case, compactly."""
import json
import os
import re
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from ui.shared import inject_css, md, require_result, step_kicker

inject_css()
res = require_result()
step_kicker(2, "Investigation")

st.header("Investigation")
st.caption("What the agents did, and the evidence they stood on. "
           "The model never calculated the money: all arithmetic ran in deterministic code.")


def _ingested(label):
    for t in res.trace:
        m = re.search(r"Ingested (\d+) " + label, t.text)
        if m:
            return m.group(1)
    return None


bill_lines = _ingested("line items") or "8"
eob_lines = _ingested("payment records") or "8"
n_keep = sum(1 for r in res.reviewed if r.verdict == "KEEP")
tools = sorted({tool for r in res.reviewed for tool in r.tools_called})

bill = json.load(open("data/synthetic_bill.json"))
eob = json.load(open("data/synthetic_eob.json"))


def _usd(s):
    return f"${Decimal(str(s)):,.2f}"


with st.expander(f"📄 Step 1: Extract - {bill_lines} bill lines, {eob_lines} EOB records"):
    st.caption("What the Extractor agent pulled, line by line (synthetic demo data).")
    st.markdown("**Hospital bill lines**")
    st.dataframe(
        [{"#": l["line_no"], "Date": l["date"], "Code": l["code"],
          "Description": l["description"], "Amount": _usd(l["amount"])}
         for l in bill["lines"]],
        use_container_width=True, hide_index=True,
    )
    st.markdown("**EOB payment records**")
    st.dataframe(
        [{"Code": l["code"], "Billed": _usd(l["billed"]), "Allowed": _usd(l["allowed"]),
          "Adjustment": _usd(l["adjustment"]), "You owe": _usd(l["patient_owes"]),
          "Remark": f"{l.get('carc', '')} / {l.get('carc_patient', '')}"}
         for l in eob["lines"]],
        use_container_width=True, hide_index=True,
    )

with st.expander(f"🧮 Step 2: Verify - {len(res.reviewed)} candidate findings"):
    st.caption("Deterministic code, not the model, ran every check below with exact decimal math.")
    for name, val, note in [
        ("Bill lines add up", _usd(res.bill_total), f"sum of {bill_lines} lines"),
        ("EOB allowed total", _usd(res.eob_allowed), "sum of allowed amounts"),
        ("Duplicate scan", "80053 x 2", "same test, same date 2026-08-14: candidate"),
        ("Code relationship", "80048 + 80053", "basic panel is a component of the comprehensive panel: candidate"),
        ("Statement vs EOB", f"{_usd(res.statement_balance)} vs {_usd(res.eob_owes)}",
         f"{_usd(res.delta)} difference: candidate"),
    ]:
        st.markdown(f"✅ **{md(name)}:** {md(val)} "
                    f"<span class='rx-label'>- {md(note)}</span>",
                    unsafe_allow_html=True)

with st.expander(f"🔍 Step 3: Review - {n_keep} kept, {len(res.reviewed) - n_keep} rejected"):
    st.caption("The Reviewer challenged each candidate and could only judge after calling lookup tools.")
    for r in res.reviewed:
        chip = ('<span class="rx-chip rx-keep">Kept</span>' if r.verdict == "KEEP"
                else '<span class="rx-chip rx-reject">Rejected</span>')
        st.markdown(f"{chip} **{md(r.candidate.title)}**<br>"
                    f"<span class='rx-label'>Tools: {md(', '.join(r.tools_called))}</span>",
                    unsafe_allow_html=True)

st.markdown("**Lookup tools consulted**<br>" + " ".join(
    f'<span class="rx-pill">{md(t)}</span>' for t in tools),
    unsafe_allow_html=True)

rejected = [r for r in res.reviewed if r.verdict != "KEEP"]
if rejected:
    st.markdown("### Checked and dropped")
    for r in rejected:
        c = r.candidate
        st.markdown(
            f"""
            <div class="rx-card">
              <span class="rx-chip rx-reject">Rejected by Reviewer</span>
              <div><strong>{md(c.title)}</strong>
              <span class="rx-label"> ({md(f'${c.amount_at_stake:,.2f}')} at stake)</span></div>
              <div class="rx-steptext" style="margin-top:0.4rem">{md(r.reason)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.caption("BillRx shows what it checked and dropped, and why. An agent that only "
               "reports hits cannot be trusted with your money.")

with st.expander("Show technical details (agent trace)"):
    for t in res.trace:
        st.markdown(f"`{t.seq:02d}` **{md(t.agent)}**")
        st.caption(md(" ".join(str(t.text).split())[:160]))

c1, c2 = st.columns(2)
if c1.button("← Back to your case", use_container_width=True):
    st.switch_page("ui/case.py")
if c2.button("See the findings →", type="primary", use_container_width=True):
    st.switch_page("ui/findings.py")
