"""Issues page: how each big issue was handled, from committee to council vote."""
import re
from collections import OrderedDict

import pandas as pd
import streamlit as st

from ui import esc, header, html_block, load, md, question_box, status_pill

header("Issues")

issues = [load(f"issues/{i['slug']}.json") for i in load("issues/index.json") if i["featured"]]
slugs = [d["slug"] for d in issues]
if st.session_state.get("issue") not in slugs:
    st.session_state["issue"] = "parking-meters" if "parking-meters" in slugs else slugs[0]


def tally_nays(s):
    m = re.match(r"(\d+) Yea / (\d+) Nay", s.get("tally") or "")
    return (int(m.group(2)), s["date"]) if m else None


def closest_vote(d):
    """The roll call with the most Nay votes (else the latest). A fact, not a ranking."""
    votes = [s for s in d["trail"] if tally_nays(s)]
    if not votes:
        return ""
    s = max(votes, key=tally_nays)
    yea, nay = re.match(r"(\d+) Yea / (\d+) Nay", s["tally"]).groups()
    label = "Closest roll call" if int(nay) else "Latest roll call"
    if not int(nay):
        s = max(votes, key=lambda v: v["date"])
    return f'{label}: <b>{esc(s["record_number"])}</b> · {yea}–{nay} · {esc(s["date"])}'


def pick(slug):
    st.session_state["issue"] = slug


left, right = st.columns([1, 2.3], gap="large")

with left:
    for d in issues:
        sel = d["slug"] == st.session_state["issue"]
        with st.container(border=True, key=f"{'sel' if sel else 'card'}_issue_{d['slug']}"):
            html_block(f'<div class="aa-card-title">{esc(d["name"])}</div>{status_pill(d["status"])}'
                       f'<div class="aa-card-body" style="margin-top:.5rem">{esc(d["one_line"])}</div>'
                       f'<div class="aa-meta">{closest_vote(d)}</div>')
            st.button("Showing below →" if sel else "Show how it was handled",
                      key=f"btn_{d['slug']}", on_click=pick, args=(d["slug"],),
                      type="primary" if sel else "secondary", use_container_width=True,
                      disabled=sel)

with right:
    d = next(x for x in issues if x["slug"] == st.session_state["issue"])
    html_block(f'<div style="display:flex;align-items:center;gap:1rem"><h1 style="margin:0">'
               f'{esc(d["name"])}</h1>{status_pill(d["status"])}</div>'
               f'<div class="aa-card-body" style="font-size:1.25rem;margin:.6rem 0 1rem">'
               f'{esc(d["summary"])}</div>')
    st.caption(f"Summary by {d['model_profile']} · {d['model']} from the official trail and the "
               "excerpts below; numbers like [3] refer to those excerpts. Status comes from the "
               "records, not the model.")

    st.markdown("## How it moved")
    by_rec = OrderedDict()
    for s in d["trail"]:
        by_rec.setdefault(s["record_number"], []).append(s)
    blocks = []
    for rec, steps in by_rec.items():
        chips = []
        for s in steps:
            if s["step"] == "introduced":
                chips.append(f'<span class="aa-step intro">Introduced<b>{esc(s["date"])}</b></span>')
            elif s["step"] == "committee":
                link = (f' · <a href="{esc(s["doc_url"])}" target="_blank">doc</a>'
                        if s.get("doc_url") else "")
                body = s["body"].replace("Committee on ", "")
                chips.append(f'<span class="aa-step com">{esc(body)}{link}<b>{esc(s["date"])}</b></span>')
            elif s["step"] == "council action":
                tally = ""
                m = re.match(r"(\d+) Yea / (\d+) Nay", s.get("tally") or "")
                if m:
                    tally = f" {m.group(1)}–{m.group(2)}"
                chips.append(f'<span class="aa-step council">{esc(s["body"])} · {esc(s["action"])}'
                             f'<b>{esc(s["date"])}{tally}</b></span>')
            else:
                chips.append(f'<span class="aa-step intro">{esc(s["action"])}</span>')
        blocks.append(f'<div class="aa-rec"><div class="aa-rec-head"><span class="aa-recno">'
                      f'{esc(rec)}</span>{esc(steps[0]["title"][:180])}</div><div class="aa-steps">'
                      + '<span class="aa-arrow">→</span>'.join(chips) + '</div></div>')
    html_block("".join(blocks) + '<div class="aa-meta" style="margin-top:.5rem">'
               '<span class="aa-official">official record</span> City Clerk: introduction, '
               'committee agendas and summaries, council action and roll call.</div>')
    with st.expander("All steps as a table"):
        rows = [{"Date": s["date"], "Record": s["record_number"], "Step": s["step"],
                 "Vote": s.get("tally", ""), "Action": s["action"], "Where": s["body"],
                 "Title": s["title"], "Document": s.get("doc_url", "")} for s in d["trail"]]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                     column_config={"Document": st.column_config.LinkColumn(display_text="document")})

    st.markdown("## Excerpts")
    cited = set(d["cited_excerpts"])
    lines = []
    for e in d["evidence"]:
        num = f'<b style="color:#E4002B">[{e["n"]}]</b>' if e["n"] in cited else f'[{e["n"]}]'
        if e["kind"] == "transcript":
            lines.append(f'<div class="aa-meta" style="font-size:1rem">{num} {esc(e["date"])} · '
                         f'{esc(e["body"])} · captions at {esc(e["at"])} · <a href="'
                         f'{esc(e["video_url"])}" target="_blank">▶ watch</a> · '
                         f'<span class="aa-likely">likely speaker</span></div>')
        else:
            lines.append(f'<div class="aa-meta" style="font-size:1rem">{num} {esc(e["date"])} · '
                         f'{esc(e["body"])} · {esc(e["doc_name"])}, p. {e["page"]} · <a href="'
                         f'{esc(e["doc_url"])}" target="_blank">document</a></div>')
    html_block("".join(lines))
    st.caption("Cited excerpts in red. Transcripts are Vimeo auto-captions and may contain errors.")

st.markdown("## Ask about any issue")
question_box("issues")
