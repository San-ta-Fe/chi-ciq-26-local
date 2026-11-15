"""Step 2: rank alders to choose the featured ones for the demo.

No AI here. For each alder in the roll-call votes:
  - caption mentions of "Alderman/Alderwoman/Alderperson/Alder/Chair/Chairman/Chairwoman <surname>"
    across all transcript .txt files (one per video, duplicate videos skipped),
  - mentions as "Chair..." separately (a hint that they chair a committee),
  - sponsored items in `legislation`, roll-call votes in `votes`.

Usage:
  python pick_alders.py                         # print ranked table, write data/alder_candidates.json
  python pick_alders.py --archive /other/path   # read captions from another copy of the archive
  python pick_alders.py --choose "Lopez, Raymond A." "Burnett, Walter R." ...
                                                # write those names to featured_alders in config.json
  python pick_alders.py --auto                  # top 4 by mentions, at least one likely chair
"""
import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from common import CONFIG_PATH, cfg, path

TITLES = r"(?:alderman|alderwoman|alderperson|alder person|alder|chairman|chairwoman|chairperson|chair)"
CHAIR_TITLES = {"chairman", "chairwoman", "chairperson", "chair"}

# Caption misspellings seen in the archive (lower case, accents removed) -> voter name.
ALIASES = {
    "Reilly, Brendan": ["riley", "reilley"],
    "Ervin, Jason C.": ["irvin", "irving", "erwin"],
    "Gardiner, James M.": ["gardner"],
    "Knudsen, Timothy R.": ["knutson", "knudson", "knutsen"],
    "La Spata, Daniel": ["laspata", "laspada", "lospada", "la spada", "las spata"],
    "Beale, Anthony": ["beal", "beel"],
    "Villegas, Gilbert": ["viegas", "vilegas", "villages"],
    "Quezada, Anthony J.": ["quesada"],
    "Mosley, Ronnie L.": ["moseley", "mosely"],
    "Mitts, Emma": ["mitz", "mits"],
    "Yancy, Desmon C.": ["yancey"],
    "Tabares, Silvana": ["tavares", "tabarez"],
    "Waguespack, Scott": ["waguespak", "wagaspack"],
    "Napolitano, Anthony V.": ["napalitano"],
    "Taliaferro, Chris": ["tolliver", "taliaferra"],
    "Manaa-Hoppenworth, Leni": ["hoppenworth", "manaa hoppenworth", "manna hoppenworth"],
    "Sigcho-Lopez, Byron": ["sigcho", "sigcho lopez", "sicho lopez", "sigo lopez",
                            "cintra lopez", "sintra lopez"],
    "Rodriguez Sanchez, Rossana": ["rodriguez sanchez", "sanchez"],
    "Cardona, Jr., Felix": ["cardona"],
    "Vasquez, Jr., Andre": ["vasquez", "vazquez"],
}

# Surnames shared by two alders: a bare mention is credited to the first, and flagged.
AMBIGUOUS = {
    "lopez": ("Lopez, Raymond A.", "Sigcho-Lopez, Byron"),
    "rodriguez": ("Rodriguez, Michael D.", "Rodriguez Sanchez, Rossana"),
}


def fold(s: str) -> str:
    """Lower case, accents removed, hyphens as spaces."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower().replace("-", " ")).strip()


def surname_of(voter: str) -> str:
    return voter.split(",")[0].strip()


def variants(voter: str) -> set:
    sur = surname_of(voter)
    v = {fold(sur), fold(sur.replace(" ", "")), fold(sur.replace("-", ""))}
    v |= {fold(a) for a in ALIASES.get(voter, [])}
    return {x for x in v if x}


def caption_files(archive: Path):
    """One .txt per video, as in build_db.py (same video under two meetings counted once)."""
    meetings = json.loads((archive / "index.json").read_text())["meetings"]
    seen = set()
    for m in meetings:
        for tr in m.get("caption_tracks", []):
            vid = tr["language"].split()[0]
            if vid in seen:
                continue
            seen.add(vid)
            f = archive / m["folder"] / tr["text"]
            if not f.exists():
                print(f"  missing transcript: {f}", file=sys.stderr)
                continue
            h = hashlib.sha256(f.read_bytes()).hexdigest()
            if h in seen or not vid.isdigit():  # duplicate captions / not a Vimeo video
                continue
            seen.add(h)
            yield m, vid, f


def caption_text(f: Path) -> str:
    """Join caption lines (names often break across lines) without the timestamps."""
    lines = (re.sub(r"^\[[\d:.]+\]\s*", "", l) for l in f.read_text(errors="replace").splitlines())
    return fold(" ".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", help="archive folder (default: archive_dir in config.json)")
    ap.add_argument("--choose", nargs="+", metavar="NAME", help="voter names to feature")
    ap.add_argument("--auto", action="store_true", help="take the top 4, incl. one likely chair")
    args = ap.parse_args()

    db = sqlite3.connect(path("data_dir") / "records.db")
    voters = [r[0] for r in db.execute("SELECT DISTINCT voter FROM votes ORDER BY voter")]

    if args.choose:
        return write_featured(args.choose, voters)

    archive = Path(args.archive).expanduser() if args.archive else path("archive_dir")
    if not (archive / "index.json").exists():
        sys.exit(f"No index.json in {archive}. Pass --archive <folder>.")

    # variant (folded) -> voter. Longer variants first so "sigcho lopez" wins over "lopez".
    var_to_voter = {}
    for v in voters:
        for x in variants(v):
            var_to_voter.setdefault(x, v)
    for sur, (first, _) in AMBIGUOUS.items():
        var_to_voter[sur] = first
    alts = sorted(var_to_voter, key=len, reverse=True)
    pat = re.compile(rf"\b({TITLES})\s+({'|'.join(re.escape(a) for a in alts)})\b")

    mentions, chair_mentions, ambiguous = Counter(), Counter(), Counter()
    meetings_with = defaultdict(set)
    bodies = defaultdict(Counter)
    n_files = 0
    for m, vid, f in caption_files(archive):
        n_files += 1
        for mt in pat.finditer(caption_text(f)):
            title, name = mt.group(1), mt.group(2)
            voter = var_to_voter[name]
            mentions[voter] += 1
            if title in CHAIR_TITLES:
                chair_mentions[voter] += 1
                bodies[voter][m["body"]] += 1
            if name in AMBIGUOUS:
                ambiguous[voter] += 1
            meetings_with[voter].add(m["id"])

    sponsored = dict(db.execute("SELECT sponsor, COUNT(*) FROM legislation GROUP BY sponsor"))
    vote_rows = {r[0]: r[1:] for r in db.execute(
        "SELECT voter, COUNT(DISTINCT record_number), SUM(vote='Yea'), SUM(vote='Nay') "
        "FROM votes GROUP BY voter")}

    rows = []
    for v in voters:
        chair_of = bodies[v].most_common(1)[0][0] if chair_mentions[v] >= 20 else None
        rows.append({
            "name": v,
            "surname": surname_of(v),
            "variants": sorted(variants(v)),
            "caption_mentions": mentions[v],
            "meetings_mentioned": len(meetings_with[v]),
            "chair_mentions": chair_mentions[v],
            "likely_chair_of": chair_of,
            "ambiguous_mentions": ambiguous[v],
            "sponsored_items": sponsored.get(v, 0),
            "rollcall_items": vote_rows[v][0],
            "yea": vote_rows[v][1],
            "nay": vote_rows[v][2],
        })
    rows.sort(key=lambda r: r["caption_mentions"], reverse=True)

    out = path("data_dir") / "alder_candidates.json"
    out.write_text(json.dumps({"caption_files": n_files, "archive": str(archive),
                               "alders": rows}, indent=1))

    print(f"{n_files} caption files read. Mentions are a rough signal (roll calls count too).\n")
    print(f"{'#':>2}  {'alder':28} {'mentions':>8} {'mtgs':>5} {'chair':>5} {'spons':>5} "
          f"{'votes':>5} {'nay':>4}  likely chair of")
    for i, r in enumerate(rows, 1):
        flag = "*" if r["ambiguous_mentions"] else " "
        print(f"{i:>2}  {r['name']:28}{flag}{r['caption_mentions']:>8} {r['meetings_mentioned']:>5} "
              f"{r['chair_mentions']:>5} {r['sponsored_items']:>5} {r['rollcall_items']:>5} "
              f"{r['nay']:>4}  {r['likely_chair_of'] or ''}")
    print("\n* includes bare-surname mentions shared with another alder (Lopez, Rodriguez).")
    print(f"Wrote {out}")

    if args.auto:
        top = [r["name"] for r in rows[:4]]
        if not any(r["likely_chair_of"] for r in rows[:4]):
            chair = next(r["name"] for r in rows if r["likely_chair_of"])
            top[-1] = chair
        write_featured(top, voters)


def write_featured(names, voters):
    bad = [n for n in names if n not in voters]
    if bad:
        sys.exit(f"Not exactly as in votes: {bad}")
    if not 3 <= len(names) <= 5:
        sys.exit("Choose 3 to 5 alders.")
    # Edit only the featured_alders line so the rest of config.json keeps its layout.
    text = CONFIG_PATH.read_text()
    new = re.sub(r'"featured_alders"\s*:\s*\[[^\]]*\]',
                 '"featured_alders": ' + json.dumps(names), text)
    CONFIG_PATH.write_text(new)
    assert cfg()["featured_alders"] == names
    print("featured_alders =", names)


if __name__ == "__main__":
    main()
