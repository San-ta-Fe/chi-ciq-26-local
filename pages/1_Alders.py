"""Alders page: facts, topics with video moments, sponsored items, votes, questions."""
import pandas as pd
import streamlit as st

from ui import display_name, esc, header, html_block, load, question_box, tiles

header("Alders")

index = load("alders/index.json")
by_name = {a["name"]: a for a in index}
names = list(by_name)
name = st.segmented_control("Choose an alder", names, format_func=display_name,
                            default=st.session_state.get("alder", names[0]), key="alder_pick")
name = name or st.session_state.get("alder", names[0])  # clicking the selected one again
st.session_state["alder"] = name
a = by_name[name]
facts = load(f"alders/{a['slug']}.facts.json")
try:
    ins = load(f"alders/{a['slug']}.insights.json")
except FileNotFoundError:
    ins = {"topics": [], "suggested_questions": []}

votes, spons, named = facts["votes"], facts["sponsored"], facts["named_in_meetings"]
minority = votes["voted_differently_from_majority"]

st.markdown(f"# Alder {display_name(name)}")
tiles([(named["meetings"], "Meetings named in", "captions · likely"),
       (spons["count"], "Items sponsored", "official record"),
       (f"{votes['rollcall_items']:,}", "Roll-call votes", f"official · {votes['meetings']} meetings"),
       (len(minority), "Voted differently from majority", "official record")])

# ---------- topics ----------
st.markdown("## Topics they spoke about")
st.caption("Quotes are word for word from the auto-captions. The speaker is inferred from the "
           "captions (likely speaker); ▶ watch opens the video at that moment.")
topics = ins.get("topics", [])
if not topics:
    st.info("No topics computed for this alder yet.")
cols = st.columns(3, gap="medium")
for i, t in enumerate(topics):
    quotes = "".join(
        f'<div class="aa-quote">“{esc(q["text"])}”<div class="aa-meta">{esc(q["date"])} · '
        f'{esc(q["body"])} · <a href="{esc(q["video_url"])}" target="_blank">▶ watch</a> · '
        f'<span class="aa-likely">likely speaker</span></div></div>' for q in t["quotes"])
    with cols[i % 3], st.container(border=True, key=f"card_topic_{i}"):
        html_block(f'<div class="aa-card-title">{esc(t["topic"])}</div>'
                   f'<div class="aa-card-body">{esc(t["summary"])}</div>{quotes}')

# ---------- records ----------
left, right = st.columns(2, gap="large")
with left:
    st.markdown(f"## Sponsored items · {spons['count']}")
    html_block('<div class="aa-chips">' + "".join(
        f'<span class="aa-chip">{esc(c.title())} <b>{n}</b></span>'
        for c, n in list(spons["by_category"].items())[:10]) + '</div>')
    df = pd.DataFrame(spons["items"])
    if not df.empty:
        st.dataframe(df[["intro_date", "record_number", "title", "status"]].rename(
            columns={"intro_date": "Introduced", "record_number": "Record", "title": "Title",
                     "status": "Status"}), hide_index=True, use_container_width=True, height=380)
    st.caption(spons["source"])
with right:
    st.markdown(f"## Voted differently from majority · {len(minority)}")
    if minority:
        st.dataframe(pd.DataFrame(minority)[["date", "record_number", "title", "their_vote",
                                             "tally"]].rename(columns={
            "date": "Date", "record_number": "Record", "title": "Title",
            "their_vote": "Their vote", "tally": "Tally"}),
            hide_index=True, use_container_width=True, height=440)
    else:
        st.write("Voted with the majority on every roll call in this period.")
    st.caption(f"{votes['source']}. Yea {votes['yea']:,} · Nay {votes['nay']} · other "
               f"{sum(votes['other'].values())}.")

with st.expander(f"Meetings where named in captions ({named['meetings']})"):
    html_block('<div class="aa-chips">' + "".join(
        f'<span class="aa-chip">{esc(b)} <b>{n}</b></span>' for b, n in named["by_body"].items())
        + '</div>')
    rows = [{"Date": r["date"], "Body": r["body"], "Mentions": r["mentions"],
             "First mention": r["videos"][0]["video_url"]} for r in named["list"]]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                 column_config={"First mention": st.column_config.LinkColumn(display_text="▶ watch")})
    st.caption(named["source"])

# ---------- questions ----------
st.markdown(f"## Ask about Alder {name.split(',')[0]}")
question_box(f"alder_{a['slug']}", alder=name, suggestions=ins.get("suggested_questions", []))
