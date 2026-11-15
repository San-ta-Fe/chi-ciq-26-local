# Know Your Alder — local demo: build plan for Claude Code

You are building a demo web app on a 16GB Mac, in a few hours, for one person.
Follow the steps in order. Each step ends with a **Done when** check; do not move on until it passes.
If a step fails twice, take the simplest fallback listed and keep going. Time matters more than polish.

## What we are building

A Streamlit app (a web page written in Python) with two pages:

1. **Alders**: pick one of 3–5 featured alders, see pre-computed facts and topics, ask questions about what they did in council meetings this past year.
2. **Issues**: see 5–8 pre-computed big issues and how each was handled (discussed → ordinance → committee action → council vote), then ask about any issue.

Data: the Chicago City Clerk archive, Nov 11 2025 – Nov 11 2026 (261 meetings, 202 with Vimeo auto-captions, ~10,500 documents, roll-call votes for 25 meetings). No audio, no Whisper.

## Rules (apply to every step)

- **Stay inside the repo.** Every file the project creates goes inside `chi-ciq-26-local`. Paths in `config.json` that aren't full paths (`db`, `data`) are inside the repo; keep them that way.

- **Neutral.** Same format for every alder. No scores, ratings or labels like "weak on X". Only plain facts ("spoke on housing in 4 meetings", "voted Nay on 3 items").
- **Every claim links to its source**: a video moment (`https://vimeo.com/<id>#t=<sec>s`) or a document name and page.
- **Speakers are inferred.** Captions have no speaker names. Anything attributed from captions is shown as "likely speaker", with the link. Facts from votes and sponsorship records are shown as official.
- **Label sources on screen**: "Transcripts are Vimeo auto-captions and may contain errors."
- **Quotes must be real**: any quote shown must appear word for word in the stored chunk text. Drop any that don't.
- **All model calls go through `common.py`** (`chat()` and `embed()`). Never hard-code a model or address elsewhere. `config.json` is re-read on every call, so switching local ↔ cloud needs no code change.
- **No secrets in files.** The cloud key is read from the environment variable named in `config.json` (`CLOUD_API_KEY` by default).
- Every script reads files and writes files, and can be run on its own. This is what lets it move to Fuzzball/PGX later.

## Files

```
chi-ciq-26-local/         the repo. EVERYTHING the project writes stays inside it
                          (db/, data/, .venv/, .env). Never write to ~/kya-demo or anywhere
                          else outside the repo. Only input read from outside: archive_dir
                          (~/Downloads/chicago-city-council-archive, read only).
  config.json             paths, model profiles, chunk sizes, featured_alders
  common.py               config, chat(), embed(), search(), vector store   [exists]
  build_db.py             step 1a: chunk + embed → 2 collections            [exists]
  build_records.py        step 1b: official records → data/records.db       [exists]
  check_db.py             step 1c: test search                              [exists]
  pick_alders.py          step 2
  alder_facts.py          step 3a (no AI)
  alder_insights.py       step 3b (cloud model)
  issues.py               step 4  (cloud model)
  rag.py                  step 5  (live Q&A)
  app.py, pages/1_Alders.py, pages/2_Issues.py   step 5
  vectorstore.py          small search store: SQLite + numpy (no chromadb)    [exists]
  db/transcripts.db, db/documents.db   the two searchable collections (created)
  data/records.db, data/alders/*.json, data/issues/*.json, data/qa_cache.json
```

## Step 0 — Setup (15 min)

Do not install chromadb: it needs onnxruntime, which has no build for this Mac. `vectorstore.py` replaces it, using `collection(name).query(query_embeddings, n_results, where={field: value}, where_document={"$contains": text})`.

```bash
cd "/Volumes/My Shared Files/InVitro/chi-ciq-26-local"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
brew install ollama   # or the Mac app from ollama.com; then make sure it is running
ollama pull nomic-embed-text
ollama pull qwen2.5:3b          # fallback if slow: llama3.2:3b
ollama pull nomic-embed-text
export CLOUD_API_KEY=...        # the user provides this
```

In `config.json`, set `llm_profiles.cloud.base_url` and `model` to the user's provider. Any provider with an OpenAI-compatible API works. Ask the user which provider and model if they aren't set.
Check `archive_dir` points at the archive folder.

**Done when:** `python -c "from common import chat; print(chat([{'role':'user','content':'say ok'}], 'local'))"` prints a reply, and the same with `'cloud'`.

## Step 1 — Build the knowledge base (≈1 hour, mostly waiting)

```bash
python build_records.py                  # seconds
python build_db.py --dry-run             # chunk counts only, no embedding
python build_db.py --limit 5             # quick real test
python check_db.py "parking meter pension"
python build_db.py                       # full run; resumable; run in background
```

- `transcripts` collection: 3-minute caption windows (2.5-min step), duplicate videos skipped. Metadata: meeting_id, date, body, video_id, start_sec, video_url.
- `documents` collection: Agenda, Summary, Committee Letter texts in 1,500-character pieces with page numbers. Legislation and Exhibits are left out to save time. Add `"Legislation"` to `doc_types` only if time allows.
- `records.db` tables: `meetings`, `agenda_items` (title, record number, action, action text), `legislation` (sponsor, category, status), `votes` (record number, voter, Yea/Nay).
- Expect about 13k transcript chunks and under 10k document chunks. The full run prints speed and time left. If it estimates more than 60 minutes, stop and run `--only transcripts` first.

**Done when:** `check_db.py` shows the Nov 2, 2026 City Council meeting near the top for "parking meter pension", with a working Vimeo link. `records.db` has a 44 Yea / 6 Nay vote on O2026-0029681.

While the full embed runs, do steps 2 and 3a; they don't need it.

## Step 2 — Pick featured alders (15 min)

`pick_alders.py`:
- Alder list = distinct `voter` in `votes` (format "Last, First M."). Build surname variants (e.g. "Lopez", "López"), plus a small manual alias map for caption misspellings you spot.
- For each alder count: caption mentions of "Alderman/Alderperson/Alder/Chairman/Chairwoman <surname>" across all transcript `.txt` files; sponsored items in `legislation`; roll-call votes.
- Print a ranked table and write `data/alder_candidates.json`.
- **Ask the user to choose 3–5.** If no answer, take the top 4 by mentions, including at least one committee chair. Write them to `featured_alders` in `config.json`.

**Done when:** `featured_alders` has 3–5 names exactly as they appear in `votes`.

## Step 3 — Alder pre-computation (45 min)

**3a `alder_facts.py` (no AI)** → `data/alders/<slug>.facts.json`:
- Votes: count of Yea / Nay / other. Items where they voted differently from the majority (record number, title, their vote, the tally).
- Sponsored legislation: count by `category`, list of titles with status.
- Meetings where they were called on by name: count by committee body, plus the dates.

**3b `alder_insights.py` (cloud profile, `json_mode=True`)** → `data/alders/<slug>.insights.json`:
- Gather evidence: transcript chunks containing the surname (`where_document={"$contains": surname}`, also try variants). Cap at about 60, spread across meetings. Also the windows right after a "you're recognized" mention: the chunk containing it and the next one.
- Prompt: "You are given numbered excerpts from Chicago council meeting auto-captions where Alder X is likely speaking or being addressed. List 3–6 topics this alder spoke about most. For each topic: a neutral 1–2 sentence summary of what they said or asked, and up to 2 short exact quotes with the excerpt number. No opinions, no ratings. JSON: {topics:[{topic, summary, quotes:[{text, excerpt}]}]}".
- After the call: keep a quote only if its text appears word for word in that excerpt; attach that excerpt's video_url and date. Drop topics left with no evidence.
- Also write 3 suggested questions per alder (for the Q&A box).

**Done when:** each featured alder has a facts file and an insights file, and every quote has a link. Open 2 links and check the moment matches.

## Step 4 — Issues pre-computation (45 min)

`issues.py` (cloud profile) → `data/issues/<slug>.json`, plus `data/issues/index.json`:
1. **Find candidates:** send the model `legislation.category` counts and about 150 sample agenda item titles (spread across committees, skipping routine items such as payments, permits and honorary resolutions). Ask for 8 resident-facing issues (e.g. budget, housing, policing, parking meters), each with a name, a one-line description and 3 search queries.
2. **For each issue, build the trail from records** (no AI): agenda_items and legislation whose titles match the issue keywords → record number, committee, action, date, and vote tally from `votes`. Order by date.
3. **Evidence:** the top 8 transcript chunks and top 4 document chunks for the issue's queries.
4. **Summary (cloud model):** from the trail and evidence only: "what was discussed, what was decided, what is still open". Neutral, 4–6 sentences, citing excerpt numbers. Mark the status as `voted`, `in committee` or `discussed, no action recorded`, based on the trail, not the model.
5. Keep 5–8 issues; the user hand-picks if there are more. Set `featured: true/false` in index.json.

**Done when:** at least 5 issues have a trail with real record numbers, and every cited excerpt has a link. Check the parking-meter issue shows O2026-0029681 passed 44–6 on 2026-11-02.

## Step 5 — App (1 hour)

`rag.py`: `answer(question, alder=None, profile=None)`:
- Retrieve 8 transcript chunks (filtered by surname with `where_document` if an alder is given; if fewer than 3 come back, run again without the filter) and 4 document chunks.
- Prompt: answer only from the numbered sources, cite as [1], [2], say "not found in the records" if absent, and stay neutral.
- Return the answer and the sources (date, body, link, snippet). Cache by (question, alder, profile) in `data/qa_cache.json`.

`app.py` + `pages/`:
- **Sidebar**: model selector (radio: profiles from `config.json`, default `chat_profile`), and the source label.
- **Alders page**: alder picker → header with a facts row (meetings called on, items sponsored, roll-call votes, times in the minority) → topic cards (summary, quotes with "▶ watch" links, each marked "likely speaker") → sponsored-items table → "voted differently from majority" table → question box with suggested-question buttons → answer with numbered source links.
- **Issues page**: issue cards (name, status, one-line summary) → click to see the trail as a timeline table (date, committee, action, vote tally, record number) and the evidence links → a free question box for any issue (`rag.answer` without an alder filter).
- Read only from `data/*.json`, `records.db` and the two `db/*.db` collections. No pre-computation inside the app.

**Done when:** `streamlit run app.py` opens. Both pages work. Switching the sidebar model changes which model answers, with no restart.

## Step 6 — Demo polish (30 min)

- Run every suggested question with `local`. If one takes more than 30s or answers badly, run it with `cloud` and keep it in the cache for the demo.
- Check 5 random links on screen.
- Write `DEMO.md`: a 3-minute script. Open with one alder (facts → a topic → click a video moment) → ask a question live → switch to Issues → follow parking meters from committee to the 44–6 vote → close with "built on auto-captions; with the PGX cluster this becomes our own Whisper transcripts with real speaker labels".

## If time runs short, cut in this order

1. Document collection (transcripts only).
2. Issue trails beyond 5 issues.
3. Live Q&A on the Issues page (keep it on the Alders page).
4. Suggested questions (keep the free box).

## Moving to Fuzzball / PGX later (do not build now)

- Each script becomes a Fuzzball job: `build_records` → `build_db` → `alder_*` / `issues`. The app becomes a Fuzzball service.
- Change only `config.json`: the model server addresses (vLLM on the PGX speaks the same OpenAI format) and model names. Copy `db/` and `data/` across, or rebuild them there.
- Swap Vimeo captions for Whisper transcripts in the same `[HH:MM:SS.mmm] text` format, and `build_db.py` works unchanged.
