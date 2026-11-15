"""Step 3a: plain facts for each featured alder. No AI.

From records.db (official):
  - roll-call votes: Yea / Nay / other counts; items where they voted against the majority
  - sponsored legislation: count by category, titles with status
From the captions (inferred, "likely"):
  - meetings where they were named with a title ("Alderman Lopez", "Chair Ervin"),
    count by committee, dates, and a link to the first mention in each meeting.

Usage: python alder_facts.py [--archive DIR]   -> data/alders/<slug>.facts.json, data/alders/index.json
"""
import argparse
import bisect
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from common import cfg, path, vimeo_link
from pick_alders import AMBIGUOUS, TITLES, caption_files, fold, surname_of, variants

LINE = re.compile(r"^\[(\d+):(\d\d):(\d\d)(?:\.\d+)?\]\s*(.*)$")


def slug(voter: str) -> str:
    sur, rest = voter.split(",", 1)
    first = rest.replace("Jr.", "").replace(",", "").split()[0]
    return re.sub(r"[^a-z0-9]+", "-", fold(f"{sur} {first}")).strip("-")


def name_regex(voter: str, voters: list) -> str:
    """Regex (on folded text) for this alder's surname variants, excluding longer names of
    other alders that end in the same word ("sigcho lopez" is not Raymond Lopez)."""
    mine = variants(voter)
    if fold(surname_of(voter)) in AMBIGUOUS and AMBIGUOUS[fold(surname_of(voter))][0] == voter:
        mine.add(fold(surname_of(voter)))
    parts = []
    for v in sorted(mine, key=len, reverse=True):
        blockers = set()
        for other in voters:
            if other == voter:
                continue
            for ov in variants(other):
                if ov.endswith(" " + v):
                    blockers.add(ov[: -len(v)])  # e.g. "sigcho "
        look = "".join(f"(?<!{re.escape(b)})" for b in sorted(blockers))
        parts.append(look + re.escape(v))
    return r"\b(?:" + "|".join(parts) + r")\b"


def timed_text(f: Path):
    """Folded caption text joined into one string, plus line start offsets and times."""
    offsets, times, pieces, pos = [], [], [], 0
    for line in f.read_text(errors="replace").splitlines():
        mt = LINE.match(line.strip())
        if not mt or not mt.group(4):
            continue
        t = fold(mt.group(4))
        offsets.append(pos)
        times.append(int(mt.group(1)) * 3600 + int(mt.group(2)) * 60 + int(mt.group(3)))
        pieces.append(t)
        pos += len(t) + 1
    return " ".join(pieces), offsets, times


def vote_facts(db, voter):
    counts = Counter(v for (v,) in db.execute("SELECT vote FROM votes WHERE voter=?", (voter,)))
    titles = dict(db.execute("SELECT record_number, title FROM legislation"))
    titles.update({r: t for r, t in db.execute(
        "SELECT record_number, title FROM agenda_items WHERE record_number IS NOT NULL")
        if r not in titles})
    tallies = defaultdict(Counter)
    for mid, rec, vote in db.execute("SELECT meeting_id, record_number, vote FROM votes"):
        tallies[(mid, rec)][vote] += 1
    minority = []
    for mid, date, rec, vote in db.execute(
            "SELECT meeting_id, date, record_number, vote FROM votes WHERE voter=? "
            "AND vote IN ('Yea','Nay') ORDER BY date, record_number", (voter,)):
        t = tallies[(mid, rec)]
        if t["Yea"] == t["Nay"]:
            continue
        majority = "Yea" if t["Yea"] > t["Nay"] else "Nay"
        if vote != majority:
            minority.append({"date": date, "meeting_id": mid, "record_number": rec,
                             "title": titles.get(rec, ""), "their_vote": vote,
                             "tally": f"{t['Yea']} Yea / {t['Nay']} Nay",
                             "result": "passed" if majority == "Yea" else "failed"})
    return {
        "source": "Official roll-call records (City Clerk)",
        "rollcall_items": sum(counts.values()),
        "meetings": db.execute("SELECT COUNT(DISTINCT meeting_id) FROM votes WHERE voter=?",
                               (voter,)).fetchone()[0],
        "yea": counts["Yea"], "nay": counts["Nay"],
        "other": {k: n for k, n in counts.items() if k not in ("Yea", "Nay")},
        "voted_differently_from_majority": minority,
    }


def sponsor_facts(db, voter):
    rows = db.execute("SELECT record_number, title, type, category, status, intro_date, "
                      "final_date, committee FROM legislation WHERE sponsor=? "
                      "ORDER BY intro_date DESC", (voter,)).fetchall()
    keys = ["record_number", "title", "type", "category", "status", "intro_date",
            "final_date", "committee"]
    items = [dict(zip(keys, r)) for r in rows]
    return {"source": "Official legislation records (City Clerk), filing sponsor",
            "count": len(items),
            "by_category": dict(Counter(i["category"] or "Other" for i in items).most_common()),
            "items": items}


def mention_facts(archive, featured, voters):
    title_pats = {v: re.compile(rf"\b{TITLES}\s+{name_regex(v, voters)}") for v in featured}
    per = {v: {} for v in featured}  # voter -> meeting_id -> info
    for m, vid, f in caption_files(archive):
        text, offsets, times = timed_text(f)
        for v, pat in title_pats.items():
            hits = [mt.start() for mt in pat.finditer(text)]
            if not hits:
                continue
            first = times[bisect.bisect_right(offsets, hits[0]) - 1]
            info = per[v].setdefault(m["id"], {"date": m["date"], "body": m["body"],
                                               "mentions": 0, "videos": []})
            info["mentions"] += len(hits)
            info["videos"].append({"video_id": vid, "first_mention_sec": first,
                                   "video_url": vimeo_link(vid, first)})
    out = {}
    for v, meetings in per.items():
        rows = sorted(({"meeting_id": k} | i for k, i in meetings.items()), key=lambda r: r["date"])
        out[v] = {
            "source": "Vimeo auto-captions; names matched by text, so this is likely, not official. "
                      "Includes roll calls.",
            "meetings": len(rows),
            "by_body": dict(Counter(r["body"] for r in rows).most_common()),
            "list": rows,
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", help="archive folder (default: archive_dir in config.json)")
    args = ap.parse_args()
    archive = Path(args.archive).expanduser() if args.archive else path("archive_dir")

    featured = cfg()["featured_alders"]
    db = sqlite3.connect(path("data_dir") / "records.db")
    voters = [r[0] for r in db.execute("SELECT DISTINCT voter FROM votes")]
    outdir = path("data_dir") / "alders"
    outdir.mkdir(exist_ok=True)

    mentions = mention_facts(archive, featured, voters)
    index = []
    for v in featured:
        s = slug(v)
        facts = {"name": v, "slug": s, "surname": surname_of(v),
                 "votes": vote_facts(db, v), "sponsored": sponsor_facts(db, v),
                 "named_in_meetings": mentions[v]}
        (outdir / f"{s}.facts.json").write_text(json.dumps(facts, indent=1))
        index.append({"name": v, "slug": s, "surname": surname_of(v),
                      "name_regex": name_regex(v, voters)})
        vf = facts["votes"]
        print(f"{v:24} votes {vf['rollcall_items']} (Yea {vf['yea']}, Nay {vf['nay']}), "
              f"minority {len(vf['voted_differently_from_majority'])}, "
              f"sponsored {facts['sponsored']['count']}, named in {mentions[v]['meetings']} meetings")
    (outdir / "index.json").write_text(json.dumps(index, indent=1))
    print(f"Wrote {len(index)} facts files to {outdir}")


if __name__ == "__main__":
    main()
