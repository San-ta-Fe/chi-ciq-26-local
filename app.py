"""Alder Audit — local demo. Run: streamlit run app.py

Reads only data/*.json, data/records.db and the two db/*.db collections.
No pre-computation happens here. Theme: .streamlit/config.toml (Chicago flag colors).
"""
import streamlit as st

from common import HERE
from ui import APP_NAME, sidebar, style

st.set_page_config(page_title=APP_NAME, page_icon=str(HERE / "assets" / "chicago-star.png"),
                   layout="wide", initial_sidebar_state="expanded")

page = st.navigation([
    st.Page("home.py", title="Home", icon=":material/home:", default=True),
    st.Page("pages/1_Alders.py", title="Alders", icon=":material/person:", url_path="Alders"),
    st.Page("pages/2_Issues.py", title="Issues", icon=":material/gavel:", url_path="Issues"),
])
style()
sidebar()
page.run()
