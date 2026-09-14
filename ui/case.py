"""Screen 1: Your case. What BillRx is doing, and the audit trigger."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from ui.shared import h, inject_css, md, reset_all, disclaimer, step_kicker
from src.pipeline import Pipeline

inject_css()
step_kicker(1, "Your case")

# Toast from the run that just completed (shown once, on the rerun after the audit).
if st.session_state.pop("just_ran", False):
    res0 = st.session_state.get("res")
    if res0 is not None:
        n = sum(1 for r in res0.reviewed if r.verdict == "KEEP")
        st.toast(f"Audit complete: {n} of {len(res0.reviewed)} findings worth asking about.",
                 icon="✅")

st.markdown(
    """
    <div class="rx-hero">
      <h1>BillRx</h1>
      <p>An evidence-first agent that helps people investigate confusing medical bills.</p>
    </div>
    """,
    unsafe_allow_html=True,
)
disclaimer()

res = st.session_state.get("res")

if res is None:
    st.markdown("### How it works")
    st.markdown(
        """
        <div class="rx-cards">
          <div class="rx-card">
            <div class="rx-stepicon">📄</div>
            <div class="rx-steptitle" style="text-align:left">Extract</div>
            <div class="rx-steptext">Agents read the itemized hospital bill and the explanation of benefits, line by line.</div>
          </div>
          <div class="rx-card">
            <div class="rx-stepicon">🧮</div>
            <div class="rx-steptitle" style="text-align:left">Verify</div>
            <div class="rx-steptext">Deterministic code, not the model, checks every dollar figure with exact decimal math.</div>
          </div>
          <div class="rx-card">
            <div class="rx-stepicon">🔍</div>
            <div class="rx-steptitle" style="text-align:left">Review</div>
            <div class="rx-steptext">A Reviewer agent challenges each candidate finding and may only judge after calling lookup tools.</div>
          </div>
          <div class="rx-card">
            <div class="rx-stepicon">✅</div>
            <div class="rx-steptitle" style="text-align:left">You approve</div>
            <div class="rx-steptext">Nothing is drafted until a human selects which findings to include.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("Demo case: 8 hospital bill lines, 8 EOB records, 4 candidate findings.")
    if st.button("Run BillRx audit", type="primary", use_container_width=True):
        pipe = Pipeline()
        with st.spinner("Agents working..."):
            res = pipe.run("data/synthetic_bill.json", "data/synthetic_eob.json")
        for r in res.reviewed:
            st.session_state.pop(f"include_{r.candidate.finding_id}", None)
        st.session_state["res"] = res
        st.session_state["approved"] = False
        for k in ("final_draft", "final_phone", "script_choice", "choice_asked",
                  "approved_count", "approved_ids"):
            st.session_state.pop(k, None)
        st.session_state["just_ran"] = True
        st.rerun()
else:
    st.markdown(f"### {md(f'${res.delta:,.2f}')} difference worth investigating")
    st.caption("BillRx compared the hospital statement against the explanation of benefits. "
               "Every figure below was checked by deterministic code, not by the model.")
    st.markdown(
        f"""
        <div class="rx-cards">
          <div class="rx-card"><div class="rx-label">Hospital billed</div>
            <div class="rx-bignum">{h(f'${res.bill_total:,.2f}')}</div></div>
          <div class="rx-card"><div class="rx-label">Insurer allowed</div>
            <div class="rx-bignum">{h(f'${res.eob_allowed:,.2f}')}</div></div>
          <div class="rx-card"><div class="rx-label">Statement asks you to pay</div>
            <div class="rx-bignum">{h(f'${res.statement_balance:,.2f}')}</div></div>
          <div class="rx-card"><div class="rx-label">EOB says you owe</div>
            <div class="rx-bignum">{h(f'${res.eob_owes:,.2f}')}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    if c1.button("See the investigation →", type="primary", use_container_width=True):
        st.switch_page("ui/investigation.py")
    if c2.button("Run audit again", use_container_width=True):
        pipe = Pipeline()
        with st.spinner("Agents working..."):
            res = pipe.run("data/synthetic_bill.json", "data/synthetic_eob.json")
        reset_all()
        st.session_state["res"] = res
        st.session_state["approved"] = False
        st.session_state["just_ran"] = True
        st.rerun()
    if c3.button("Start over", use_container_width=True):
        reset_all()
        st.rerun()

with st.expander("🔜 Bring your own bill: on the roadmap"):
    st.write(
        "Today BillRx runs on a fixed synthetic demo case, which is what makes every "
        "number on this page verifiable end to end. The next step is letting you bring "
        "your own bill: enter your itemized charges and EOB lines, or sync them "
        "straight from your email, and the same pipeline "
        "takes over from there. Deterministic code checks every dollar, the Reviewer "
        "challenges each candidate finding against its lookup tools, and nothing is "
        "drafted until you approve it. Your data would be processed in memory only and "
        "never stored."
    )
