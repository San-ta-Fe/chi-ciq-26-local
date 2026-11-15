"""Step 1c: check the database works. Prints top matches with links.

Usage: python check_db.py "parking meter pension"
"""
import sys

from common import search, hms, collection


def main():
    q = " ".join(sys.argv[1:]) or "parking meter concession pension funds"
    for name in ("transcripts", "documents"):
        print(f"\n=== {name} ({collection(name).count()} chunks) ===")
        for r in search(q, name, k=5):
            m = r["meta"]
            where = (f"{hms(m['start_sec'])}  {m['video_url']}" if name == "transcripts"
                     else f"{m['doc_name']} p.{m['page']}")
            print(f"{r['score']:.2f}  {m['date']}  {m['body']}  {where}")
            print("      ", r["text"][:160].replace("\n", " "))


if __name__ == "__main__":
    main()
