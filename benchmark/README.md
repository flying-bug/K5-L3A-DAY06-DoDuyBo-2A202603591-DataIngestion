# Benchmark: NIST AI RMF 1.0 (NIST AI 100-1)

`questions.jsonl` has 22 questions (16 dev, 6 test). The split was fixed **before** any retrieval run. Do not edit the test questions after looking at results. If you do, record it here and do not report that test set as an independent holdout.

## Fields
`id, split, type, question, expected_answer, gold_source_id, gold_page, evidence_quote, filter`, plus an optional `alternatives` list of other valid `{gold_page, evidence_quote}` pairs. For example, q06 is answered on both page 17 and page 8.

- `gold_page` is the **physical PDF page** (1-based). It is not the printed page number: printed page = PDF page − 5 for pages 6–47.
- `type` is one of `direct`, `paraphrase`, `paraphrase_vi` (question in Vietnamese, source in English), `conditional`, or `filter`.

## Metadata filter
- The field is `function`, with values `GOVERN | MAP | MEASURE | MANAGE`. It is taken from the section headings "5.1 Govern" … "5.4 Manage" and from the table captions "Table N: Categories and subcategories for the X function". Chunks outside section 5.1–5.4 have `function = null`.
- 6 questions use a filter (4 dev, 2 test). The filter value comes from the question wording itself ("Under the MANAGE function, …"). It is input the user supplies before retrieval, not information taken from the gold answer.
- Why the filter is useful: the four tables use very similar wording. Third-party risk, for example, appears in GOVERN 6, MAP 4 and MANAGE 3. Without a filter, retrieval can easily pull a subcategory from the wrong function.
- For strategy C, questions with `filter = null` run without a filter, exactly as in B.

## Evidence verification
Run `python starter/scripts/verify_benchmark.py`. It confirms that every `evidence_quote` (and every alternative) appears on its gold page after normalization. Normalization is NFKC, lowercase, and keeping only `[a-z0-9]`, which removes PDF line-break hyphenation and curly quotes. The same normalization is used for Evidence Hit@k (`starter/src/textmatch.py`). Last run: 22/22 OK.

## Selection criterion (decided before seeing test)
1. Higher Evidence Hit@3 on **dev**.
2. If tied, higher Hit@1 on dev.
3. If still tied, fewer chunks and lower ingest time.

The test set is run once, after the configuration has been chosen.

### What happened (run log)
- Dev run 2026-11-13 10:11 UTC: A 13/16, B 15/16, C 15/16 Evidence Hit@3. B and C share one index and tied on all three criteria, so the rule could not separate them. The tie is recorded in `starter/results/selection.json` and both were carried to test. The dev run was repeated at 10:12 UTC only to change how the tie is written to `selection.json`. No strategy, parameter or question changed, and the metrics were identical.
- Test run 2026-11-13 10:13 UTC, run once: A 5/6, B 4/6, C 4/6 Evidence Hit@3. Test was not used to change anything afterwards.

## Limitations and leakage risk
- There is only one document, so dev and test cannot be split by document. They are split by topic/section where possible, but share vocabulary.
- The questions and evidence were drafted with AI assistance. The author has now manually reviewed all 22 questions, expected answers, and evidence against the source PDF; the automatic verifier also confirms that each evidence quote appears on its gold page. This review checks answer completeness and relevance, not only string presence.
- With 6 test questions, one question equals about 17 percentage points. Do not generalize beyond this corpus.
