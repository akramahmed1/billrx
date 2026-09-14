"""Screen 2: Investigation. How BillRx solved the case, compactly."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from ui.shared import inject_css, md, require_result

inject_css()
res = require_result()

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

st.markdown(
    f"""
    <div class="rx-cards">
      <div class="rx-card"><div class="rx-step">
        <div class="rx-stepicon">📄</div>
        <div class="rx-steptitle">1. Extract</div>
        <div class="rx-steptext">Agents read {bill_lines} hospital bill lines and {eob_lines} EOB records, line by line.</div>
      </div></div>
      <div class="rx-card"><div class="rx-step">
        <div class="rx-stepicon">🧮</div>
        <div class="rx-steptitle">2. Verify</div>
        <div class="rx-steptext">Deterministic code checked every dollar figure with exact decimal math and produced {len(res.reviewed)} candidate findings.</div>
      </div></div>
      <div class="rx-card"><div class="rx-step">
        <div class="rx-stepicon">🔍</div>
        <div class="rx-steptitle">3. Review</div>
        <div class="rx-steptext">A Reviewer agent challenged each finding, calling lookup tools first: {n_keep} kept, {len(res.reviewed) - n_keep} rejected.</div>
      </div></div>
    </div>
    """,
    unsafe_allow_html=True,
)

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
