"""Step 1b: put the official structured records into one SQLite file.

No AI here. These are the reliable facts for the dashboards:
meetings, agenda items with their actions, legislation (sponsor, category),
and roll-call votes.

Usage: python build_records.py      -> data/records.db
"""
import json
import sqlite3
import sys

from common import path

SCHEMA = """
DROP TABLE IF EXISTS meetings; DROP TABLE IF EXISTS agenda_items;
DROP TABLE IF EXISTS legislation; DROP TABLE IF EXISTS votes;
CREATE TABLE meetings(meeting_id TEXT PRIMARY KEY, date TEXT, body TEXT, status TEXT,
  clerk_url TEXT, video_ids TEXT, has_captions INT, duration_sec INT);
CREATE TABLE agenda_items(meeting_id TEXT, date TEXT, body TEXT, record_number TEXT,
  matter_type TEXT, title TEXT, action TEXT, action_text TEXT, has_votes INT);
CREATE TABLE legislation(record_number TEXT PRIMARY KEY, title TEXT, type TEXT,
  category TEXT, sponsor TEXT, status TEXT, intro_date TEXT, final_date TEXT,
  committee TEXT, key_legislation TEXT);
CREATE TABLE votes(meeting_id TEXT, date TEXT, record_number TEXT, voter TEXT, vote TEXT);
"""


def main():
    archive = path("archive_dir")
    meetings = json.loads((archive / "index.json").read_text())["meetings"]
    db = sqlite3.connect(path("data_dir") / "records.db")
    db.executescript(SCHEMA)
    n_items = n_leg = n_votes = 0

    for m in meetings:
        folder = archive / m["folder"]
        vids = ",".join(t["language"].split()[0] for t in m.get("caption_tracks", []))
        dur = sum(x.get("duration", 0) or 0 for x in m.get("media", []))
        db.execute("INSERT INTO meetings VALUES (?,?,?,?,?,?,?,?)",
                   (m["id"], m["date"], m["body"], m["status"], m["source"], vids,
                    int(bool(vids)), int(dur)))

        mj = folder / "meeting.json"
        if mj.exists():
            meeting = json.loads(mj.read_text())
            for g in (meeting.get("agenda") or {}).get("groups") or []:
                for it in g.get("items") or []:
                    db.execute("INSERT INTO agenda_items VALUES (?,?,?,?,?,?,?,?,?)",
                               (m["id"], m["date"], m["body"], it.get("recordNumber"),
                                it.get("matterType"), it.get("matterTitle"), it.get("actionName"),
                                it.get("actionText"), int(bool(it.get("hasVotes")))))
                    n_items += 1
        else:
            print(f"  no meeting.json: {folder.name}", file=sys.stderr)

        for f in sorted((folder / "Legislation").glob("*.json")):
            L = json.loads(f.read_text())
            db.execute("INSERT OR REPLACE INTO legislation VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (L.get("recordNumber"), L.get("title"), L.get("type"),
                        L.get("matterCategory"), L.get("filingSponsor"),
                        L.get("statusDescription"), (L.get("introductionDate") or "")[:10],
                        (L.get("finalActionDate") or "")[:10], L.get("committeReferral"),
                        L.get("keyLegislation")))
            n_leg += 1

        for f in sorted((folder / "Votes").glob("*.json")):
            rows = json.loads(f.read_text()) or []
            for v in rows:
                db.execute("INSERT INTO votes VALUES (?,?,?,?,?)",
                           (m["id"], m["date"], f.stem, v.get("voterName"), v.get("vote")))
                n_votes += 1

    db.commit()
    print(f"meetings {len(meetings)}, agenda items {n_items}, legislation {n_leg}, votes {n_votes}")
    print("alders seen in votes:",
          db.execute("SELECT COUNT(DISTINCT voter) FROM votes").fetchone()[0])


if __name__ == "__main__":
    main()
