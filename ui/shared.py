"""Shared UI helpers for the BillRx multipage app."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st


def md(text):
    """Escape $ so Streamlit does not treat $...$ as KaTeX math."""
    return str(text).replace("$", r"\$")


def inject_css():
    st.markdown(
        """
        <style>
        .rx-hero { background: linear-gradient(135deg, #0F766E 0%, #0D5C56 55%, #083F3A 100%);
                   color: #FFFFFF; border-radius: 1rem; padding: 1.6rem 2rem; margin-bottom: 1.2rem; }
        .rx-hero h1 { color: #FFFFFF !important; margin-bottom: 0.3rem; font-size: 1.9rem; }
        .rx-hero p { color: #D7EDEA; margin-bottom: 0; font-size: 1.02rem; }
        .rx-cards { display: flex; gap: 1rem; align-items: stretch; flex-wrap: wrap; margin-bottom: 1rem; }
        .rx-card { flex: 1 1 180px; border: 1px solid #E2E8F0; border-radius: 0.75rem;
                   padding: 1.1rem 1.25rem; background: #FFFFFF; }
        .rx-label { color: #64748B; font-size: 0.82rem; margin-bottom: 0.25rem; }
        .rx-bignum { color: #0F766E; font-size: 1.55rem; font-weight: 800; }
        .rx-chip { display: inline-block; border-radius: 999px; padding: 0.15rem 0.75rem;
                   font-size: 0.78rem; font-weight: 700; margin-bottom: 0.5rem; }
        .rx-keep { background: #ECFDF5; color: #047857; border: 1px solid #A7F3D0; }
        .rx-reject { background: #FEF2F2; color: #B91C1C; border: 1px solid #FECACA; }
        .rx-pill { display: inline-block; background: #F1F5F9; color: #475569; border-radius: 999px;
                   padding: 0.1rem 0.6rem; font-size: 0.75rem; margin: 0 0.25rem 0.25rem 0; }
        .rx-step { text-align: center; padding: 0.8rem 0.4rem; }
        .rx-stepicon { font-size: 1.7rem; line-height: 1; margin-bottom: 0.4rem; }
        .rx-steptitle { font-weight: 700; color: #1E293B; margin-bottom: 0.25rem; }
        .rx-steptext { color: #64748B; font-size: 0.85rem; line-height: 1.5; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def require_result():
    """Guard: pages beyond the case need a completed audit."""
    res = st.session_state.get("res")
    if res is None:
        st.warning("Run the audit on **1. Your case** first.")
        st.page_link("ui/case.py", label="Go to 1. Your case", icon="📋")
        st.stop()
    return res


def require_approved():
    if not st.session_state.get("approved"):
        st.warning("Approve your findings on **3. Findings** first.")
        st.page_link("ui/findings.py", label="Go to 3. Findings", icon="🧾")
        st.stop()


def reset_all():
    res = st.session_state.get("res")
    for k in ("res", "approved", "final_draft", "final_phone",
              "script_choice", "choice_asked", "just_ran", "kit_toasted"):
        st.session_state.pop(k, None)
    if res is not None:
        for r in res.reviewed:
            st.session_state.pop(f"include_{r.candidate.finding_id}", None)


def disclaimer():
    st.warning("Research prototype. All data on this page is synthetic and fictional. "
               "BillRx does not determine whether a real bill is incorrect and does not "
               "provide medical, insurance, or legal advice.")
