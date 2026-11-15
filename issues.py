"""Step 4: big issues and how each was handled. Cloud model for picking and summarizing only.

1. Candidates (model): category counts + ~150 non-routine titles -> 8 resident-facing issues,
   each with a name, one-line description, 3 search queries and title keywords.
   Saved to data/issues/candidates.json and reused on later runs (edit it by hand to change
   the issues; --refresh asks the model again).
2. Trail (no AI): legislation / agenda items whose titles match the keywords ->
   introduced, committee agenda/summary mentions (from committee documents), council action,
   roll-call tally. Ordered by date.
3. Evidence: top 8 transcript chunks + top 4 document chunks for the issue's queries.
4. Summary (model): from trail + evidence only, citing excerpt numbers.
   Status comes from the trail, not the model.

Usage:
  python issues.py                 # all candidates
  python issues.py --only parking-meters
  python issues.py --refresh       # ask the model for new candidates
  -> data/issues/<slug>.json, data/issues/index.json
"""
import argparse
import json
import re
import sqlite3
from collections import Counter, OrderedDict, defaultdict

from common import cfg, chat, collection, hms, path, search

RECORD = re.compile(r"\b[A-Z]{1,3}r?\d{4}-\d{6,}\b")

# Routine categories left out of candidate titles and trails.
ROUTINE = re.compile(r"^(PARKING \| (Disabled|Handicapped|Loading|Residential|Buffer|Tow)|"
                     r"COMMENDATIONS|TRIBUTES|CLAIMS|STREETS \| Honorary|SIGNS|ALLEY|"
                     r"TRAFFIC \| Signs|ZONING RECLASSIFICATIONS|HISTORICAL LANDMARKS \| Permit|"
                     r"PERMITS|SIDEWALK|CANOPIES|GRANT OF PRIVILEGE|PAYMENTS|REFUNDS|"
                     r"APPOINTMENTS|SPECIAL SERVICE AREAS|PROPERTY \| Sale|"
                     r"MUNICIPAL CODE AMENDMENTS \| 4-60|RESTRICTED RESIDENTIAL|TRAFFIC|"
                     r"VEHICLE)", re.I)
ADDRESS = re.compile(r"\b(at|from|on) (\d|[NSEW] [A-Z])|\b(at|on) (a )?portions? of\b|\bportion\(s\) of\b|"
                     r"\bWard\b")
CEREMONIAL = re.compile(r"^(Congratulations|Gratitude|Tribute|Recognition|Honorary|Declaration|"
                        r"Condolence)|\bretirement\b", re.I)

CANDIDATE_PROMPT = """Below are counts of legislation categories and a sample of non-routine \
agenda item titles from the Chicago City Council, Nov 2025 - Nov 2026.

Pick 8 resident-facing, citywide issues that got real attention and debate this year (for \
example the budget, housing, policing, parking meters). Do not pick routine ward services \
(individual parking signs, permit zones, traffic signs, liquor moratoriums, honorary items). \
For each give:
- name: 2-4 words
- slug: lowercase-with-hyphens
- description: one neutral line
- queries: 3 short search queries for meeting transcripts
- title_keywords: 3-6 short phrases (1-3 words) that appear in the formal legislation titles \
below for this issue, e.g. "Metered Parking", "parking meter". Avoid words so broad they match \
unrelated items (not "City", "Amendment", "Code").

JSON only: {{"issues":[{{"name":"","slug":"","description":"","queries":["","",""],\
"title_keywords":[""]}}]}}

Category counts:
{cats}

Titles:
{titles}"""

SUMMARY_PROMPT = """Issue: {name} - {description}

Below are the official record trail for this issue (from City Clerk records) and numbered \
excerpts: [1]-[{nt}] are meeting auto-captions (may contain errors, speakers unknown), \
[{d0}]-[{dn}] are council documents.

Using only this material, write a neutral 4-6 sentence summary: what was discussed, what was \
decided, what is still open. Lead with the contested or citywide items, not routine ones. Copy \
dates (YYYY-MM-DD) and vote tallies (Yea-Nay) exactly from the trail; never guess them. Cite excerpts as [n] and record numbers as written. No opinions, no \
praise or blame, no names of speakers unless the excerpt states them.
Also write a one-line summary (max 20 words).

JSON only: {{"summary":"...","one_line":"...","cited":[1,2]}}

Record trail:
{trail}

Excerpts:
{excerpts}"""


def records():
    return sqlite3.connect(path("data_dir") / "records.db")


def candidates(db, profile, refresh):
    out = path("data_dir") / "issues" / "candidates.json"
    if out.exists() and not refresh:
        return json.loads(out.read_text())["issues"]
    cats = [(c, n) for c, n in db.execute("SELECT category, COUNT(*) FROM legislation "
                                          "GROUP BY category ORDER BY 2 DESC")
            if c and not ROUTINE.match(c)]
    rows = db.execute("SELECT l.committee, l.title, l.category FROM legislation l "
                      "ORDER BY l.key_legislation DESC, l.intro_date DESC").fetchall()
    by_committee = defaultdict(list)
    for com, title, cat in rows:
        if title and not ROUTINE.match(cat or ""):
            by_committee[com or "Other"].append(title[:160])
    titles, queues = [], [list(dict.fromkeys(v)) for v in by_committee.values()]
    while len(titles) < 150 and any(queues):  # round-robin across committees
        for q in queues:
            if q and len(titles) < 150:
                titles.append(q.pop(0))
    prompt = CANDIDATE_PROMPT.format(
        cats="\n".join(f"{c}: {n}" for c, n in cats if c),
        titles="\n".join(f"- {t}" for t in titles))
    data = ask_json(prompt, profile)
    out.write_text(json.dumps(data, indent=1))
    return data["issues"]


def ask_json(prompt, profile):
    for attempt in range(2):
        raw = chat([{"role": "user", "content": prompt}], profile, json_mode=True)
        try:
            return json.loads(re.sub(r"^```(?:json)?|```$", "", raw.strip()).strip())
        except json.JSONDecodeError:
            print(f"  bad JSON (attempt {attempt + 1}): {raw[:200]!r}")
    raise RuntimeError("model did not return JSON")


def committee_mentions():
    """record number -> committee documents (agenda / summary / letter) that list it."""
    out = defaultdict(list)
    _, _, texts, metas, _ = collection("documents")._load()
    for t, m in zip(texts, metas):
        if m["body"] == "City Council":
            continue
        for rec in set(RECORD.findall(t)):
            out[rec].append({"date": m["date"], "body": m["body"], "doc_name": m["doc_name"],
                             "doc_type": m["doc_type"], "page": m["page"],
                             "doc_url": m.get("doc_url", "")})
    return out


def build_trail(db, keywords, com_docs, cap=12):
    """Official steps for every matching record, ordered by date. No AI."""
    kw = [k.strip() for k in keywords if len(k.strip()) >= 4]
    if not kw:
        return []
    like = " OR ".join("lower(title) LIKE ?" for _ in kw)
    args = [f"%{k.lower()}%" for k in kw]
    recs = {}
    for r in db.execute(f"SELECT record_number, title, category, status, intro_date, final_date, "
                        f"committee, sponsor, key_legislation FROM legislation WHERE {like}", args):
        if not ROUTINE.match(r[2] or "") and not CEREMONIAL.search(r[1] or ""):
            recs[r[0]] = dict(zip(["record_number", "title", "category", "status", "intro_date",
                                   "final_date", "committee", "sponsor", "key"], r))
    for rec, title in db.execute(f"SELECT DISTINCT record_number, title FROM agenda_items "
                                 f"WHERE record_number IS NOT NULL AND ({like})", args):
        if CEREMONIAL.search(title or ""):
            continue
        recs.setdefault(rec, {"record_number": rec, "title": title, "category": "",
                              "status": "", "intro_date": "", "final_date": "",
                              "committee": "", "sponsor": "", "key": ""})

    if not recs:
        return []
    tallies = defaultdict(Counter)
    for rec, mid, vote in db.execute(
            f"SELECT record_number, meeting_id, vote FROM votes WHERE record_number IN "
            f"({','.join('?' * len(recs))})", list(recs)):
        tallies[(rec, mid)][vote] += 1

    contested = {rec for (rec, _), t in tallies.items() if t["Nay"] > 0}
    voted = {rec for (rec, _) in tallies}

    # Address-specific items ("Parking meters at 911 W Fulton Market") are ward routine:
    # leave them out when there are enough citywide items to tell the story.
    citywide = [r for r in recs.values() if not ADDRESS.search(r["title"] or "")]
    pool = citywide if len(citywide) >= 3 else list(recs.values())

    def weight(r):  # what to keep if there are too many: contested, key items, roll calls
        rec = r["record_number"]
        return (rec in contested, r["key"] == "YES", rec in voted, bool(com_docs.get(rec)),
                r["final_date"] or r["intro_date"])

    keep = sorted(pool, key=weight, reverse=True)[:cap]
    steps = []
    for r in keep:
        rec = r["record_number"]
        base = {"record_number": rec, "title": r["title"], "sponsor": r["sponsor"]}
        if r["intro_date"]:
            steps.append(base | {"date": r["intro_date"], "body": "City Council",
                                 "step": "introduced",
                                 "action": f"Introduced, referred to {r['committee']}"
                                 if r["committee"] and r["committee"] != "City Council"
                                 else "Introduced"})
        seen = set()
        for d in sorted(com_docs.get(rec, []), key=lambda d: d["date"]):
            if (d["date"], d["body"]) in seen:
                continue
            seen.add((d["date"], d["body"]))
            steps.append(base | {"date": d["date"], "body": d["body"], "step": "committee",
                                 "action": f"Listed in committee {d['doc_type'].lower()}",
                                 "source": f"{d['doc_name']}, p. {d['page']}",
                                 "doc_url": d["doc_url"]})
        for mid, date, body, action, text in db.execute(
                "SELECT meeting_id, date, body, action, action_text FROM agenda_items "
                "WHERE record_number=? ORDER BY date", (rec,)):
            t = tallies.get((rec, mid))
            steps.append(base | {"date": date, "body": body, "step": "council action",
                                 "action": action or "", "action_text": text or "",
                                 "tally": f"{t['Yea']} Yea / {t['Nay']} Nay" if t else ""})
        if (r["status"] or "").startswith("4-In Committee"):
            steps.append(base | {"date": r["intro_date"], "body": r["committee"],
                                 "step": "in committee", "action": "Still in committee"})
    steps.sort(key=lambda s: (s["date"] or "", s["record_number"]))
    return steps


def status_of(trail):
    """From the records, not the model."""
    if any(s["step"] == "council action" and (s["tally"] or s["action"] in
           ("Passed", "Adopted", "Approved", "Failed to Pass")) for s in trail):
        return "voted"
    if any(s["step"] in ("committee", "in committee", "introduced") for s in trail):
        return "in committee"
    return "discussed, no action recorded"


def evidence(queries, nt=8, nd=4):
    def top(coll, k):
        best = {}
        for q in queries:
            for r in search(q, coll, k=k):
                if r["id"] not in best or r["score"] > best[r["id"]]["score"]:
                    best[r["id"]] = r
        return sorted(best.values(), key=lambda r: -r["score"])[:k]

    out = []
    for r in top("transcripts", nt):
        m = r["meta"]
        out.append({"kind": "transcript", "chunk_id": r["id"], "date": m["date"],
                    "body": m["body"], "video_url": m["video_url"], "at": hms(m["start_sec"]),
                    "text": r["text"]})
    for r in top("documents", nd):
        m = r["meta"]
        out.append({"kind": "document", "chunk_id": r["id"], "date": m["date"],
                    "body": m["body"], "doc_name": m["doc_name"], "page": m["page"],
                    "doc_url": m.get("doc_url", ""), "text": r["text"]})
    for n, e in enumerate(out, 1):
        e["n"] = n
    return out


def trail_text(trail):
    """One line per record (all of them: a cut trail invites a wrong "no action")."""
    by_rec = OrderedDict()
    for s in trail:
        by_rec.setdefault(s["record_number"], []).append(s)
    lines = []
    for rec, steps in by_rec.items():
        parts = []
        for s in steps:
            if s["step"] == "introduced":
                parts.append(f"introduced {s['date']}")
            elif s["step"] == "committee":
                parts.append(f"on {s['body']} agenda {s['date']}")
            elif s["step"] == "council action":
                tally = f" {s['tally']}" if s.get("tally") else ""
                parts.append(f"{s['body']} {s['action']}{tally} on {s['date']}")
            else:
                parts.append(s["action"])
        lines.append(f"- {rec}: {steps[0]['title'][:160]}\n    " + "; ".join(parts))
    return "\n".join(lines) or "(no matching records)"


def fact_problems(summary, trail, ev):
    """Dates and vote tallies in the summary that are not in the trail or the excerpts."""
    known_dates = {s["date"] for s in trail} | {e["date"] for e in ev}
    known_tallies = set()
    for s in trail:
        mt = re.match(r"(\d+) Yea / (\d+) Nay", s.get("tally") or "")
        if mt:
            known_tallies.add(f"{mt.group(1)}-{mt.group(2)}")
    ev_text = " ".join(e["text"] for e in ev)
    bad = [d for d in re.findall(r"\b20\d\d-\d\d-\d\d\b", summary) if d not in known_dates]
    bad += [t for t in re.findall(r"(?<![\d-])(\d{1,2})[-–](\d{1,2})(?![\d-])", summary)
            for t in [f"{t[0]}-{t[1]}"] if t not in known_tallies and t not in ev_text]
    return bad


def run_issue(db, issue, com_docs, profile):
    trail = build_trail(db, issue.get("title_keywords", []), com_docs)
    ev = evidence(issue.get("queries") or [issue["name"]])
    nt = sum(e["kind"] == "transcript" for e in ev)
    excerpts = "\n\n".join(
        f"[{e['n']}] {e['date']} | {e['body']} | "
        + (f"captions at {e['at']}" if e["kind"] == "transcript" else f"{e['doc_name']} p.{e['page']}")
        + f"\n{e['text'][:2500]}" for e in ev)
    prompt = SUMMARY_PROMPT.format(name=issue["name"], description=issue["description"],
                                   nt=nt, d0=nt + 1, dn=len(ev),
                                   trail=trail_text(trail), excerpts=excerpts)
    data = ask_json(prompt, profile)
    problems = fact_problems(data.get("summary", ""), trail, ev)
    if problems:  # one retry, telling the model exactly what didn't match the records
        print(f"  summary had dates/tallies not in the records {problems}; asking again")
        data = ask_json(prompt + f"\n\nYour previous summary stated {problems}, which do not "
                        "appear in the record trail. Copy dates and vote tallies exactly from the "
                        "trail, as YYYY-MM-DD and Yea-Nay.", profile)
        problems = fact_problems(data.get("summary", ""), trail, ev)
    summary = data.get("summary", "")
    valid = {e["n"] for e in ev}
    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", summary)} & valid)
    # strip citations to excerpts that don't exist
    summary = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if int(m.group(1)) in valid else "", summary)
    records_cited = sorted(set(RECORD.findall(summary)))
    known = {s["record_number"] for s in trail}
    return {
        "name": issue["name"], "slug": issue["slug"], "description": issue["description"],
        "queries": issue.get("queries", []), "title_keywords": issue.get("title_keywords", []),
        "status": status_of(trail),
        "summary": summary, "one_line": data.get("one_line", ""),
        "cited_excerpts": cited,
        "records_cited_not_in_trail": [r for r in records_cited if r not in known],
        "trail": trail,
        "trail_records": len(known),
        "citywide_records": len({s["record_number"] for s in trail
                                 if not ADDRESS.search(s["title"] or "")}),
        "unverified_in_summary": problems,
        "evidence": [{k: v for k, v in e.items() if k != "text"} | {"snippet": e["text"][:300]}
                     for e in ev],
        "model_profile": profile, "model": cfg()["llm_profiles"][profile]["model"],
        "source_note": "Trail: official City Clerk records. Excerpts: Vimeo auto-captions "
                       "(may contain errors) and council documents.",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="one slug")
    ap.add_argument("--refresh", action="store_true", help="ask the model for new candidates")
    ap.add_argument("--profile", help="model profile (default: precompute_profile)")
    args = ap.parse_args()
    profile = args.profile or cfg()["precompute_profile"]

    outdir = path("data_dir") / "issues"
    outdir.mkdir(exist_ok=True)
    db = records()
    issues = candidates(db, profile, args.refresh)
    com_docs = committee_mentions()

    index_path = outdir / "index.json"
    index = {i["slug"]: i for i in json.loads(index_path.read_text())} if index_path.exists() else {}
    for issue in issues:
        if args.only and issue["slug"] != args.only:
            continue
        print(f"{issue['name']}  keywords={issue.get('title_keywords')}")
        out = run_issue(db, issue, com_docs, profile)
        (outdir / f"{issue['slug']}.json").write_text(json.dumps(out, indent=1))
        votes = [s for s in out["trail"] if s.get("tally")]
        print(f"  status={out['status']}, {out['trail_records']} records, {len(out['trail'])} steps, "
              f"{len(votes)} roll calls, cited {out['cited_excerpts']}")
        prev = index.get(issue["slug"], {})
        index[issue["slug"]] = {"slug": issue["slug"], "name": out["name"],
                                "status": out["status"], "one_line": out["one_line"],
                                "trail_records": out["trail_records"],
                                "citywide_records": out["citywide_records"],
                                "featured": prev.get("featured", out["citywide_records"] > 0)}
    # keep 5-8 featured: those with trails, in candidate order
    order = [i["slug"] for i in issues if i["slug"] in index]
    featured = [s for s in order if index[s]["featured"]][:8]
    for s in order:
        index[s]["featured"] = s in featured
    index_path.write_text(json.dumps([index[s] for s in order], indent=1))
    print(f"{len(featured)} featured issues -> {index_path}")


if __name__ == "__main__":
    main()
