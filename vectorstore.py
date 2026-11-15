"""A tiny vector store: SQLite for text + metadata + vectors, numpy for search.

Replaces chromadb (which needs onnxruntime, not installable on every Mac).
Same calls the rest of the code uses: add, get, count, query.
One .db file per collection in db_dir; copy the folder to move machines.
~25k chunks x 768 numbers = ~80 MB in memory; a search takes milliseconds.
"""
import json
import sqlite3
from pathlib import Path

import numpy as np


class Collection:
    def __init__(self, db_path: Path):
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS chunks("
                        "id TEXT PRIMARY KEY, text TEXT, meta TEXT, vec BLOB)")
        self.db.commit()
        self._cache = None  # (count, ids, texts, metas, matrix)

    def count(self):
        return self.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    def get(self, include=None):
        return {"ids": [r[0] for r in self.db.execute("SELECT id FROM chunks")]}

    def add(self, ids, embeddings, documents, metadatas):
        rows = [(i, d, json.dumps(m), np.asarray(e, dtype=np.float32).tobytes())
                for i, e, d, m in zip(ids, embeddings, documents, metadatas)]
        self.db.executemany("INSERT OR REPLACE INTO chunks VALUES (?,?,?,?)", rows)
        self.db.commit()

    def _load(self):
        n = self.count()
        if self._cache is None or self._cache[0] != n:
            ids, texts, metas, vecs = [], [], [], []
            for i, t, m, v in self.db.execute("SELECT id, text, meta, vec FROM chunks"):
                ids.append(i); texts.append(t); metas.append(json.loads(m))
                vecs.append(np.frombuffer(v, dtype=np.float32))
            mat = np.vstack(vecs) if vecs else np.zeros((0, 1), np.float32)
            mat = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
            self._cache = (n, ids, texts, metas, mat)
        return self._cache

    def query(self, query_embeddings, n_results=8, where=None, where_document=None):
        """where: {"field": value} exact match. where_document: {"$contains": "text"}
        (case-insensitive)."""
        _, ids, texts, metas, mat = self._load()
        q = np.asarray(query_embeddings[0], dtype=np.float32)
        q = q / (np.linalg.norm(q) + 1e-9)
        scores = mat @ q if len(ids) else np.zeros(0)

        mask = np.ones(len(ids), dtype=bool)
        if where:
            for k, v in where.items():
                mask &= np.array([m.get(k) == v for m in metas], dtype=bool)
        if where_document and "$contains" in where_document:
            needle = where_document["$contains"].lower()
            mask &= np.array([needle in t.lower() for t in texts], dtype=bool)

        idx = np.where(mask)[0]
        top = idx[np.argsort(-scores[idx])[:n_results]]
        return {
            "ids": [[ids[i] for i in top]],
            "documents": [[texts[i] for i in top]],
            "metadatas": [[metas[i] for i in top]],
            "distances": [[float(1 - scores[i]) for i in top]],
        }


_open = {}


def get_collection(db_dir: Path, name: str) -> Collection:
    key = (str(db_dir), name)
    if key not in _open:
        _open[key] = Collection(Path(db_dir) / f"{name}.db")
    return _open[key]
