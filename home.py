"""Home page: a short, friendly front door. The Alders and Issues pages stay formal."""
import sqlite3

import streamlit as st

from common import path
from ui import SOURCE_LABEL, SPEAKER_NOTE, esc, header, html_block

header(note=False)

db = sqlite3.connect(path("data_dir") / "records.db")
hours = db.execute("SELECT SUM(duration_sec) FROM meetings WHERE has_captions=1").fetchone()[0] or 0
n_meet = db.execute("SELECT COUNT(*) FROM meetings").fetchone()[0]
n_rollcalls = db.execute("SELECT COUNT(DISTINCT record_number) FROM votes").fetchone()[0]

html_block(
    '<div class="aa-hero">Alders talk. Issues move.<br><span>We keep the receipts.</span></div>'
    '<div class="aa-lede">We turned a year of Chicago City Council meetings into something you '
    'can actually read. Every claim links back to the moment it happened.</div>'
    '<div class="aa-big3">'
    f'<div><b>{round(hours / 3600):,} hours</b>of meeting video, so you don\'t have to</div>'
    f'<div><b>{n_meet:,}</b>council and committee meetings</div>'
    f'<div><b>{n_rollcalls:,}</b>roll-call votes, one click away</div>'
    '</div>')

c1, c2 = st.columns(2, gap="large")
with c1, st.container(border=True, key="card_home_alders"):
    html_block('<div class="aa-door">Meet your alders</div>'
               '<div class="aa-door-sub">What they talked about, how they voted, '
               'and what they put their name on.</div>')
    if st.button("Meet the alders →", key="go_alders", type="primary", use_container_width=True):
        st.switch_page("pages/1_Alders.py")
with c2, st.container(border=True, key="card_home_issues"):
    html_block('<div class="aa-door">Follow the issues</div>'
               '<div class="aa-door-sub">From the first draft to the final vote: '
               'how big ideas become city law.</div>')
    if st.button("Follow the issues →", key="go_issues", type="primary", use_container_width=True):
        st.switch_page("pages/2_Issues.py")

html_block(f'<div class="aa-footer">★ {esc(SOURCE_LABEL)} {esc(SPEAKER_NOTE)} '
           'Source: Chicago City Clerk archive, Nov 11, 2025 – Nov 11, 2026.</div>')
