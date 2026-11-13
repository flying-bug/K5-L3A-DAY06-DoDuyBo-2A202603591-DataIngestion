"""PostgreSQL + pgvector store: one table, rows keyed by (index_name, chunk_id).

- Exact (sequential) cosine search: no ANN index, the corpus is a few hundred chunks.
- Metadata filters are whitelisted columns and always passed as SQL parameters.
- Re-ingest is idempotent: upsert on the primary key, skip unchanged content (sha256),
  and delete chunks of the same document that no longer exist.
"""
from __future__ import annotations

import json
from typing import Any

import psycopg

from .models import Chunk

FILTER_COLUMNS = {"function": "function", "part": "part", "document_id": "document_id",
                  "page": "page", "section": "section"}


def _vec(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is empty: copy starter/.env.example to starter/.env")
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.database_url = database_url
        self.dimensions = dimensions

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, connect_timeout=5)

    def create_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    index_name      text NOT NULL,
                    chunk_id        text NOT NULL,
                    document_id     text NOT NULL,
                    source          text NOT NULL,
                    page            integer NOT NULL,
                    part            text,
                    section         text,
                    function        text,
                    text            text NOT NULL,
                    content_sha256  text NOT NULL,
                    metadata        jsonb NOT NULL,
                    embedding_model text NOT NULL,
                    embedding       vector({self.dimensions}) NOT NULL,
                    updated_at      timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (index_name, chunk_id)
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS chunks_filter_idx ON chunks (index_name, function)")
            row = conn.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'").fetchone()
            if row[0] != f"vector({self.dimensions})":
                raise RuntimeError(f"existing table has {row[0]}, model needs vector({self.dimensions}); "
                                   "drop the table or use another database")

    def versions(self) -> dict[str, str]:
        with self._connect() as conn:
            pg = conn.execute("SELECT current_setting('server_version')").fetchone()[0]
            ext = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0]
        return {"postgresql": pg, "pgvector": ext}

    def existing(self, index_name: str) -> dict[str, tuple[str, str]]:
        """chunk_id -> (content_sha256, embedding_model) currently stored for this index."""
        with self._connect() as conn:
            rows = conn.execute("SELECT chunk_id, content_sha256, embedding_model FROM chunks "
                                "WHERE index_name = %s", (index_name,)).fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]],
               embedding_model: str = "") -> int:
        """Insert or update the given chunks (stable IDs, so a re-run never duplicates rows)."""
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise ValueError(f"vector has {len(vector)} dims, expected {self.dimensions}")
        rows = [(
            strategy, c.chunk_id, c.document_id, c.source, c.page, c.metadata.get("part"),
            c.metadata.get("section"), c.metadata.get("function"), c.text,
            c.metadata["content_sha256"], json.dumps(c.metadata, ensure_ascii=False),
            embedding_model, _vec(v),
        ) for c, v in zip(chunks, vectors)]
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO chunks (index_name, chunk_id, document_id, source, page, part, section,
                                    function, text, content_sha256, metadata, embedding_model, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::vector)
                ON CONFLICT (index_name, chunk_id) DO UPDATE SET
                    document_id = EXCLUDED.document_id, source = EXCLUDED.source,
                    page = EXCLUDED.page, part = EXCLUDED.part, section = EXCLUDED.section,
                    function = EXCLUDED.function, text = EXCLUDED.text,
                    content_sha256 = EXCLUDED.content_sha256, metadata = EXCLUDED.metadata,
                    embedding_model = EXCLUDED.embedding_model, embedding = EXCLUDED.embedding,
                    updated_at = now()""", rows)
        return len(rows)

    def delete_obsolete(self, strategy: str, document_ids: list[str], keep_ids: list[str]) -> int:
        """Remove chunks of these documents whose IDs are not in the current chunk set."""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM chunks WHERE index_name = %s AND document_id = ANY(%s) "
                "AND NOT (chunk_id = ANY(%s))", (strategy, document_ids, keep_ids))
            return cur.rowcount

    def count(self, strategy: str) -> tuple[int, int]:
        """(rows, distinct chunk_ids) for an index; equal values mean no duplicates."""
        with self._connect() as conn:
            return conn.execute("SELECT count(*), count(DISTINCT chunk_id) FROM chunks "
                                "WHERE index_name = %s", (strategy,)).fetchone()

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if len(query_vector) != self.dimensions:
            raise ValueError(f"query has {len(query_vector)} dims, expected {self.dimensions}")
        where, params = ["index_name = %s"], [strategy]
        for key, value in (filters or {}).items():
            if key not in FILTER_COLUMNS:
                raise ValueError(f"filter on '{key}' is not allowed")
            where.append(f"{FILTER_COLUMNS[key]} = %s")
            params.append(value)
        qv = _vec(query_vector)
        sql = (f"SELECT chunk_id, document_id, source, page, part, section, function, text, metadata, "
               f"1 - (embedding <=> %s::vector) AS score FROM chunks WHERE {' AND '.join(where)} "
               f"ORDER BY embedding <=> %s::vector, chunk_id LIMIT %s")
        with self._connect() as conn:
            rows = conn.execute(sql, [qv, *params, qv, top_k]).fetchall()
        keys = ["chunk_id", "document_id", "source", "page", "part", "section", "function",
                "text", "metadata", "score"]
        return [dict(zip(keys, row)) for row in rows]
