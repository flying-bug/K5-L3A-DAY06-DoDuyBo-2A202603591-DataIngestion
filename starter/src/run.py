"""Day 06 pipeline: ingest -> chunk (A/B) -> embed -> pgvector -> retrieve (A/B/C) -> evaluate.

Run from starter/:
    python -m src.run --split dev     # ingest (idempotent), evaluate dev, apply selection rule
    python -m src.run --split test    # only after dev: evaluate test once, write audit sheets
    python -m src.run --ingest-only   # ingest and re-check idempotency, no queries

Outputs go to starter/results/ (see starter/README.md).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pypdf import PdfReader

from .chunking import by_paragraph, fixed_size
from .embeddings import MyEmbedder
from .evaluation import evaluate_query, summarize
from .ingestion import load_page_manifest, load_pdf
from .store import PgVectorStore
from .textmatch import contains_evidence, normalize_for_match

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
RESULTS = STARTER / "results"

# Same corpus, model, questions and top_k for every strategy.
# A -> B changes only the chunking method (same ~800 character budget).
# B -> C changes only the metadata filter (same index, applied only when the question has one).
INDEXES = {
    "fixed800o100": {"chunker": "fixed_size", "size": 800, "overlap": 100},
    "para800": {"chunker": "by_paragraph", "max_size": 800},
}
STRATEGIES = {
    "A": {"index": "fixed800o100", "use_filter": False,
          "description": "fixed 800 chars, overlap 100, per page; no filter"},
    "B": {"index": "para800", "use_filter": False,
          "description": "paragraph groups <= 800 chars, split at headings/function changes; no filter"},
    "C": {"index": "para800", "use_filter": True,
          "description": "same chunks as B; SQL filter on `function` when the question provides one"},
}
TOP_K = 3
# Fixed before any retrieval run (also written in benchmark/README.md).
SELECTION_RULE = ["higher dev Evidence Hit@3", "higher dev Hit@1", "fewer chunks"]
# Coherence audit positions, fixed before scoring: every 4th counted page, character midpoint.
COHERENCE_PAGE_STEP = 4
COHERENCE_POSITIONS = 10


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_documents() -> list[dict]:
    docs = []
    with open(ROOT / "data" / "manifest.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            local = row["source_path_or_url"].split("local: ")[-1].rstrip(")")
            path = ROOT / local
            if not path.exists():
                raise FileNotFoundError(f"{path} missing; see data/manifest.csv for the source URL")
            actual = sha256_file(path)
            if actual != row["sha256"]:
                raise RuntimeError(f"{path.name}: sha256 {actual} != manifest {row['sha256']}")
            docs.append({**row, "path": path})
    return docs


def build_chunks(pages, index_name: str):
    cfg = INDEXES[index_name]
    chunks = []
    for page in pages:
        if cfg["chunker"] == "fixed_size":
            chunks += fixed_size(page, cfg["size"], cfg["overlap"])
        else:
            chunks += by_paragraph(page, cfg["max_size"])
    return chunks


def length_stats(values: list[int]) -> dict:
    return {"min": min(values), "median": statistics.median(values),
            "mean": round(statistics.mean(values), 1), "max": max(values), "total": sum(values)}


def ingest(docs, embedder: MyEmbedder, store: PgVectorStore) -> tuple[dict, dict, list, dict]:
    """Parse, chunk, embed only new/changed chunks, upsert, prune obsolete. Returns stats."""
    t0 = time.perf_counter()
    pages, ingest_log = [], {"documents": []}
    for doc in docs:
        page_manifest = load_page_manifest(ROOT / "data" / "pages_manifest.csv", doc["source_id"])
        doc_pages = load_pdf(doc["path"], doc["source_id"], doc["title"], page_manifest)
        counted = [p for p in doc_pages if p.metadata["counted"]]
        ingest_log["documents"].append({
            "source_id": doc["source_id"],
            "physical_pages": len(doc_pages),
            "counted_pages": len(counted),
            "empty_pages": [p.page for p in doc_pages if p.metadata["empty"]],
            "excluded_pages": {p.page: p.metadata["excluded_reason"] for p in doc_pages
                               if not p.metadata["counted"]},
            "removed_header_footer_lines": sum(len(p.metadata["removed_lines"]) for p in doc_pages),
            "counted_chars_after_normalization": sum(len(p.text) for p in counted),
            "function_pages": sorted({p.page for p in counted
                                      for b in p.metadata["blocks"] if b["function"]}),
        })
        pages += counted
    if len(pages) < 30:
        raise RuntimeError(f"only {len(pages)} counted pages; the lab needs >= 30")
    parse_seconds = time.perf_counter() - t0
    log(f"parsed {len(pages)} counted pages in {parse_seconds:.2f}s")

    store.create_schema()
    stats, all_chunks = {}, {}
    doc_ids = [d["source_id"] for d in docs]
    for index_name in INDEXES:
        t = time.perf_counter()
        chunks = build_chunks(pages, index_name)
        chunk_seconds = time.perf_counter() - t
        existing = store.existing(index_name)
        todo = [c for c in chunks
                if existing.get(c.chunk_id) != (c.metadata["content_sha256"], embedder.model_name)]
        t = time.perf_counter()
        vectors = embedder.embed_documents([c.text for c in todo])
        embed_seconds = time.perf_counter() - t
        t = time.perf_counter()
        store.upsert(index_name, todo, vectors, embedder.model_name)
        deleted = store.delete_obsolete(index_name, doc_ids, [c.chunk_id for c in chunks])
        upsert_seconds = time.perf_counter() - t
        rows, distinct = store.count(index_name)
        tokens = [embedder.count_tokens(c.text) for c in chunks]
        stats[index_name] = {
            "config": INDEXES[index_name],
            "chunks": len(chunks),
            "chars": length_stats([len(c.text) for c in chunks]),
            "tokens": length_stats(tokens),
            "truncated_chunks": sum(n > embedder.max_seq_length for n in tokens),
            "chunks_with_function": sum(bool(c.metadata["function"]) for c in chunks),
            "split_paragraph_chunks": sum(bool(c.metadata.get("split_paragraph")) for c in chunks),
            "embedded_now": len(todo),
            "unchanged_skipped": len(chunks) - len(todo),
            "deleted_obsolete": deleted,
            "rows_in_store": rows,
            "distinct_ids_in_store": distinct,
            "duplicates": rows - distinct,
            "store_matches_chunks": rows == len(chunks),
            "seconds": {"chunking": round(chunk_seconds, 3), "embedding": round(embed_seconds, 2),
                        "upsert_and_prune": round(upsert_seconds, 2)},
        }
        all_chunks[index_name] = chunks
        log(f"{index_name}: {len(chunks)} chunks, embedded {len(todo)}, skipped "
            f"{len(chunks) - len(todo)}, deleted {deleted}, rows {rows}/{distinct} distinct, "
            f"embed {embed_seconds:.1f}s")
    ingest_log["parse_seconds"] = round(parse_seconds, 2)
    return stats, ingest_log, pages, all_chunks


def load_questions(split: str) -> list[dict]:
    qs = [json.loads(line) for line in open(ROOT / "benchmark" / "questions.jsonl", encoding="utf-8")
          if line.strip()]
    return [q for q in qs if split == "all" or q["split"] == split]


def run_queries(questions, embedder, store, all_chunks) -> list[dict]:
    traces = []
    for q in questions:
        t = time.perf_counter()
        qvec = embedder.embed_query(q["question"])
        embed_ms = (time.perf_counter() - t) * 1000
        for name, cfg in STRATEGIES.items():
            filters = q["filter"] if (cfg["use_filter"] and q.get("filter")) else None
            t = time.perf_counter()
            hits = store.search(cfg["index"], qvec, TOP_K, filters)
            search_ms = (time.perf_counter() - t) * 1000
            trace = evaluate_query(q, hits)
            golds = trace["gold"]
            trace.update({
                "strategy": name,
                "index": cfg["index"],
                "applied_filter": filters,
                "latency_ms": round(embed_ms + search_ms, 2),
                "search_ms": round(search_ms, 2),
                "evidence_containable": any(
                    c.page == g["page"] and c.document_id == g["source_id"]
                    and contains_evidence(c.text, g["evidence_quote"])
                    for g in golds for c in all_chunks[cfg["index"]]),
            })
            traces.append(trace)
    return traces


def select_strategy(summary: dict, stats: dict) -> dict:
    def key(name):
        dev = summary[name]["dev"]
        return (-dev["hit3"], -dev["hit1"], stats[STRATEGIES[name]["index"]]["chunks"])
    ranking = sorted(STRATEGIES, key=key)
    best = [s for s in ranking if key(s) == key(ranking[0])]
    note = None
    if len(best) > 1:
        note = (f"{' and '.join(best)} tie on every pre-registered criterion (they share the same index); "
                "the rule does not separate them, so all tied strategies are carried to test.")
    return {"selected": best, "tie": len(best) > 1, "note": note, "ranking": ranking, "rule": SELECTION_RULE,
            "dev": {s: {k: summary[s]["dev"][k] for k in ("n", "hit1", "hit3")} for s in STRATEGIES},
            "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def write_audit_sheets(pages, all_chunks, traces, docs) -> None:
    """Blank manual-label sheets (coherence, grounding, metadata). Labels are filled by a human."""
    audit = RESULTS / "audit"
    audit.mkdir(parents=True, exist_ok=True)

    # 1. Coherence: same 10 source positions for every strategy (C shares B's chunks).
    chosen = pages[::COHERENCE_PAGE_STEP][:COHERENCE_POSITIONS]
    with open(audit / "coherence.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["position_id", "page", "char_offset", "context_at_position", "strategy",
                    "chunk_id", "chunk_text", "score_0_2", "reason"])
        for i, page in enumerate(chosen, 1):
            offset = len(page.text) // 2
            context = page.text[max(0, offset - 60): offset + 60].replace("\n", " ")
            for name in ("A", "B"):
                index = STRATEGIES[name]["index"]
                covering = [c for c in all_chunks[index] if c.page == page.page
                            and c.metadata["char_start"] <= offset < c.metadata["char_end"]]
                for c in covering[:1]:
                    w.writerow([f"pos{i:02d}", page.page, offset, context, name + (" (=C)" if name == "B" else ""),
                                c.chunk_id, c.text, "", ""])

    # 2. Grounding: test questions x strategy, top-3 together.
    test = [t for t in traces if t["split"] == "test"]
    with open(audit / "grounding.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "strategy", "question", "expected_answer", "filter", "top3_chunk_ids",
                    "top3_pages", "top3_text", "auto_evidence_hit3", "label_0_2", "reason"])
        for t in test:
            w.writerow([t["id"], t["strategy"], t["question"], t["expected_answer"],
                        json.dumps(t["filter"]) if t["filter"] else "",
                        " | ".join(h["chunk_id"] for h in t["hits"]),
                        " | ".join(str(h["page"]) for h in t["hits"]),
                        "\n---\n".join(f"[{h['rank']}] p{h['page']}: {h['text']}" for h in t["hits"]),
                        t["hit3"], "", ""])

    # 3. Metadata: every test top-3 record, with automatic pre-checks against the raw PDF.
    raw = {}
    for doc in docs:
        reader = PdfReader(doc["path"])
        raw[doc["source_id"]] = {i: normalize_for_match(p.extract_text() or "")
                                 for i, p in enumerate(reader.pages, 1)}
    page_by_id = {p.page: p for p in pages}
    with open(audit / "metadata.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "strategy", "rank", "chunk_id", "source", "page", "part", "section",
                    "function", "filter", "filter_ok", "auto_text_on_page", "auto_function_matches_source",
                    "manual_correct_and_complete", "note"])
        for t in test:
            for h in t["hits"]:
                on_page = normalize_for_match(h["text"]) in raw[h["document_id"]].get(h["page"], "")
                page = page_by_id.get(h["page"])
                funcs = {b["function"] for b in page.metadata["blocks"]} if page else set()
                w.writerow([t["id"], t["strategy"], h["rank"], h["chunk_id"], h["source"], h["page"],
                            h["part"], h["section"], h["function"],
                            json.dumps(t["filter"]) if t["filter"] else "",
                            "" if h["filter_ok"] is None else h["filter_ok"],
                            on_page, h["function"] in funcs, "", ""])
    log(f"audit sheets written to {audit}")


def write_summary_md(split: str, summary: dict, stats: dict, selection: dict | None) -> None:
    lines = [f"# Results: {split}", "",
             "| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | page_hit@3 | containable | "
             "filter compliant | chunks | misses@3 |", "|---|---|---|---|---|---|---|---|---|"]
    for name in STRATEGIES:
        for sp, r in summary.get(name, {}).items():
            fc = f"{r['filter_compliant']}/{r['filter_questions']}" if r["filter_questions"] else "N/A"
            lines.append(f"| {name} | {sp} | {r['hit1']}/{r['n']} | {r['hit3']}/{r['n']} | "
                         f"{r['page_hit3']}/{r['n']} | {r['evidence_containable']}/{r['n']} | {fc} | "
                         f"{stats[STRATEGIES[name]['index']]['chunks']} | {', '.join(r['misses_hit3']) or '-'} |")
    if selection:
        lines += ["", f"Selected on dev: **{' / '.join(selection['selected'])}** "
                  f"(rule: {' > '.join(selection['rule'])})"]
        if selection.get("note"):
            lines.append(f"Note: {selection['note']}")
    (RESULTS / f"summary_{split}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--ingest-only", action="store_true")
    args = parser.parse_args()

    load_dotenv(STARTER / ".env")
    model = os.getenv("EMBEDDING_MODEL") or str(ROOT.parent / "models" / "embeddinggemma-300m")
    RESULTS.mkdir(exist_ok=True)
    started = datetime.now(timezone.utc)

    if args.split == "test" and not args.ingest_only and not (RESULTS / "selection.json").exists():
        sys.exit("Run --split dev first: the strategy must be selected on dev before test is run.")

    docs = load_documents()
    log(f"loading embedding model {model}")
    embedder = MyEmbedder(model)
    store = PgVectorStore(os.getenv("DATABASE_URL", ""), embedder.dimensions)
    stats, ingest_log, pages, all_chunks = ingest(docs, embedder, store)
    run_info = {
        "started_at": started.isoformat(timespec="seconds"),
        "command": " ".join(["python -m src.run", *sys.argv[1:]]),
        "split": None if args.ingest_only else args.split,
        "embedding": embedder.info(),
        "vector_store": {**store.versions(), "metric": "cosine (<=>)", "search": "exact, no ANN index",
                         "table": "chunks"},
        "strategies": STRATEGIES, "indexes": INDEXES, "top_k": TOP_K,
        "machine": {"platform": platform.platform(), "processor": platform.processor(),
                    "cpu_count": os.cpu_count(), "python": platform.python_version()},
        "cost_usd": 0.0,
        "index_stats": stats,
    }
    (RESULTS / "ingest_log.json").write_text(json.dumps(ingest_log, indent=2, ensure_ascii=False), encoding="utf-8")
    runs_dir = RESULTS / "runs"
    runs_dir.mkdir(exist_ok=True)
    stamp = started.strftime("%Y%m%d-%H%M%S")
    if args.ingest_only:
        (runs_dir / f"ingest_{stamp}.json").write_text(json.dumps(run_info, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"ingest-only run finished -> results/runs/ingest_{stamp}.json")
        return

    questions = load_questions(args.split)
    log(f"running {len(questions)} {args.split} questions x {len(STRATEGIES)} strategies")
    traces = run_queries(questions, embedder, store, all_chunks)
    summary = summarize(traces)
    with open(RESULTS / f"traces_{args.split}.jsonl", "w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    selection = None
    if args.split == "dev":
        selection = select_strategy(summary, stats)
        (RESULTS / "selection.json").write_text(json.dumps(selection, indent=2), encoding="utf-8")
    else:
        selection = json.loads((RESULTS / "selection.json").read_text(encoding="utf-8"))
        write_audit_sheets(pages, all_chunks, traces, docs)

    run_info.update({"finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "summary": summary, "selection": selection})
    payload = json.dumps(run_info, indent=2, ensure_ascii=False)
    (RESULTS / f"run_{args.split}.json").write_text(payload, encoding="utf-8")
    (runs_dir / f"{args.split}_{stamp}.json").write_text(payload, encoding="utf-8")
    write_summary_md(args.split, summary, stats, selection)
    for name in STRATEGIES:
        r = summary[name][args.split]
        log(f"{name} {args.split}: Hit@1 {r['hit1']}/{r['n']}  Evidence Hit@3 {r['hit3']}/{r['n']}  "
            f"misses {r['misses_hit3']}")
    if args.split == "dev":
        log(f"selected on dev: {selection['selected']} (ranking {selection['ranking']})")


if __name__ == "__main__":
    main()
