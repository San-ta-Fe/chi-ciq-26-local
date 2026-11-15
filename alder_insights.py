"""Step 3b: topics each featured alder spoke about, with real quotes. Cloud model.

Evidence = transcript chunks that name the alder, favouring the moments right after the
chair recognizes them ("The chair recognizes Alderman Lopez" / "Alderman Lopez, you're
recognized": that chunk and the next one). Capped and spread across meetings.

After the model call every quote is checked: it must appear word for word in the excerpt it
cites, or it is dropped. Each kept quote gets the caption line's time as its video link.
Topics with no quote left are dropped.

Usage:
  python alder_insights.py                    # all featured alders
  python alder_insights.py --only lopez-raymond
  python alder_insights.py --max-excerpts 40  # smaller prompt
  -> data/alders/<slug>.insights.json
"""
import argparse
import json
import re
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

from common import cfg, chat, collection, hms, path, vimeo_link
from pick_alders import TITLES, caption_files, fold

LINE = re.compile(r"^\[(\d+):(\d\d):(\d\d)(?:\.\d+)?\]\s*(.*)$")

PROMPT = """You are given numbered excerpts from Chicago City Council meeting auto-captions where \
{title} is likely speaking or being addressed. Captions have no speaker names and contain \
transcription errors; other people speak in these excerpts too.

List 3-6 topics this alder spoke about most. For each topic: a neutral 1-2 sentence summary of \
what they said or asked, and up to 2 short exact quotes (5-30 words, copied character for \
character from the excerpt, no added punctuation or ellipses) with the excerpt number. \
Only use words you believe this alder said, typically right after the chair recognizes them. \
No opinions, no ratings, no praise or criticism. Do not state titles, roles or committee \
chairs unless the excerpt says so about this alder. Skip a topic if you are unsure the words \
are this alder's.

Also write 3 short questions a resident might ask about this alder's council work that these \
excerpts could answer.

Reply with JSON only:
{{"topics":[{{"topic":"...","summary":"...","quotes":[{{"text":"...","excerpt":1}}]}}],
 "questions":["...","...","..."]}}

Excerpts:
{excerpts}"""


def all_chunks():
    """id -> (text, meta) for every transcript chunk (read straight from the store)."""
    coll = collection("transcripts")
    _, ids, texts, metas, _ = coll._load()
    return OrderedDict((i, (t, m)) for i, t, m in zip(ids, texts, metas))


def gather(chunks, name_re, cap):
    """Pick evidence chunks: recognized moments (+ the next window) first, then other
    mentions, round-robin across meetings so one long hearing can't fill the cap."""
    name = re.compile(name_re)
    recog = re.compile(rf"recogni\w*\s+(?:\w+\s+){{0,3}}?{TITLES}\s+{name_re}"
                       rf"|{TITLES}\s+{name_re}\W+(?:you\W?re|you are)\s+recogni")
    step = cfg()["transcript_step_sec"]
    primary, secondary = defaultdict(list), defaultdict(list)
    for cid, (text, meta) in chunks.items():
        f = fold(text)
        if recog.search(f):
            primary[meta["meeting_id"]].append(cid)
            nxt = f"t-{meta['video_id']}-{meta['start_sec'] + step}"
            if nxt in chunks:
                primary[meta["meeting_id"]].append(nxt)
        elif name.search(f):
            secondary[meta["meeting_id"]].append(cid)

    picked = []
    for pool in (primary, secondary):
        queues = [list(dict.fromkeys(v)) for v in pool.values()]
        while queues and len(picked) < cap:
            for q in queues:
                if q and len(picked) < cap and q[0] not in picked:
                    picked.append(q.pop(0))
                elif q:
                    q.pop(0)
            queues = [q for q in queues if q]
    n_primary = sum(1 for c in picked if chunks[c][1]["meeting_id"] in primary)
    picked.sort(key=lambda c: (chunks[c][1]["date"], chunks[c][1]["video_id"],
                               chunks[c][1]["start_sec"]))
    return picked, n_primary


def find_exact(quote: str, text: str):
    """Return the quote as it appears in text (whitespace/case-insensitive), or None."""
    q = " ".join(quote.strip().strip('"“”').split())
    if len(q.split()) < 3:
        return None
    t = " ".join(text.split())
    i = t.lower().find(q.lower())
    return t[i:i + len(q)] if i >= 0 else None


def caption_rows(archive, cache={}):
    """video_id -> [(sec, line)] from the caption .txt files (loaded once)."""
    if not cache:
        for m, vid, f in caption_files(archive):
            rows = []
            for line in f.read_text(errors="replace").splitlines():
                mt = LINE.match(line.strip())
                if mt and mt.group(4):
                    rows.append((int(mt.group(1)) * 3600 + int(mt.group(2)) * 60
                                 + int(mt.group(3)), mt.group(4)))
            cache[vid] = rows
    return cache


def quote_time(rows, start, window, quote):
    """Second of the caption line where the quote begins (fallback: chunk start)."""
    lines = [(s, t) for s, t in rows if start <= s < start + window]
    joined, starts, pos = [], [], 0
    for s, t in lines:
        starts.append((pos, s))
        joined.append(t.lower())
        pos += len(t) + 1
    i = " ".join(joined).find(quote.lower()[:40])
    if i < 0:
        return start
    sec = start
    for p, s in starts:
        if p <= i:
            sec = s
    return sec


def run_one(alder, chunks, rows_by_video, cap, profile):
    name_re = alder["name_regex"]
    picked, n_primary = gather(chunks, name_re, cap)
    if not picked:
        print(f"  no evidence for {alder['name']}")
        return None
    excerpts = []
    for n, cid in enumerate(picked, 1):
        text, m = chunks[cid]
        excerpts.append(f"[{n}] {m['date']} | {m['body']} | at {hms(m['start_sec'])}\n{text}")
    surname = alder["surname"]
    prompt = PROMPT.format(title=f"Alder {surname} ({alder['name']})",
                           excerpts="\n\n".join(excerpts))
    print(f"  {len(picked)} excerpts ({n_primary} from recognized moments), "
          f"{len(prompt) // 4:,} tokens approx.")

    data = None
    for attempt in range(2):
        raw = chat([{"role": "user", "content": prompt}], profile, json_mode=True)
        try:
            data = json.loads(re.sub(r"^```(?:json)?|```$", "", raw.strip()).strip())
            break
        except json.JSONDecodeError:
            print(f"  bad JSON (attempt {attempt + 1}): {raw[:200]!r}")
    if data is None:
        return None

    window = cfg()["transcript_window_sec"]
    topics, dropped = [], 0
    for t in data.get("topics", []):
        quotes = []
        for q in t.get("quotes", [])[:2]:
            try:
                k = int(q.get("excerpt"))
            except (TypeError, ValueError):
                dropped += 1
                continue
            if not 1 <= k <= len(picked):
                dropped += 1
                continue
            text, m = chunks[picked[k - 1]]
            exact = find_exact(q.get("text", ""), text)
            if not exact:
                dropped += 1
                continue
            sec = quote_time(rows_by_video.get(m["video_id"], []), m["start_sec"], window, exact)
            quotes.append({"text": exact, "excerpt": k, "date": m["date"], "body": m["body"],
                           "meeting_id": m["meeting_id"], "video_id": m["video_id"],
                           "start_sec": sec, "video_url": vimeo_link(m["video_id"], sec),
                           "chunk_id": picked[k - 1], "speaker": "likely"})
        if quotes:
            topics.append({"topic": t.get("topic", ""), "summary": t.get("summary", ""),
                           "quotes": quotes})
    print(f"  {len(topics)} topics kept, {sum(len(t['quotes']) for t in topics)} quotes kept, "
          f"{dropped} quotes dropped (not word for word)")

    return {
        "name": alder["name"], "slug": alder["slug"],
        "model_profile": profile, "model": cfg()["llm_profiles"][profile]["model"],
        "source_note": "Transcripts are Vimeo auto-captions and may contain errors. "
                       "Speakers are inferred: quotes are from the likely speaker.",
        "topics": topics,
        "suggested_questions": [q for q in data.get("questions", []) if isinstance(q, str)][:3],
        "evidence": [{"n": n, "chunk_id": c, "date": chunks[c][1]["date"],
                      "body": chunks[c][1]["body"], "video_url": chunks[c][1]["video_url"]}
                     for n, c in enumerate(picked, 1)],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="one slug")
    ap.add_argument("--max-excerpts", type=int, default=60)
    ap.add_argument("--profile", help="model profile (default: precompute_profile)")
    ap.add_argument("--archive", help="archive folder, for exact quote times")
    args = ap.parse_args()

    profile = args.profile or cfg()["precompute_profile"]
    outdir = path("data_dir") / "alders"
    index = json.loads((outdir / "index.json").read_text())  # written by alder_facts.py
    archive = Path(args.archive).expanduser() if args.archive else path("archive_dir")
    rows_by_video = caption_rows(archive) if (archive / "index.json").exists() else {}
    if not rows_by_video:
        print("Archive not readable: quote links will use the chunk start time.", file=sys.stderr)
    chunks = all_chunks()

    for alder in index:
        if args.only and alder["slug"] != args.only:
            continue
        print(alder["name"])
        out = run_one(alder, chunks, rows_by_video, args.max_excerpts, profile)
        if out:
            (outdir / f"{alder['slug']}.insights.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
