"""Step 5: live question answering over the two collections.

answer(question, alder=None, profile=None) -> {"answer", "sources", ...}
  - official outcomes (records.db) for records the sources mention, listed first
  - 8 transcript chunks (filtered to chunks naming the alder, if one is given; if fewer than 3
    come back, search again without the filter) + 4 document chunks
  - the model answers only from the numbered sources and cites them as [1], [2]
  - cached in data/qa_cache.json by (question, alder, profile, model)

Each source sent to the model is cut to its most relevant window. The size comes from the
profile's "rag_source_chars" in config.json (small local models have small context windows).

Usage: python rag.py "What did Alder Lopez say about animal cruelty?" [--alder "Lopez, Raymond A."]
       [--profile cloud]
"""
import argparse
import json
import os
import re
import tempfile
import time

from common import cfg, chat, hms, path, search

STOP = set("""a an and are as at be by did do does for from has have how in is it its of on or
that the their this to was were what when where which who why will with about alder alderman
alderwoman alderperson chicago city council say said""".split())

SYSTEM = """You answer questions about Chicago City Council meetings using only the numbered \
sources given. Rules:
- Use only facts in the sources. Cite every claim with the source number, like [1] or [2][5].
- Only if no source is about the topic at all, reply "Not found in the records."
- Transcript sources are auto-captions with no speaker names: say who "likely" said something, \
never state it as certain. They may contain transcription errors.
- Be neutral: no opinions, praise, criticism or ratings. Keep it under 150 words."""


def _terms(q):
    return [w for w in re.findall(r"[a-z0-9']+", q.lower()) if w not in STOP and len(w) > 2]


def best_window(text, terms, size):
    """The size-char window of text with the most query-term hits (whole text if short)."""
    text = " ".join(text.split())
    if len(text) <= size:
        return text
    low, best, best_i = text.lower(), -1, 0
    for i in range(0, len(text) - size + 1, max(size // 4, 50)):
        score = sum(low.count(t, i, i + size) for t in terms)
        if score > best:
            best, best_i = score, i
    start = text.rfind(" ", 0, best_i) + 1 if best_i else 0
    return ("…" if start else "") + text[start:start + size] + "…"


def _alder_variants(alder):
    """Lower-case surname spellings for the where_document filter."""
    from pick_alders import variants  # surname + caption misspellings (aliases)
    return sorted(variants(alder), key=len, reverse=True)


def retrieve(question, alder=None, nt=8, nd=4):
    trans, filtered = [], False
    if alder:
        best = {}
        for v in _alder_variants(alder):
            for r in search(question, "transcripts", k=nt, where_document={"$contains": v}):
                if r["id"] not in best or r["score"] > best[r["id"]]["score"]:
                    best[r["id"]] = r
        trans = sorted(best.values(), key=lambda r: -r["score"])[:nt]
        filtered = len(trans) >= 3
    if not filtered:
        trans = search(question, "transcripts", k=nt)
    docs = search(question, "documents", k=nd) if nd else []
    return trans, docs, filtered


RECORD = re.compile(r"\b[A-Z]{1,3}r?\d{4}-\d{6,}\b")


def official_records(texts, meeting_ids=(), terms=(), limit=3):
    """[(record_number, "title — action on date, tally")] for records that the source texts
    name, plus agenda items of the sources' meetings whose titles share 2+ question terms."""
    import sqlite3
    from collections import Counter

    db = sqlite3.connect(path("data_dir") / "records.db")
    by_title = Counter()
    for mid in set(meeting_ids):
        for rec, title in db.execute("SELECT record_number, title FROM agenda_items WHERE "
                                     "meeting_id=? AND record_number IS NOT NULL", (mid,)):
            low = (title or "").lower()
            hits = sum(1 for t in set(terms) if t.rstrip("s") in low)
            if hits >= 2:
                by_title[rec] = max(by_title[rec], hits)
    counts = Counter(rec for t in texts for rec in RECORD.findall(t or ""))
    seen = [rec for rec, _ in by_title.most_common()]
    seen += [rec for rec, _ in counts.most_common() if rec not in seen]  # most-mentioned first
    out = []
    for rec in seen:
        rows = db.execute("SELECT meeting_id, date, body, action, title FROM agenda_items "
                          "WHERE record_number=? AND action != '' ORDER BY date", (rec,)).fetchall()
        if not rows:
            continue
        mid, date, body, action, title = rows[-1]
        t = Counter(v for (v,) in db.execute(
            "SELECT vote FROM votes WHERE record_number=? AND meeting_id=?", (rec, mid)))
        tally = f", roll call {t['Yea']} Yea / {t['Nay']} Nay" if t else ""
        out.append((rec, f"{rec}: {title[:200]} — {body} action: {action} on {date}{tally}."))
        if len(out) >= limit:
            break
    return out


def _cache_path():
    return path("data_dir") / "qa_cache.json"


def _load_cache():
    try:
        return json.loads(_cache_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(key, value):
    cache = _load_cache()
    cache[key] = value
    p = _cache_path()
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(cache, f, indent=1)
    os.replace(tmp, p)  # atomic: two app tabs can't leave a half-written file


def answer(question, alder=None, profile=None, use_cache=True):
    c = cfg()
    profile = profile or c["chat_profile"]
    prof = c["llm_profiles"][profile]
    key = json.dumps([" ".join(question.lower().split()), alder or "", profile, prof["model"]])
    if use_cache:
        hit = _load_cache().get(key)
        if hit:
            return hit | {"cached": True}

    t0 = time.time()
    trans, docs, filtered = retrieve(question, alder)
    size = int(prof.get("rag_source_chars", 2000))
    terms = _terms(question) + ([v for v in _alder_variants(alder)] if alder else [])
    sources, blocks = [], []

    # Official outcomes first (from records.db, not captions): record numbers the retrieved
    # sources mention, and same-meeting agenda items whose titles match the question.
    for rec, line in official_records([r["text"] for r in trans + docs]
                                      + [r["meta"].get("record_number", "") for r in docs],
                                      [r["meta"]["meeting_id"] for r in trans + docs],
                                      _terms(question)):
        n = len(sources) + 1
        sources.append({"kind": "record", "n": n, "date": "", "body": "City Clerk records",
                        "label": f"Official record {rec}", "link": "", "chunk_id": rec,
                        "snippet": line})
        blocks.append(f"[{n}] (official City Clerk record) {line}")

    # Small local models do better with fewer sources (profile: rag_transcripts / rag_documents).
    trans = trans[:int(prof.get("rag_transcripts", 8))]
    docs = docs[:int(prof.get("rag_documents", 4))]
    first_t = len(sources) + 1
    for r in trans + docs:
        m, n = r["meta"], len(sources) + 1
        excerpt = best_window(r["text"], terms, size)
        if "video_url" in m:
            label = f"{m['date']} · {m['body']} · captions at {hms(m['start_sec'])}"
            src = {"kind": "transcript", "link": m["video_url"], "start_sec": m["start_sec"]}
        else:
            label = f"{m['date']} · {m['body']} · {m['doc_name']}, p. {m['page']}"
            src = {"kind": "document", "link": m.get("doc_url", ""), "doc_name": m["doc_name"],
                   "page": m["page"]}
        sources.append(src | {"n": n, "date": m["date"], "body": m["body"], "label": label,
                              "chunk_id": r["id"], "snippet": excerpt[:400]})
        blocks.append(f"[{n}] ({'auto-captions' if src['kind'] == 'transcript' else 'document'}) "
                      f"{label}\n{excerpt}")

    who = (f"The question is about Alder {alder.split(',')[0]} ({alder}). Caption sources "
           f"{first_t}-{first_t + len(trans) - 1} "
           f"{'mention this alder' if filtered else 'are the closest matches; they may not mention this alder'}.\n"
           if alder else "")
    # Sources first, question last: small local models follow what they read last.
    user = ("Sources:\n\n" + "\n\n".join(blocks) + f"\n\n{who}Question: {question}\n\n"
            "Answer from the sources above, citing them like [3]. For words from auto-captions, "
            "write who \"likely said\" them. Say \"Not found in the records.\" only if no "
            "source mentions the topic at all.")
    text = chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], profile)
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()  # reasoning models
    if re.search(r"\[\d+\]", text):  # small models sometimes answer, then add "Not found" anyway
        text = re.sub(r"\s*Not found in the records\.?[^\n]*$", "", text).strip()

    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text)} & set(range(1, len(sources) + 1)))
    out = {"question": question, "alder": alder, "profile": profile, "model": prof["model"],
           "answer": text, "sources": sources, "cited": cited, "alder_filter_used": filtered,
           "seconds": round(time.time() - t0, 1), "cached": False}
    _save_cache(key, out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--alder")
    ap.add_argument("--profile")
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()
    r = answer(a.question, a.alder, a.profile, use_cache=not a.no_cache)
    print(f"[{r['profile']} / {r['model']}, {r['seconds']}s{', cached' if r['cached'] else ''}]\n")
    print(r["answer"], "\n")
    for s in r["sources"]:
        mark = "*" if s["n"] in r["cited"] else " "
        print(f"{mark}[{s['n']}] {s['label']}  {s['link']}")


if __name__ == "__main__":
    main()
