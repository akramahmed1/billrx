"""BillRx demo UI. Evidence-first cards, live agent trace, human approval gate."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

from src.pipeline import Pipeline, build_appeal_draft, build_phone_script
import json

st.set_page_config(page_title="BillRx", page_icon="🧾", layout="wide")

st.title("BillRx")
st.caption("An evidence-first agent that helps people investigate confusing medical bills.")
st.warning("Research prototype. All data on this page is synthetic and fictional. "
           "BillRx does not determine whether a real bill is incorrect and does not "
           "provide medical, insurance, or legal advice.")

ICONS = {"start": "⚙️", "tool": "🔍", "decision": "🧠", "gate": "⏸️", "done": "✅"}


def _short(text, n=110):
    t = " ".join(str(text).split())
    return t if len(t) <= n else t[:n - 1] + "…"


if st.button("Run BillRx audit", type="primary"):
    pipe = Pipeline()
    with st.spinner("Agents working..."):
        res = pipe.run("data/synthetic_bill.json", "data/synthetic_eob.json")
    for r in res.reviewed:
        st.session_state.pop(r.candidate.finding_id, None)
    st.session_state["res"] = res
    st.session_state["approved"] = False
    st.session_state.pop("final_draft", None)
    st.session_state.pop("final_phone", None)

res = st.session_state.get("res")
if res is None:
    st.markdown("### How it works")
    steps = [
        ("📄", "Extract",
         "Agents read the itemized hospital bill and the explanation of benefits, line by line."),
        ("🧮", "Verify",
         "Deterministic code, not the model, checks every dollar figure with exact decimal math."),
        ("🔍", "Review",
         "A Reviewer agent challenges each candidate finding and may only judge after calling lookup tools."),
        ("✅", "You approve",
         "Nothing is drafted until a human selects which findings to include."),
    ]
    cols = st.columns(4)
    for col, (icon, title, text) in zip(cols, steps):
        with col:
            with st.container(border=True):
                st.markdown(f"**{icon} {title}**")
                st.caption(text)
    st.caption("Demo case: 8 hospital bill lines, 8 EOB records, 4 candidate findings. "
               "Press **Run BillRx audit** above to analyze them.")
    st.stop()

# ---- trace sidebar ----
with st.sidebar:
    st.header("Agent trace")
    for t in res.trace:
        st.markdown(f"`{t.seq:02d}` {ICONS.get(t.kind, 'ℹ️')} **{t.agent}**")
        st.caption(_short(t.text))

# ---- claim delta ----
st.header(f"${res.delta:,.2f} difference worth investigating")
st.caption("In this fictional example, BillRx compared the hospital statement "
           "against the explanation of benefits.")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Hospital billed", f"${res.bill_total:,.2f}")
c2.metric("Insurer allowed", f"${res.eob_allowed:,.2f}")
c3.metric("Statement asks you to pay", f"${res.statement_balance:,.2f}")
c4.metric("EOB says you owe", f"${res.eob_owes:,.2f}")

# ---- findings ----
st.header("Findings")
for r in res.reviewed:
    c = r.candidate
    badge = "✅ Worth asking about" if r.verdict == "KEEP" else "🛑 Rejected by Reviewer"
    with st.expander(f"{badge} — {c.title} (${c.amount_at_stake:,.2f})",
                     expanded=(r.verdict == "KEEP")):
        st.markdown(f"**Question to ask:** {c.question}")
        st.markdown("**Evidence**")
        for e in c.evidence:
            st.markdown(f"- {e}")
        st.markdown(f"**Reviewer:** {r.reason}")
        st.caption(f"Tools consulted: {', '.join(r.tools_called)}")

# ---- approval gate ----
st.header("Human approval gate")
kept = [r for r in res.reviewed if r.verdict == "KEEP"]
st.write("Nothing below is sent anywhere. Check the findings you agree with, then approve.")
selected = []
for r in kept:
    if st.checkbox(f"Include: {r.candidate.title} (${r.candidate.amount_at_stake:,.2f})",
                   value=False, key=r.candidate.finding_id):
        selected.append(r)

if st.button("Approve and generate dispute packet"):
    if not selected:
        st.session_state["approved"] = False
        st.warning("Select at least one finding to include in the dispute packet.")
    else:
        bill = json.load(open("data/synthetic_bill.json"))
        eob = json.load(open("data/synthetic_eob.json"))
        st.session_state["final_draft"] = build_appeal_draft(selected, bill, eob)
        st.session_state["final_phone"] = build_phone_script(selected)
        st.session_state["approved"] = True

if st.session_state.get("approved"):
    st.success("Approved by human. Dispute packet generated from selected findings.")
    st.subheader("Formal appeal draft")
    st.text(st.session_state.get("final_draft", res.draft))
    st.subheader("Phone script")
    st.text(st.session_state.get("final_phone", res.phone_script))
    st.caption("The model never calculated the money: all arithmetic ran in "
               "deterministic code; the agents handled evidence and language.")
