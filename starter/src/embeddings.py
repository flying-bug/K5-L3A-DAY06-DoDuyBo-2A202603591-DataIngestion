"""Real embedding provider: a local Sentence Transformers model (default: EmbeddingGemma-300m).

Documents and queries use the model's own retrieval prompts
("title: none | text: " / "task: search result | query: ") via encode_document / encode_query.
Vectors are L2-normalized, so cosine distance in pgvector is the matching metric.
There is no fallback: if the model cannot be loaded, the error propagates.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class MyEmbedder:
    def __init__(self, model_name: str, device: str = "cpu", batch_size: int = 16) -> None:
        from sentence_transformers import SentenceTransformer  # heavy import, keep lazy

        self.model_name = model_name
        self.batch_size = batch_size
        self.model = SentenceTransformer(model_name, device=device)
        get_dims = getattr(self.model, "get_embedding_dimension", None) or \
            self.model.get_sentence_embedding_dimension
        dims = get_dims()
        if not dims:
            raise RuntimeError(f"cannot read embedding dimension of {model_name}")
        self.dimensions = int(dims)
        self.max_seq_length = int(self.model.max_seq_length)

    def info(self) -> dict:
        """Provenance for the run log: model id, dims, library versions, weights hash prefix."""
        import sentence_transformers
        import torch
        import transformers

        weights = Path(self.model_name) / "model.safetensors"
        digest = None
        if weights.exists():
            h = hashlib.sha256()
            with open(weights, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
            digest = h.hexdigest()
        return {
            "provider": "local sentence-transformers (CPU)",
            "model": Path(self.model_name).name if Path(self.model_name).exists() else self.model_name,
            "model_path": self.model_name,
            "weights_sha256": digest,
            "dimensions": self.dimensions,
            "max_seq_length": self.max_seq_length,
            "document_prompt": self.model.prompts.get("document"),
            "query_prompt": self.model.prompts.get("query"),
            "normalized": True,
            "sentence_transformers": sentence_transformers.__version__,
            "transformers": transformers.__version__,
            "torch": torch.__version__,
        }

    def count_tokens(self, text: str) -> int:
        return len(self.model.tokenizer(text)["input_ids"])

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self.model.encode_document(texts, batch_size=self.batch_size,
                                             normalize_embeddings=True, convert_to_numpy=True)
        return vectors.tolist()

    def embed_query(self, question: str) -> list[float]:
        vector = self.model.encode_query([question], normalize_embeddings=True, convert_to_numpy=True)
        return vector[0].tolist()
