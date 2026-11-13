"""Read and normalize the NIST AI RMF PDF into traceable pages and paragraph blocks.

Each DocumentPage keeps:
- text: normalized page text (paragraph blocks joined by a blank line)
- metadata["blocks"]: [{"text", "start", "end", "section", "function"}] with character offsets into text
- metadata["counted"], ["excluded_reason"], ["part"]: copied from data/pages_manifest.csv
- metadata["removed_lines"]: running header/footer lines dropped during normalization

The `function` field (GOVERN | MAP | MEASURE | MANAGE | None) is a state machine over the
section headings "5.1 Govern" ... "5.4 Manage". It is carried across pages and reset by any
other numbered heading or appendix heading, so it is only set inside section 5.1–5.4.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

from pypdf import PdfReader

from .models import DocumentPage

# Running header / footer / table furniture that carries no content.
NOISE_RE = re.compile(
    r"^(NIST AI 100-1 AI RMF 1\.0|Page \d+|Continued on next page|Categories Subcategories)$"
)
# Section headings: "1.2.2 Risk Tolerance", "6. AI RMF Profiles", "Appendix B: ...", "Part 1: ..."
NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s+[A-Z][^.]{0,70}$")
OTHER_HEADING_RE = re.compile(r"^(Appendix [A-D]:.*|Part \d+:.*|Executive Summary|Prologue)$")
FUNCTION_HEADING_RE = re.compile(r"^5\.[1-4]\s+(Govern|Map|Measure|Manage)$")
# Lines that always open a new block (table rows, captions, bullets).
BLOCK_START_RE = re.compile(r"^((GOVERN|MAP|MEASURE|MANAGE) \d+(\.\d+)?:|Table \d+:|Figure \d+:|•)")
# No ':' here: "GOVERN 2:" must stay with the category text on the next lines.
SENTENCE_END_RE = re.compile(r"[.?!”\"')]$")


def normalize_text(text: str) -> str:
    """NFKC (ligatures such as 'ﬁ' -> 'fi'), unify spaces, strip each line; keep line breaks."""
    text = unicodedata.normalize("NFKC", text).replace(" ", " ").replace("\t", " ")
    lines = [re.sub(r" {2,}", " ", line).strip() for line in text.splitlines()]
    return "\n".join(lines)


def _join_lines(lines: list[str]) -> str:
    """Join wrapped lines; remove end-of-line hyphenation when the next line starts lowercase."""
    out = ""
    for line in lines:
        if not out:
            out = line
        elif out.endswith("-") and line[:1].islower():
            out = out[:-1] + line
        else:
            out += " " + line
    return out


def load_page_manifest(path: Path, document_id: str) -> dict[int, dict]:
    with open(path, encoding="utf-8") as f:
        return {int(r["page"]): r for r in csv.DictReader(f) if r["source_id"] == document_id}


def load_pdf(path: Path, document_id: str, source: str,
             page_manifest: dict[int, dict] | None = None) -> list[DocumentPage]:
    """Extract every physical page (1-based), normalize it and split it into paragraph blocks.

    Pages with no extractable text are kept with empty text and metadata["empty"] = True so the
    caller can log them. Excluded pages (cover, ToC, ...) are parsed too, because headings on
    them may change the section/function state, but they are marked counted = False.
    """
    reader = PdfReader(path)
    page_manifest = page_manifest or {}
    pages: list[DocumentPage] = []
    section: str | None = None
    function: str | None = None

    for number, pdf_page in enumerate(reader.pages, start=1):
        raw = normalize_text(pdf_page.extract_text() or "")
        lines = [line for line in raw.splitlines() if line]
        removed = [line for line in lines if NOISE_RE.match(line)]
        body = [line for line in lines if not NOISE_RE.match(line)]
        width = max((len(line) for line in body), default=0)

        blocks: list[dict] = []
        current: list[str] = []
        block_meta = {"section": section, "function": function}

        def flush() -> None:
            nonlocal current
            if current:
                blocks.append({"text": _join_lines(current), **block_meta})
            current = []

        for line in body:
            is_heading = bool(NUMBERED_HEADING_RE.match(line) or OTHER_HEADING_RE.match(line))
            if is_heading or BLOCK_START_RE.match(line):
                flush()
            if is_heading:
                match = FUNCTION_HEADING_RE.match(line)
                function = match.group(1).upper() if match else None
                section = line
            if not current:
                block_meta = {"section": section, "function": function}
            current.append(line)
            if is_heading:
                # keep the heading with the paragraph that follows it
                continue
            if SENTENCE_END_RE.search(line) and len(line) < 0.8 * width:
                flush()
        flush()

        # assign character offsets in the page text
        text_parts, offset = [], 0
        for block in blocks:
            block["start"] = offset
            block["end"] = offset + len(block["text"])
            text_parts.append(block["text"])
            offset = block["end"] + 2  # "\n\n"
        text = "\n\n".join(text_parts)

        info = page_manifest.get(number, {})
        pages.append(DocumentPage(
            document_id=document_id,
            source=source,
            page=number,
            text=text,
            metadata={
                "counted": info.get("counted", "1") == "1",
                "excluded_reason": info.get("excluded_reason") or None,
                "part": info.get("part") or None,
                "printed_page": number - 5 if 6 <= number <= 47 else None,
                "blocks": blocks,
                "removed_lines": removed,
                "empty": not text.strip(),
            },
        ))
    return pages
