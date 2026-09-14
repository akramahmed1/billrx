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
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
        h1, h2, h3, .rx-bignum, .rx-steptitle, .rx-kicker, .rx-statnum {
            font-family: 'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif;
            letter-spacing: -0.01em;
        }
        .rx-hero { background: linear-gradient(135deg, #0F766E 0%, #0D5C56 55%, #083F3A 100%);
                   color: #FFFFFF; border-radius: 1rem; padding: 1.6rem 2rem; margin-bottom: 1.2rem; }
        .rx-hero h1 { color: #FFFFFF !important; margin-bottom: 0.3rem; font-size: 1.9rem; }
        .rx-hero p { color: #D7EDEA; margin-bottom: 0; font-size: 1.02rem; }
        .rx-cards { display: flex; gap: 1rem; align-items: stretch; flex-wrap: wrap; margin-bottom: 1rem; }
        .rx-card { flex: 1 1 180px; border: 1px solid #E2E8F0; border-radius: 0.75rem;
                   padding: 1.1rem 1.25rem; background: #FFFFFF;
                   transition: box-shadow .15s ease; }
        .rx-card:hover { box-shadow: 0 8px 22px rgba(15, 118, 110, 0.10); }
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
        .rx-kicker { color: #0F766E; font-size: 0.78rem; font-weight: 800;
                     letter-spacing: 0.09em; text-transform: uppercase; margin-bottom: 0.35rem; }
        .rx-progress { height: 4px; background: #E2E8F0; border-radius: 999px;
                       margin-bottom: 1.1rem; overflow: hidden; }
        .rx-progress-fill { height: 100%; border-radius: 999px;
                            background: linear-gradient(90deg, #14B8A6, #0F766E); }
        .rx-stat { text-align: center; padding: 0.5rem 0.25rem; }
        .rx-statnum { color: #0F766E; font-size: 1.45rem; font-weight: 800; }
        .rx-statlabel { color: #64748B; font-size: 0.8rem; margin-top: 0.15rem; }
        section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"] {
            font-size: 1.02rem; padding: 0.5rem 0.85rem; border-radius: 0.65rem;
            margin-bottom: 0.15rem;
        }
        section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"][aria-current="page"] {
            background: #CCFBF1; color: #0F766E; font-weight: 700;
        }
        .stButton > button { border-radius: 0.65rem;
            transition: transform .12s ease, box-shadow .12s ease; }
        .stButton > button:hover { transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(15, 118, 110, 0.16); }
        </style>
        """,
        unsafe_allow_html=True,
    )


def step_kicker(n, label):
    """Wayfinding: 'Step N of 4' label plus a thin progress bar."""
    st.markdown(
        f"""<div class="rx-kicker">Step {n} of 4 &middot; {label}</div>
        <div class="rx-progress"><div class="rx-progress-fill" style="width:{n * 25}%"></div></div>""",
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
    for k in ("res", "approved", "approved_count", "approved_ids",
              "final_draft", "final_phone",
              "script_choice", "choice_asked", "just_ran", "kit_toasted"):
        st.session_state.pop(k, None)
    if res is not None:
        for r in res.reviewed:
            st.session_state.pop(f"include_{r.candidate.finding_id}", None)


def disclaimer():
    st.warning("Research prototype. All data on this page is synthetic and fictional. "
               "BillRx does not determine whether a real bill is incorrect and does not "
               "provide medical, insurance, or legal advice.")
