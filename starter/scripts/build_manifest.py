"""Build data/manifest.csv (one row per document) and data/pages_manifest.csv (one row per page).

Run from the repo root:  python starter/scripts/build_manifest.py
"""
import csv
import hashlib
import re
import unicodedata
from datetime import date
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

DOCUMENTS = [
    {
        "source_id": "nist-ai-100-1",
        "title": "Artificial Intelligence Risk Management Framework (AI RMF 1.0)",
        "path": DATA / "raw" / "NIST.AI.100-1.pdf",
        "url": "https://doi.org/10.6028/NIST.AI.100-1",
        "license": (
            "US Government work by NIST employees: not subject to copyright protection in the US "
            "(https://www.nist.gov/oism/copyrights). Publication states it is available free of charge."
        ),
        "version": "AI RMF 1.0, NIST AI 100-1, January 2023",
        # Pages excluded from the content count, with the reason (decided by reading each page).
        "excluded": {
            1: "cover",
            2: "title page",
            3: "disclaimer, update schedule, front matter",
            4: "table of contents",
            5: "table of contents / list of figures",
            16: "figure only (Fig. 3 caption, 409 chars)",
            48: "back cover",
        },
    },
]

PART_RE = [
    (re.compile(r"^Executive Summary$", re.M), "front"),
    (re.compile(r"^Part 1: Foundational Information$", re.M), "part1"),
    (re.compile(r"^Part 2: Core and Profiles$", re.M), "part2"),
    (re.compile(r"^Appendix [A-D]:", re.M), "appendix"),
]


def page_text(raw: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", raw)).strip()


def main() -> None:
    doc_rows, page_rows = [], []
    for doc in DOCUMENTS:
        reader = PdfReader(doc["path"])
        sha256 = hashlib.sha256(doc["path"].read_bytes()).hexdigest()
        part = None
        counted, chars_counted = [], 0
        for number, page in enumerate(reader.pages, start=1):
            raw = unicodedata.normalize("NFC", page.extract_text() or "")
            if number not in doc["excluded"]:
                for pattern, name in PART_RE:
                    if pattern.search(raw):
                        part = name
            text = page_text(raw)
            reason = doc["excluded"].get(number, "")
            if not reason:
                counted.append(number)
                chars_counted += len(text)
            page_rows.append({
                "source_id": doc["source_id"], "page": number, "counted": int(not reason),
                "excluded_reason": reason, "part": part if not reason else "", "chars": len(text),
            })
        doc_rows.append({
            "source_id": doc["source_id"],
            "title": doc["title"],
            "source_path_or_url": f'{doc["url"]} (local: {doc["path"].relative_to(ROOT).as_posix()})',
            "license_or_permission": doc["license"],
            "accessed_at": date.today().isoformat(),
            "version": doc["version"],
            "sha256": sha256,
            "physical_pages": len(reader.pages),
            "counted_pages": len(counted),
            "counted_page_ids": ";".join(map(str, counted)),
            "excluded_pages": "; ".join(f"{p}: {r}" for p, r in doc["excluded"].items()),
            "chars_counted": chars_counted,
            "page_numbering": "PDF physical page index (1-based); printed page = PDF page - 5 for pages 6-47",
        })

    with open(DATA / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(doc_rows[0]))
        writer.writeheader()
        writer.writerows(doc_rows)
    with open(DATA / "pages_manifest.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(page_rows[0]))
        writer.writeheader()
        writer.writerows(page_rows)
    for row in doc_rows:
        print(f'{row["source_id"]}: {row["counted_pages"]}/{row["physical_pages"]} pages counted, '
              f'{row["chars_counted"]} chars')


if __name__ == "__main__":
    main()
