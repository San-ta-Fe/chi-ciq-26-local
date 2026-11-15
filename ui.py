"""Shared pieces for the Streamlit pages: theme CSS, Chicago header, sidebar, data loading,
the question box. Colors are the Chicago flag's: light blue stripes, red six-pointed stars."""
import html
import json
import math

import streamlit as st

from common import cfg, path

APP_NAME = "Alder Audit"
BLUE, RED, NAVY, PALE = "#41B6E6", "#E4002B", "#0B2340", "#EAF6FC"
SOURCE_LABEL = "Transcripts are Vimeo auto-captions and may contain errors."
SPEAKER_NOTE = ("Captions have no speaker names: anything attributed from them is the "
                "likely speaker. Votes and sponsorships are official City Clerk records.")
PERIOD = "Chicago City Council · Nov 11, 2025 – Nov 11, 2026"


# ---------- text helpers ----------

def md(text: str) -> str:
    """Escape characters Streamlit markdown would misread ($ starts LaTeX)."""
    return (text or "").replace("$", r"\$")


def esc(text) -> str:
    """For raw HTML: escape tags, and $ so markdown doesn't start LaTeX."""
    return html.escape(str(text or "")).replace("$", "&#36;")


def load(rel: str):
    return json.loads((path("data_dir") / rel).read_text())


def display_name(voter: str) -> str:
    """'Lopez, Raymond A.' -> 'Raymond A. Lopez'; 'Cardona, Jr., Felix' -> 'Felix Cardona Jr.'"""
    parts = [p.strip() for p in voter.split(",")]
    if len(parts) == 3:
        return f"{parts[2]} {parts[0]} {parts[1]}"
    return f"{parts[1]} {parts[0]}" if len(parts) == 2 else voter


def html_block(s: str):
    st.markdown(s, unsafe_allow_html=True)


# ---------- Chicago flag ----------

def _star(cx, cy, r):
    """Six-pointed star, as on the Chicago flag."""
    pts = []
    for i in range(12):
        a = math.pi / 2 + i * math.pi / 6
        rad = r if i % 2 == 0 else r * 0.48
        pts.append(f"{cx + rad * math.cos(a):.1f},{cy - rad * math.sin(a):.1f}")
    return f'<polygon points="{" ".join(pts)}" fill="{RED}"/>'


def flag_svg(w=150):
    h = w * 2 / 3
    stars = "".join(_star(w * x, h / 2, h * 0.12) for x in (0.2, 0.4, 0.6, 0.8))
    return (f'<svg width="{w}" height="{h:.0f}" viewBox="0 0 {w} {h:.0f}" role="img" '
            f'aria-label="Chicago flag"><rect width="{w}" height="{h:.0f}" fill="#fff" '
            f'stroke="#D5ECF8"/><rect y="{h / 6:.1f}" width="{w}" height="{h / 6:.1f}" '
            f'fill="{BLUE}"/><rect y="{h * 4 / 6:.1f}" width="{w}" height="{h / 6:.1f}" '
            f'fill="{BLUE}"/>{stars}</svg>')


CSS = f"""
<style>
.block-container {{ max-width: 1760px; padding-top: 1.2rem; padding-bottom: 4rem; }}
/* header */
.aa-header {{ display:flex; align-items:center; gap:1.6rem; margin: .2rem 0 .6rem 0; }}
.aa-header svg {{ flex: none; box-shadow: 0 2px 10px rgba(11,35,64,.12); }}
.aa-brand {{ font-size: 3.4rem; font-weight: 900; letter-spacing: .04em; line-height: 1;
            color: {NAVY}; text-transform: uppercase; }}
.aa-brand span {{ color: {RED}; }}
.aa-kicker {{ font-size: 1.05rem; letter-spacing: .14em; text-transform: uppercase;
             color: #3D5A80; margin-top: .35rem; }}
.aa-page {{ margin-left:auto; font-size: 1.6rem; font-weight: 800; color: {NAVY};
           padding: .4rem 1.2rem; border: 3px solid {BLUE}; border-radius: 999px; }}
.aa-stripes {{ height: 14px; margin: .4rem 0 1.2rem 0;
   background: linear-gradient(to bottom, {BLUE} 0 4px, #fff 4px 10px, {BLUE} 10px 14px); }}
.aa-note {{ font-size: .95rem; color: #3D5A80; }}
.aa-note b {{ color: {RED}; }}
/* stat tiles */
.aa-tiles {{ display:grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin: .6rem 0 1rem; }}
.aa-tile {{ background: {PALE}; border-top: 6px solid {RED}; border-radius: .6rem;
           padding: .9rem 1.2rem; }}
.aa-tile .v {{ font-size: 3.2rem; font-weight: 900; color: {NAVY}; line-height: 1.05; }}
.aa-tile .l {{ font-size: 1.1rem; font-weight: 700; color: {NAVY}; }}
.aa-tile .s {{ font-size: .85rem; color: #3D5A80; text-transform: uppercase; letter-spacing: .06em; }}
/* cards */
[class*="st-key-card"] {{ border-left: 7px solid {BLUE} !important; background: #FAFDFF; }}
[class*="st-key-sel"] {{ border-left: 7px solid {RED} !important; background: {PALE}; }}
.aa-card-title {{ font-size: 1.45rem; font-weight: 800; color: {NAVY}; line-height: 1.25;
                 margin-bottom: .4rem; }}
.aa-card-body {{ font-size: 1.08rem; line-height: 1.5; }}
.aa-quote {{ border-left: 4px solid {RED}; padding: .35rem 0 .35rem .9rem; margin: .8rem 0;
            font-size: 1.12rem; font-style: italic; }}
.aa-meta {{ font-style: normal; font-size: .9rem; color: #3D5A80; margin-top: .3rem; }}
.aa-meta a, .aa-watch {{ font-weight: 700; color: {RED} !important; text-decoration: none; }}
.aa-likely {{ background: #FFF4D6; color: #6B4E00; border-radius: 4px; padding: 0 .35rem;
             font-size: .8rem; text-transform: uppercase; letter-spacing: .05em; font-style: normal; }}
.aa-official {{ background: {PALE}; color: #0067A5; border-radius: 4px; padding: 0 .35rem;
               font-size: .8rem; text-transform: uppercase; letter-spacing: .05em; }}
.aa-pill {{ display:inline-block; border-radius: 999px; padding: .15rem .8rem; font-size: .9rem;
           font-weight: 700; text-transform: uppercase; letter-spacing: .05em; }}
.aa-pill.voted {{ background: {NAVY}; color: #fff; }}
.aa-pill.committee {{ background: {BLUE}; color: {NAVY}; }}
.aa-pill.discussed {{ background: #E3E8EE; color: {NAVY}; }}
.aa-chips {{ display:flex; flex-wrap: wrap; gap: .5rem; margin: .4rem 0 1rem; }}
.aa-chip {{ background: {PALE}; border: 1px solid #BFE3F5; border-radius: 999px;
           padding: .25rem .8rem; font-size: .95rem; }}
.aa-chip b {{ color: {RED}; }}
/* issue trail timeline */
.aa-rec {{ border-bottom: 1px solid #D5ECF8; padding: .8rem 0; }}
.aa-rec-head {{ font-size: 1.05rem; margin-bottom: .45rem; }}
.aa-recno {{ font-family: ui-monospace, Menlo, monospace; font-weight: 700; color: {NAVY};
            background: {PALE}; padding: .05rem .45rem; border-radius: 4px; margin-right: .4rem; }}
.aa-steps {{ display:flex; flex-wrap: wrap; align-items: stretch; gap: .35rem; }}
.aa-step {{ border-radius: .5rem; padding: .35rem .75rem; font-size: .92rem; line-height: 1.3; }}
.aa-step b {{ display:block; font-size: 1rem; }}
.aa-step.intro {{ background: #F2F5F8; }}
.aa-step.com {{ background: {PALE}; border: 1px solid {BLUE}; }}
.aa-step.council {{ background: {NAVY}; color: #fff; }}
.aa-step.council b {{ font-size: 1.15rem; }}
.aa-step a {{ color: inherit; text-decoration: underline; }}
.aa-arrow {{ align-self: center; color: {BLUE}; font-weight: 900; font-size: 1.3rem; }}
/* buttons, answer */
.stButton button {{ font-size: 1.05rem; min-height: 3rem; height: auto; text-align: left;
                   justify-content: flex-start; padding: .6rem 1rem; }}
.stButton button p, .stButton button div {{ white-space: normal !important; overflow: visible !important;
                   text-overflow: clip !important; text-align: left; }}
.st-key-alder_pick button {{ font-size: 1.25rem !important; padding: .7rem 1.4rem !important;
                            min-height: 3.2rem; }}
.st-key-alder_pick button p {{ font-size: 1.25rem !important; font-weight: 700; }}
.st-key-alder_pick label p {{ font-size: 1rem; text-transform: uppercase; letter-spacing: .08em; }}
[class*="st-key-answer"] {{ background: #FAFDFF; border-left: 7px solid {RED} !important;
                           font-size: 1.15rem; }}
[data-testid="stSegmentedControl"] button {{ font-size: 1.15rem; padding: .5rem 1.1rem; }}
/* home page */
.aa-hero {{ font-size: 4.6rem; font-weight: 900; line-height: 1.02; color: {NAVY};
           margin: 2.2rem 0 1rem; letter-spacing: -.01em; }}
.aa-hero span {{ color: {RED}; }}
.aa-lede {{ font-size: 1.7rem; line-height: 1.4; max-width: 1150px; color: #2A4365; }}
.aa-big3 {{ display:flex; gap: 3.5rem; margin: 2.2rem 0 2.4rem; flex-wrap: wrap; }}
.aa-big3 div {{ font-size: 1.25rem; color: #2A4365; }}
.aa-big3 b {{ display:block; font-size: 3.6rem; font-weight: 900; color: {RED}; line-height: 1; }}
.aa-door {{ font-size: 2.1rem; font-weight: 900; color: {NAVY}; margin-bottom: .3rem; }}
.aa-door-sub {{ font-size: 1.3rem; color: #2A4365; min-height: 3.6rem; }}
[class*="st-key-go_"] button {{ font-size: 1.35rem !important; min-height: 3.6rem; justify-content: center; }}
[class*="st-key-go_"] button p {{ font-size: 1.35rem !important; font-weight: 800; }}
.aa-footer {{ margin-top: 3rem; padding-top: .8rem; border-top: 3px solid {BLUE};
             font-size: .9rem; color: #3D5A80; }}
h2 {{ border-bottom: 3px solid {BLUE}; padding-bottom: .3rem; margin-top: 1.4rem; }}
section[data-testid="stSidebar"] .aa-side-brand {{ font-weight: 900; font-size: 1.4rem;
   letter-spacing: .05em; text-transform: uppercase; }}
</style>
"""


def style():
    html_block(CSS)


def header(page: str = "", note: bool = True):
    """Chicago-flag banner with the app name; the source label sits right under it
    (note=False when the page shows it elsewhere, e.g. a footer)."""
    html_block(
        f'<div class="aa-header">{flag_svg(150)}<div><div class="aa-brand">Alder '
        f'<span>Audit</span></div><div class="aa-kicker">{esc(PERIOD)}</div></div>'
        + (f'<div class="aa-page">{esc(page)}</div>' if page else "") + '</div>'
        f'<div class="aa-stripes"></div>'
        + (f'<div class="aa-note"><b>★</b> {esc(SOURCE_LABEL)} {esc(SPEAKER_NOTE)}</div>'
           if note else ""))


def tiles(items):
    """items: [(value, label, sublabel)] -> row of big stat tiles."""
    cells = "".join(f'<div class="aa-tile"><div class="v">{esc(v)}</div><div class="l">{esc(l)}'
                    f'</div><div class="s">{esc(s)}</div></div>' for v, l, s in items)
    html_block(f'<div class="aa-tiles">{cells}</div>')


def status_pill(status: str) -> str:
    cls = {"voted": "voted", "in committee": "committee"}.get(status, "discussed")
    return f'<span class="aa-pill {cls}">{esc(status)}</span>'


# ---------- sidebar ----------

def sidebar() -> str:
    """Model selector (re-read from config.json on every run) + source labels."""
    c = cfg()
    profiles = list(c["llm_profiles"])
    cur = st.session_state.get("profile", c["chat_profile"])
    if cur not in profiles:
        cur = c["chat_profile"]
    with st.sidebar:
        html_block(f'{flag_svg(90)}<div class="aa-side-brand">{APP_NAME}</div>')
        choice = st.radio(
            "Model for questions", profiles, index=profiles.index(cur),
            format_func=lambda p: f"{p} · {c['llm_profiles'][p]['model']}")
        st.session_state["profile"] = choice
        st.divider()
        st.caption(SOURCE_LABEL)
        st.caption(SPEAKER_NOTE)
    return choice


# ---------- question box ----------

def _source_line(s, cited):
    mark = "**" if s["n"] in cited else ""
    num = f"{mark}[{s['n']}]{mark}"
    if s["kind"] == "transcript":
        return f"{num} {s['label']} · [▶ watch]({s['link']}) · *likely speaker*"
    if s["kind"] == "document":
        return f"{num} {md(s['label'])} · [document]({s['link']})"
    return f"{num} {md(s['snippet'])} *(official record)*"


def show_answer(r, key):
    with st.container(border=True, key=f"answer_{key}"):
        st.markdown(md(r["answer"]))
        st.caption(f"Answered by {r['profile']} · {r['model']}"
                   + (" · from cache" if r.get("cached") else f" · {r['seconds']}s")
                   + ("" if r.get("alder_filter_used", True) or not r.get("alder")
                      else " · few excerpts name this alder, so the closest matches were used"))
    with st.expander(f"Sources ({len(r['sources'])}; cited ones in bold)",
                     expanded=bool(r["cited"])):
        for s in r["sources"]:
            st.markdown(_source_line(s, set(r["cited"])))
            if s["kind"] != "record":
                st.caption(md(s["snippet"][:300]))


def question_box(key: str, alder=None, suggestions=()):
    """Suggested-question buttons + free text box. Answer kept in session state."""
    import rag  # imported lazily: the pages render without the model stack

    inp, ans = f"{key}_input", f"{key}_answer"

    def pick(q):
        st.session_state[inp] = q
        st.session_state[f"{key}_go"] = True

    if suggestions:
        cols = st.columns(len(suggestions))
        for i, q in enumerate(suggestions):
            cols[i].button(q, key=f"{key}_s{i}", on_click=pick, args=(q,),
                           use_container_width=True)
    with st.form(f"{key}_form", clear_on_submit=False, border=False):
        c1, c2 = st.columns([6, 1], vertical_alignment="bottom")
        q = c1.text_input("Your question", key=inp,
                          placeholder="e.g. What was said about the parking meter deal?")
        asked = c2.form_submit_button("Ask", type="primary", use_container_width=True)
    if (asked or st.session_state.pop(f"{key}_go", False)) and q.strip():
        profile = st.session_state.get("profile")
        model = cfg()["llm_profiles"][profile]["model"]
        with st.spinner(f"Searching the records and asking {profile} · {model}…"):
            try:
                st.session_state[ans] = rag.answer(q.strip(), alder=alder, profile=profile)
            except Exception as e:  # model server down, missing key, ...
                st.session_state[ans] = None
                st.error(f"Could not get an answer from {profile}: {e}")
    if st.session_state.get(ans):
        show_answer(st.session_state[ans], key)
