"""Verify benchmark/questions.jsonl against the source PDFs BEFORE running any retrieval.

Checks: required fields, split sizes (>=15 dev, >=5 test), filter questions (>=3, >=1 in test),
unique ids, and that every evidence quote (and alternative) is found on its gold page.
Also lists any other pages where the same quote appears, so ambiguous evidence is visible.

Run from the repo root:  python starter/scripts/verify_benchmark.py
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "starter"))
from src.textmatch import normalize_for_match  # noqa: E402

REQUIRED = ["id", "split", "question", "expected_answer", "gold_source_id", "gold_page", "evidence_quote", "filter"]


def load_pages() -> dict[str, dict[int, str]]:
    pages: dict[str, dict[int, str]] = {}
    with open(ROOT / "data" / "manifest.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            local = row["source_path_or_url"].split("local: ")[-1].rstrip(")")
            reader = PdfReader(ROOT / local)
            pages[row["source_id"]] = {
                i: normalize_for_match(p.extract_text() or "") for i, p in enumerate(reader.pages, 1)
            }
    return pages


def main() -> int:
    questions = [json.loads(line) for line in open(ROOT / "benchmark" / "questions.jsonl", encoding="utf-8") if line.strip()]
    pages = load_pages()
    errors = []

    for q in questions:
        missing = [k for k in REQUIRED if k not in q]
        if missing:
            errors.append(f"{q.get('id')}: missing fields {missing}")
            continue
        golds = [(q["gold_page"], q["evidence_quote"])] + [(a["gold_page"], a["evidence_quote"]) for a in q.get("alternatives", [])]
        doc = pages.get(q["gold_source_id"])
        if doc is None:
            errors.append(f"{q['id']}: unknown source {q['gold_source_id']}")
            continue
        for page, quote in golds:
            needle = normalize_for_match(quote)
            found_on = [p for p, text in doc.items() if needle in text]
            ok = page in found_on
            status = "OK  " if ok else "FAIL"
            others = [p for p in found_on if p != page]
            print(f"{status} {q['id']:>4} {q['split']:<4} p{page:<3} filter={q['filter']} "
                  f"len={len(needle)}{'  also on ' + str(others) if others else ''}")
            if not ok:
                errors.append(f"{q['id']}: evidence not found on page {page} (found on {found_on})")

    ids = Counter(q["id"] for q in questions)
    errors += [f"duplicate id {i}" for i, n in ids.items() if n > 1]
    splits = Counter(q["split"] for q in questions)
    filtered = [q for q in questions if q.get("filter")]
    filtered_test = [q for q in filtered if q["split"] == "test"]
    print(f"\n{len(questions)} questions | dev={splits['dev']} test={splits['test']} | "
          f"filter questions={len(filtered)} (test={len(filtered_test)})")
    if len(questions) < 20:
        errors.append("need >= 20 questions")
    if splits["dev"] < 15 or splits["test"] < 5:
        errors.append("need >= 15 dev and >= 5 test")
    if len(filtered) < 3 or not filtered_test:
        errors.append("need >= 3 filter questions with >= 1 in test")

    if errors:
        print("\nERRORS:\n  " + "\n  ".join(errors))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
