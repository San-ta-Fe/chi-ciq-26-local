# Alder Audit

**Alders talk. Issues move. We keep the receipts.**

Streamlit app over a year of Chicago City Council meetings (Nov 2025 – Nov 2026): alder topics
with video links, issue trails from committee to vote, and Q&A with cited sources.

Requires Python 3.11+ and [Ollama](https://ollama.com). No DB server or Docker.

## Setup

**1. Clone or copy the project.** `db/` and `data/` are committed (the app needs them; about
115 MB). The meeting archive is not needed to run the app.

**2. Ollama models** (with Ollama running):

```bash
ollama pull nomic-embed-text
```

```bash
ollama pull qwen2.5:3b
```

`nomic-embed-text` is required: `db/` was embedded with it. `qwen2.5:3b` is only for the "local"
answer model.

**3. Python env**

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

On Windows, use `py -m venv .venv` and `.venv\Scripts\Activate.ps1`.

**4. Cloud key (optional).** Put your key in `.env` (committed with a placeholder):

```
CLOUD_API_KEY=your-key-here
```

Don't commit your real key. To keep git from picking up the edit:

```bash
git update-index --skip-worktree .env
```

Provider and model: `config.json` → `llm_profiles.cloud` (`base_url`, `model`). Any
OpenAI-compatible API works; drop the provider-specific `headers` if you switch.

**5. Run**

```bash
streamlit run app.py
```

Open http://localhost:8501. Add `--server.address 127.0.0.1` to keep it off the LAN.

## Project-specific notes

- **Model switch:** sidebar radio, `local` (Ollama) vs `cloud`. Applies on the next question, no
  restart; `config.json` is re-read on every call. Local is slow without a GPU (1–2 min per
  answer); cloud takes about 7 s.
- **Answer cache:** `data/qa_cache.json`, keyed by question + alder + profile + model. Ask the demo
  questions once beforehand and they return instantly.
- **Source sizes per profile:** `rag_source_chars`, `rag_transcripts` and `rag_documents` in each
  `llm_profiles` entry. Local is trimmed to fit a small model's context.
- **Read-only at runtime:** the app only reads `db/` and `data/`; all summaries are pre-computed.
- **Reload:** restart after code changes (Streamlit's file watcher can miss shared/network drives).
  Changes to `data/` show on page refresh.
- **Display:** designed for 1920×1080; use browser zoom on smaller screens.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Error mentioning port 11434 | Start Ollama |
| `model 'nomic-embed-text' not found` | `ollama pull nomic-embed-text` |
| `Set the environment variable CLOUD_API_KEY` | Add `.env` or switch to `local` |
| No Chicago theme | `.streamlit/` wasn't copied |
| Errors about `segmented_control`, `navigation` or theme options | `pip install -U "streamlit>=1.67"` |

## Layout

| Path | Role |
|---|---|
| `app.py` | Entry: page config, theme CSS, sidebar, navigation |
| `home.py`, `pages/1_Alders.py`, `pages/2_Issues.py` | Pages |
| `ui.py` | Shared UI: header, cards, question box |
| `rag.py` | Q&A: retrieve, prompt, cite, cache |
| `common.py` | All model calls (`chat`, `embed`); reads `config.json` |
| `vectorstore.py` | SQLite + numpy vector search |
| `db/*.db` | Caption and document chunks with embeddings |
| `data/records.db` | Meetings, agenda items, legislation, roll-call votes |
| `data/alders/`, `data/issues/` | Pre-computed facts, topics, trails, summaries |

## Rebuilding the data (optional)

Needs the City Clerk archive; set `archive_dir` in `config.json`. Run in order:

```bash
python build_records.py      # records -> data/records.db
python build_db.py           # embed captions + docs -> db/ (~1 h, resumable)
python pick_alders.py        # rank alders; --choose "Last, First M." ... sets featured_alders
python alder_facts.py        # votes, sponsorships, mentions (no AI)
python alder_insights.py     # topics + verified quotes (cloud)
python issues.py             # issue trails + summaries (cloud)
```

Background on each step: `PLAN.md`.

---

Transcripts are Vimeo auto-captions and may contain errors. Speakers in captions are inferred
(likely speaker); votes and sponsorships are official City Clerk records.
