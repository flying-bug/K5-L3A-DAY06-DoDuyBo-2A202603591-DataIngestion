"""Retrieval evaluation with full per-query traces.

A retrieved chunk is an *evidence hit* when its source and page match a gold (or documented
alternative) location AND it contains the whole evidence quote after normalization
(src.textmatch). Hit@1 looks at rank 1, Evidence Hit@3 at ranks 1-3.

Diagnostics kept next to the main metrics (never substituted for them):
- page_hit@3: a top-3 chunk is on a gold page, whether or not it holds the full quote
- evidence_containable: some chunk in the whole index holds the full quote (the ceiling of
  Evidence Hit@3 for that chunking; False means chunking split the evidence)
- filter_compliant: for questions with a filter, all top-3 chunks satisfy it

Chunk coherence and grounding are human labels and are NOT inferred here.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .textmatch import contains_evidence


def gold_locations(question: dict[str, Any]) -> list[dict[str, Any]]:
    golds = [{"source_id": question["gold_source_id"], "page": question["gold_page"],
              "evidence_quote": question["evidence_quote"]}]
    for alt in question.get("alternatives", []):
        golds.append({"source_id": alt.get("gold_source_id", question["gold_source_id"]),
                      "page": alt["gold_page"], "evidence_quote": alt["evidence_quote"]})
    return golds


def is_evidence_hit(hit: dict[str, Any], golds: list[dict[str, Any]]) -> bool:
    return any(hit["document_id"] == g["source_id"] and hit["page"] == g["page"]
               and contains_evidence(hit["text"], g["evidence_quote"]) for g in golds)


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    golds = gold_locations(question)
    gold_pages = {(g["source_id"], g["page"]) for g in golds}
    qfilter = question.get("filter") or None
    ranked = []
    for rank, hit in enumerate(hits[:3], start=1):
        filter_ok = None
        if qfilter:
            filter_ok = all((hit.get("metadata") or {}).get(k, hit.get(k)) == v for k, v in qfilter.items())
        ranked.append({
            "rank": rank,
            "chunk_id": hit["chunk_id"],
            "document_id": hit["document_id"],
            "source": hit["source"],
            "page": hit["page"],
            "part": hit.get("part"),
            "section": hit.get("section"),
            "function": hit.get("function"),
            "score": round(float(hit["score"]), 6),
            "evidence_hit": is_evidence_hit(hit, golds),
            "page_hit": (hit["document_id"], hit["page"]) in gold_pages,
            "filter_ok": filter_ok,
            "text": hit["text"],
        })
    return {
        "id": question["id"],
        "split": question["split"],
        "type": question.get("type"),
        "question": question["question"],
        "expected_answer": question["expected_answer"],
        "filter": qfilter,
        "gold": golds,
        "hits": ranked,
        "hit1": bool(ranked) and ranked[0]["evidence_hit"],
        "hit3": any(h["evidence_hit"] for h in ranked),
        "page_hit3": any(h["page_hit"] for h in ranked),
        "filter_compliant": all(h["filter_ok"] for h in ranked) if qfilter else None,
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts (not only rates) per strategy and split."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in traces:
        groups[(t.get("strategy", "?"), t["split"])].append(t)
    out: dict[str, Any] = {}
    for (strategy, split), items in sorted(groups.items()):
        n = len(items)
        filtered = [t for t in items if t["filter"]]
        row = {
            "n": n,
            "hit1": sum(t["hit1"] for t in items),
            "hit3": sum(t["hit3"] for t in items),
            "page_hit3": sum(t["page_hit3"] for t in items),
            "evidence_containable": sum(bool(t.get("evidence_containable")) for t in items),
            "filter_questions": len(filtered),
            "filter_compliant": sum(bool(t["filter_compliant"]) for t in filtered),
            "mean_latency_ms": round(sum(t.get("latency_ms", 0) for t in items) / n, 2) if n else None,
            "misses_hit3": [t["id"] for t in items if not t["hit3"]],
        }
        row["hit1_rate"] = round(row["hit1"] / n, 4) if n else None
        row["hit3_rate"] = round(row["hit3"] / n, 4) if n else None
        out.setdefault(strategy, {})[split] = row
    return out
