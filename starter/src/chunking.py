"""Fixed-size and structure-aware (paragraph) chunking. Chunks never cross a page boundary,
so `page` is always exact; each chunk inherits source/page/part and gets section/function from
the paragraph blocks it overlaps."""
from __future__ import annotations

import hashlib
import re
from collections import Counter

from .models import Chunk, DocumentPage

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+(?=[A-Z“\"(])")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _majority(page: DocumentPage, start: int, end: int, key: str):
    """Value of `key` from the blocks covering [start, end), weighted by overlap length."""
    weights: Counter = Counter()
    for block in page.metadata.get("blocks", []):
        overlap = min(end, block["end"]) - max(start, block["start"])
        if overlap > 0:
            weights[block[key]] += overlap
    return weights.most_common(1)[0][0] if weights else None


def _make_chunk(page: DocumentPage, kind: str, index: int, text: str, start: int, end: int,
                extra: dict | None = None) -> Chunk:
    meta = {
        "part": page.metadata.get("part"),
        "printed_page": page.metadata.get("printed_page"),
        "section": _majority(page, start, end, "section"),
        "function": _majority(page, start, end, "function"),
        "char_start": start,
        "char_end": end,
        "chunker": kind,
        "content_sha256": _sha(text),
    }
    meta.update(extra or {})
    return Chunk(
        chunk_id=f"{page.document_id}:p{page.page:03d}:{kind}:{index:02d}",
        document_id=page.document_id,
        source=page.source,
        page=page.page,
        text=text,
        metadata=meta,
    )


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Character windows of `size` with `overlap`, ignoring sentence/paragraph boundaries."""
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("need size > 0 and 0 <= overlap < size")
    text, chunks, start = page.text, [], 0
    step = size - overlap
    while start < len(text):
        end = min(start + size, len(text))
        piece = text[start:end].strip()
        if piece:
            chunks.append(_make_chunk(page, f"fixed{size}o{overlap}", len(chunks), piece, start, end))
        if end == len(text):
            break
        start += step
    return chunks


def _split_oversized(text: str, max_size: int) -> list[str]:
    """Split one long paragraph at sentence ends; hard-split sentences longer than max_size."""
    parts, current = [], ""
    for sentence in SENTENCE_SPLIT_RE.split(text):
        while len(sentence) > max_size:
            parts.append(sentence[:max_size])
            sentence = sentence[max_size:]
        if current and len(current) + 1 + len(sentence) > max_size:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Greedily group whole paragraphs up to max_size characters.

    A new chunk starts at every section heading and whenever the function value changes, so a
    chunk never mixes GOVERN and MAP text. Paragraphs longer than max_size are split at sentence
    boundaries (recorded as metadata["split_paragraph"] = True).
    """
    kind = f"para{max_size}"
    chunks: list[Chunk] = []
    group: list[dict] = []

    def emit(blocks: list[dict], split: bool = False) -> None:
        start, end = blocks[0]["start"], blocks[-1]["end"]
        text = "\n\n".join(b["text"] for b in blocks)
        chunks.append(_make_chunk(page, kind, len(chunks), text, start, end,
                                  {"split_paragraph": split, "n_paragraphs": len(blocks)}))

    for block in page.metadata.get("blocks", []):
        if len(block["text"]) > max_size:
            if group:
                emit(group)
                group = []
            offset = block["start"]
            for piece in _split_oversized(block["text"], max_size):
                pos = block["text"].find(piece[:40], offset - block["start"])
                start = block["start"] + max(pos, 0)
                emit([{**block, "text": piece, "start": start, "end": start + len(piece)}], split=True)
                offset = start + len(piece)
            continue
        size_if_added = sum(len(b["text"]) + 2 for b in group) + len(block["text"])
        new_section = block["section"] != (group[-1]["section"] if group else block["section"])
        new_function = group and block["function"] != group[-1]["function"]
        if group and (size_if_added > max_size or new_section or new_function):
            emit(group)
            group = []
        group.append(block)
    if group:
        emit(group)
    return chunks
