"""Shared helpers: config, model clients, vector store.

Every model call goes through here. Switching local <-> cloud is a config
change only (config.json is re-read on every call), so nothing is redeployed.
On the PGX later, only base_url / model in config.json change.
"""
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("KYA_CONFIG", HERE / "config.json"))


def _load_dotenv():
    """Read KEY=value lines from .env next to this file (keys already set win)."""
    f = HERE / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def cfg() -> dict:
    """Read config.json fresh each time, so edits apply without restarting."""
    return json.loads(CONFIG_PATH.read_text())


def path(key: str) -> Path:
    p = Path(os.path.expanduser(cfg()[key]))
    if not p.is_absolute():  # relative paths mean "inside this project folder"
        p = HERE / p
    if key != "archive_dir":
        p.mkdir(parents=True, exist_ok=True)
    return p


def _client(profile: dict):
    from openai import OpenAI  # imported lazily so chunk-only runs need no deps

    key_env = profile.get("api_key_env")
    api_key = os.environ.get(key_env, "") if key_env else "ollama"
    if key_env and not api_key:
        raise RuntimeError(f"Set the environment variable {key_env} for this model profile.")
    # Optional extra HTTP headers per profile, e.g. OpenCode Go's x-opencode-session.
    return OpenAI(base_url=profile["base_url"], api_key=api_key,
                  default_headers=profile.get("headers") or None)


# ---------- language model ----------

def chat(messages, profile_name=None, json_mode=False, temperature=0.2) -> str:
    """Send a chat request to the profile named in config (or the one given)."""
    c = cfg()
    name = profile_name or c["chat_profile"]
    profile = c["llm_profiles"][name]

    if profile.get("api") == "responses":  # e.g. GPT/Luna models on OpenCode Go
        kwargs = {"text": {"format": {"type": "json_object"}}} if json_mode else {}
        resp = _client(profile).responses.create(model=profile["model"], input=messages, **kwargs)
        return resp.output_text

    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = _client(profile).chat.completions.create(
        model=profile["model"], messages=messages, temperature=temperature, **kwargs
    )
    return resp.choices[0].message.content


# ---------- embeddings (always the same model for build and query) ----------

def embed(texts, kind="doc"):
    e = cfg()["embedding"]
    prefix = e["doc_prefix"] if kind == "doc" else e["query_prefix"]
    resp = _client(e).embeddings.create(model=e["model"], input=[prefix + t for t in texts])
    return [d.embedding for d in resp.data]


# ---------- vector store ----------

def collection(name: str):
    """'transcripts' or 'documents'. One SQLite file each in db_dir; copy to move machines."""
    from vectorstore import get_collection

    return get_collection(path("db_dir"), name)


def search(query: str, coll: str, k=8, where=None, where_document=None):
    """Return a list of {id, text, meta, score} for the best matches."""
    res = collection(coll).query(
        query_embeddings=embed([query], kind="query"),
        n_results=k,
        where=where,
        where_document=where_document,
    )
    out = []
    for i in range(len(res["ids"][0])):
        out.append({
            "id": res["ids"][0][i],
            "text": res["documents"][0][i],
            "meta": res["metadatas"][0][i],
            "score": 1 - res["distances"][0][i],
        })
    return out


def vimeo_link(video_id: str, seconds: float) -> str:
    return f"https://vimeo.com/{video_id}#t={int(seconds)}s"


def hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
