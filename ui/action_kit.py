"""Screen 4: Action kit. Choose email draft, phone script, or both."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from ui.shared import inject_css, md, require_result, require_approved, reset_all

inject_css()
res = require_result()
require_approved()

st.header("Your action kit")
kept_ids = [r.candidate.finding_id for r in res.reviewed
            if st.session_state.get(f"include_{r.candidate.finding_id}")]
st.caption(f"Dispute packet approved by you, built from {len(kept_ids)} selected finding(s). "
           "Nothing has been sent anywhere.")


@st.dialog("How do you want to contact them?")
def _ask_scripts():
    st.write("BillRx prepared both scripts from your approved findings. Pick what you need.")
    c1, c2, c3 = st.columns(3)
    if c1.button("✉️ Email draft", use_container_width=True):
        st.session_state["script_choice"] = "email"
        st.rerun()
    if c2.button("📞 Phone script", use_container_width=True):
        st.session_state["script_choice"] = "phone"
        st.rerun()
    if c3.button("Both", use_container_width=True):
        st.session_state["script_choice"] = "both"
        st.rerun()


if "script_choice" not in st.session_state:
    if not st.session_state.get("choice_asked"):
        st.session_state["choice_asked"] = True
        _ask_scripts()
        st.stop()
    st.write("What do you need?")
    c1, c2, c3 = st.columns(3)
    if c1.button("✉️ Email draft", use_container_width=True):
        st.session_state["script_choice"] = "email"
        st.rerun()
    if c2.button("📞 Phone script", use_container_width=True):
        st.session_state["script_choice"] = "phone"
        st.rerun()
    if c3.button("Both", use_container_width=True):
        st.session_state["script_choice"] = "both"
        st.rerun()
    st.stop()

choice = st.session_state["script_choice"]
draft = st.session_state.get("final_draft", res.draft)
phone = st.session_state.get("final_phone", res.phone_script)

tabs = []
if choice in ("email", "both"):
    tabs.append(("✉️ Email draft", draft, "billrx-appeal-draft.txt"))
if choice in ("phone", "both"):
    tabs.append(("📞 Phone script", phone, "billrx-phone-script.txt"))

if not st.session_state.get("kit_toasted"):
    st.session_state["kit_toasted"] = True
    st.toast("Dispute packet ready.", icon="✅")
for (label, content, fname), tab in zip(tabs, st.tabs([t[0] for t in tabs])):
    with tab:
        st.code(content, language=None)
        st.download_button("⬇️ Download", content, file_name=fname,
                           mime="text/plain", key=f"dl_{fname}")

st.caption("The model never calculated the money: all arithmetic ran in deterministic "
           "code; the agents handled evidence and language.")

c1, c2, c3 = st.columns(3)
if c1.button("Change script choice", use_container_width=True):
    st.session_state.pop("script_choice", None)
    st.session_state.pop("choice_asked", None)
    st.rerun()
if c2.button("← Back to findings", use_container_width=True):
    st.switch_page("ui/findings.py")
if c3.button("Start over", use_container_width=True):
    reset_all()
    st.switch_page("ui/case.py")
