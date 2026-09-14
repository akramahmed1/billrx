"""Screen 3: Findings. Review candidates, select, approve."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from ui.shared import inject_css, md, require_result
from src.pipeline import build_appeal_draft, build_phone_script

inject_css()
res = require_result()

# Progressive enhancement: keep the action bar visible while scrolling.
# If the selector ever stops matching, the bar simply sits at the bottom.
st.markdown(
    """<style>
    div[data-testid="stVerticalBlockBorderWrapper"] {
        position: sticky; bottom: 0.75rem; z-index: 50; background: #FFFFFF;
        box-shadow: 0 -4px 18px rgba(15, 118, 110, 0.10);
    }
    </style>""",
    unsafe_allow_html=True,
)

st.header("Findings")
st.caption("Check the findings you agree with. Nothing is drafted or sent until you approve.")

ordered = sorted(res.reviewed, key=lambda r: 0 if r.verdict == "KEEP" else 1)
for r in ordered:
    c = r.candidate
    chip = ('<span class="rx-chip rx-keep">✅ Worth asking about</span>'
            if r.verdict == "KEEP" else
            '<span class="rx-chip rx-reject">🛑 Rejected by Reviewer</span>')
    with st.container(border=False):
        st.markdown(
            f"""
            <div class="rx-card">
              {chip}
              <div><strong>{md(c.title)}</strong>
              <span class="rx-label"> ({md(f'${c.amount_at_stake:,.2f}')} at stake)</span></div>
              <div style="margin-top:0.45rem"><strong>Question to ask:</strong> {md(c.question)}</div>
              <div style="margin-top:0.45rem"><strong>Key evidence</strong></div>
              <div class="rx-steptext" style="text-align:left"><ul style="margin:0.2rem 0 0 1.1rem;padding:0">"""
            + "".join(f"<li>{md(e)}</li>" for e in c.evidence[:3]) +
            """</ul></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    if r.verdict == "KEEP":
        prev = st.session_state.get("approved_ids") or []
        st.checkbox("Include in my dispute",
                    value=(c.finding_id in prev),
                    key=f"include_{c.finding_id}")
    with st.expander("Reviewer note and tools"):
        st.write(md(r.reason))
        st.caption(f"Tools consulted: {', '.join(r.tools_called)}")

kept = [r for r in res.reviewed if r.verdict == "KEEP"]
selected = [r for r in kept if st.session_state.get(f"include_{r.candidate.finding_id}")]

with st.container(border=True):
    c1, c2 = st.columns([3, 2])
    c1.markdown(f"**{len(selected)} of {len(kept)} selected**  \n"
                f"<span class='rx-label'>Only selected findings go into your dispute packet.</span>",
                unsafe_allow_html=True)
    if c2.button("Approve and continue →", type="primary", use_container_width=True):
        if not selected:
            st.warning("Pick at least one finding first.")
        else:
            bill = json.load(open("data/synthetic_bill.json"))
            eob = json.load(open("data/synthetic_eob.json"))
            st.session_state["final_draft"] = build_appeal_draft(selected, bill, eob)
            st.session_state["final_phone"] = build_phone_script(selected)
            st.session_state["approved"] = True
            # Snapshot the approval in plain session keys: widget state for the
            # checkboxes does not survive the page switch, so never recompute
            # the count from it on the action-kit page.
            st.session_state["approved_count"] = len(selected)
            st.session_state["approved_ids"] = [r.candidate.finding_id for r in selected]
            # Re-ask the script choice on every new approval.
            for k in ("script_choice", "choice_asked", "kit_toasted"):
                st.session_state.pop(k, None)
            st.switch_page("ui/action_kit.py")

if c1.button("← Back to investigation", use_container_width=True):
    st.switch_page("ui/investigation.py")
