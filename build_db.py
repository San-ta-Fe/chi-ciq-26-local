"""Step 1a: build the two vector collections (transcripts, documents).

Usage:
  python build_db.py --dry-run            # chunk only, print counts (no Ollama needed)
  python build_db.py                      # chunk + embed + store (resumable)
  python build_db.py --only transcripts   # or: --only documents
  python build_db.py --limit 5            # first 5 meetings, for a quick test

Re-running skips chunks already stored, so it is safe to stop and restart.
"""
import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

from common import cfg, path, embed, collection, vimeo_link

LINE = re.compile(r"^\[(\d+):(\d\d):(\d\d)(?:\.(\d+))?\]\s*(.*)$")
PAGE = re.compile(r"^--- Page (\d+) ---\s*$")


def load_index():
    return json.loads((path("archive_dir") / "index.json").read_text())["meetings"]


def video_id_of(track):
    return track["language"].split()[0]  # "1135569237 en-x-autogen" -> "1135569237"


def meeting_meta(m):
    return {"meeting_id": m["id"], "date": m["date"], "body": m["body"],
            "clerk_url": m["source"]}


# ---------- transcripts ----------

def parse_caption_txt(text):
    """Return [(seconds, line_text)] from '[HH:MM:SS.mmm] text' lines."""
    rows = []
    for line in text.splitlines():
        mt = LINE.match(line.strip())
        if mt and mt.group(5):
            h, mi, s = int(mt.group(1)), int(mt.group(2)), int(mt.group(3))
            rows.append((h * 3600 + mi * 60 + s, mt.group(5)))
    return rows


def window_chunks(rows, window, step):
    """Cut timed lines into overlapping time windows."""
    if not rows:
        return []
    chunks, start, end_time = [], rows[0][0], rows[-1][0]
    while start <= end_time:
        piece = [t for (sec, t) in rows if start <= sec < start + window]
        if piece:
            chunks.append((start, " ".join(piece)))
        start += step
    return chunks


def transcript_chunks(meetings, c):
    seen_videos = set()
    archive = path("archive_dir")
    for m in meetings:
        for tr in m.get("caption_tracks", []):
            vid = video_id_of(tr)
            if vid in seen_videos:  # same video filed under two meetings
                continue
            seen_videos.add(vid)
            f = archive / m["folder"] / tr["text"]
            if not f.exists():
                print(f"  missing transcript: {f}", file=sys.stderr)
                continue
            raw = f.read_text(errors="replace")
            h = hashlib.sha256(raw.encode()).hexdigest()
            if h in seen_videos:  # identical captions under another name (clerk attachment)
                continue
            seen_videos.add(h)
            if not vid.isdigit():  # not a Vimeo id, so no working link
                print(f"  skipping non-Vimeo caption track: {f}", file=sys.stderr)
                continue
            rows = parse_caption_txt(raw)
            for start, text in window_chunks(rows, c["transcript_window_sec"], c["transcript_step_sec"]):
                meta = meeting_meta(m) | {
                    "video_id": vid, "start_sec": start,
                    "video_url": vimeo_link(vid, start), "source": "Vimeo auto-captions",
                }
                yield f"t-{vid}-{start}", text, meta


# ---------- documents ----------

def split_text(text, size, overlap):
    """Split by page markers, then into ~size-char pieces; keep page numbers."""
    pages, cur_page, buf = [], 1, []
    for line in text.splitlines():
        mp = PAGE.match(line)
        if mp:
            if buf:
                pages.append((cur_page, "\n".join(buf)))
            cur_page, buf = int(mp.group(1)), []
        else:
            buf.append(line)
    if buf:
        pages.append((cur_page, "\n".join(buf)))

    for page, ptext in pages:
        ptext = re.sub(r"[ \t]+", " ", ptext).strip()
        i = 0
        while i < len(ptext):
            piece = ptext[i:i + size]
            if len(piece.strip()) > 80:  # skip near-empty bits
                yield page, piece
            i += size - overlap


def document_chunks(meetings, c):
    seen_hashes = set()
    archive = path("archive_dir")
    for m in meetings:
        for f in m.get("files", []):
            if f.get("type") not in c["doc_types"] or not f.get("text_path"):
                continue
            if f.get("sha256") in seen_hashes:  # same file attached to two meetings
                continue
            seen_hashes.add(f.get("sha256"))
            p = archive / m["folder"] / f["text_path"]
            if not p.exists():
                print(f"  missing doc text: {p}", file=sys.stderr)
                continue
            rec = re.search(r"\b([A-Z]{1,3}\d{4}-\d{5,})\b", f["name"])  # e.g. O2026-0029681
            for n, (page, piece) in enumerate(split_text(p.read_text(errors="replace"),
                                                         c["doc_chunk_chars"], c["doc_overlap_chars"])):
                meta = meeting_meta(m) | {
                    "doc_name": f["name"], "doc_type": f["type"], "page": page,
                    "doc_url": f.get("source", ""), "record_number": rec.group(1) if rec else "",
                }
                yield f"d-{f['sha256'][:16]}-{n}", piece, meta


# ---------- embed + store ----------

def store(name, chunks, batch_size, dry_run):
    chunks = list(chunks)
    print(f"[{name}] {len(chunks)} chunks")
    if dry_run:
        for cid, text, meta in chunks[:2]:
            print("  e.g.", cid, json.dumps(meta)[:200], "|", text[:150].replace("\n", " "))
        return
    coll = collection(name)
    existing = set(coll.get(include=[])["ids"])
    todo = [ch for ch in chunks if ch[0] not in existing]
    print(f"[{name}] already stored {len(existing)}, to embed {len(todo)}")
    t0 = time.time()
    for i in range(0, len(todo), batch_size):
        batch = todo[i:i + batch_size]
        vecs = embed([b[1] for b in batch], kind="doc")
        coll.add(ids=[b[0] for b in batch], embeddings=vecs,
                 documents=[b[1] for b in batch], metadatas=[b[2] for b in batch])
        done = i + len(batch)
        if done % (batch_size * 10) == 0 or done == len(todo):
            rate = done / max(time.time() - t0, 1e-6)
            left = (len(todo) - done) / max(rate, 1e-6)
            print(f"  {done}/{len(todo)}  ~{rate:.0f} chunks/s  ~{left / 60:.0f} min left")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", choices=["transcripts", "documents"])
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    c = cfg()
    meetings = [m for m in load_index() if m["status"] != "Cancelled"]
    if a.limit:
        meetings = meetings[:a.limit]
    print(f"{len(meetings)} meetings")
    bs = c["embedding"]["batch_size"]
    if a.only in (None, "transcripts"):
        store("transcripts", transcript_chunks(meetings, c), bs, a.dry_run)
    if a.only in (None, "documents"):
        store("documents", document_chunks(meetings, c), bs, a.dry_run)


if __name__ == "__main__":
    main()
