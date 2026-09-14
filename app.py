"""BillRx demo UI. Evidence-first agent, four short screens, human approval gate."""
import streamlit as st

st.set_page_config(page_title="BillRx", page_icon="🧾", layout="wide")

case = st.Page("ui/case.py", title="1. Your case", icon="📋", default=True)
investigation = st.Page("ui/investigation.py", title="2. Investigation", icon="🔍")
findings = st.Page("ui/findings.py", title="3. Findings", icon="🧾")
action_kit = st.Page("ui/action_kit.py", title="4. Action kit", icon="✉️")

pg = st.navigation([case, investigation, findings, action_kit])
pg.run()
