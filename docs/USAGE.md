# Using SwarmScope

SwarmScope answers one family of questions about an agent-swarm corpus: *where does this thing first appear, who
wrote it, how many of its appearances are real new writing, and which links between appearances does the data
actually support?* It is built and validated on the AI Village text tables. Author labels are not verified agents.

## 1. One-time build (offline, about 2.5 hours; most of it is artifact extraction)

```powershell
uv sync
# data/raw/aivillage/ must hold the text tables (see docs/DATA.md for the download command)
uv run python -m backend.ingest.aivillage          # raw tables -> data/derived/swarm.duckdb      (~2 min)
uv run python -m backend.analysis.build            # lineage, artifacts, edges                    (~2.5 h)
uv run python -m backend.analysis.validate         # 8 integrity gates, exits non-zero on failure (~1 min)
```

Budget about 10 GB for the database (the memory text is 6.8 GB). Nothing here calls the network or an LLM.

## 2. Look at the results

| You want | Run | Output |
|---|---|---|
| Static results page (figures, inflation, a few cases) | `uv run python -m backend.analysis.report` | `data/derived/report.html`, open in a browser |
| CSV/JSON tables for a writeup | `uv run python -m backend.analysis.export_results` | `data/derived/results/*.csv`, `results.json` |
| The interactive app | `uv run uvicorn backend.app.main:app --port 8765` | open http://127.0.0.1:8765/ |

Only one process can hold the database at a time (DuckDB), so stop the app before running any build, report, export
or review step, and start it again afterwards.

## 3. The app (three panes)

- **Left: search and cases.** Search artifacts (URLs, commit-like ids, `owner/repo#N`) and chat/goal text. The case
  list holds artifacts shared across author labels plus one carryover example. It is not a representative sample.
- **Centre: the case.** A timeline with one lane per author label (dots = appearances, lines = links) or a clockwise
  graph. Filled dots are new text; hollow dots are restored copies. Solid lines are the same exact string; dashed
  lines are similar-wording candidates. **Conservative mode** keeps only links whose order the source's own sequence
  establishes and shows how many were hidden. Below it: the 10 investigation questions, each with status, citations and limitations.
- **Right: inspector.** Click a dot to read the item. Memories and session goals show every line tagged *carried*,
  *new*, *edited*, *restored* or *first seen*, with the artifact highlighted. Click a link to see its evidence tier,
  ordering strength and competing explanations, and to record a review (accept / reject / uncertain, append-only).
- Export the case as Markdown or JSON from the buttons. Deep links: `#case=<artifact_id>` and `&item=@memory`.

## 4. Human review

```powershell
uv run python -m backend.analysis.review_pack      # -> data/derived/review/ (stop the app first)
```

Give a reviewer **only** `review_pack.html` (or `review_sheet.csv`). It holds 133 items: 43 links, 40 artifact
extractions, 30 lineage lines and 20 question answers. The page saves answers in the browser; **Export results**
downloads `review_results_<initials>.json`. Keep `review_key.json` away from reviewers until they finish. Then:

```powershell
uv run python -m backend.analysis.review_score --results data/derived/review/review_results_AB.json `
  [data/derived/review/review_results_CD.json] --out data/derived/review/scores.md
```

This reports precision with 95% Wilson intervals per relation, artifact type and ordering strength; extraction
precision; agreement of lineage classes with the reviewer; and answer correctness. With two reviewers it also reports
agreement. The brief asks for at least 90% precision on the prominently displayed relation; report the observed
numbers even if that is missed.

## 5. API (for building another front end)

`GET /stats`, `/cases`, `/cases/{artifact_id}` (appearances, edges, answers), `/cases/{id}/export?format=markdown|json`,
`GET /search?q=`, `GET /events/{item_id}` (text and per-line lineage), `GET /datasets`,
`POST /reviews`, `GET /cases/{id}/reviews`. Corpus text is returned as JSON strings only; the page renders it with
`textContent` and a restrictive Content-Security-Policy.

## 6. Reading the numbers correctly

- **Occurrence inflation** = occurrences in all text divided by occurrences in non-inherited text. It measures
  double-counting of carried-forward text, not false transmission.
- **`same_content`** means the exact string appears in new text of two different labels. It does not establish
  copying, direction, or that the labels are different agents. **`possible_reuse`** is similarity only.
- **Ordering**: only edges between two events with different `event_index` are `sequence_ordered`. Everything else is
  ordered by recorded database time, whose uncertainty the source does not give, and is labelled
  `timestamp_ordered_unbounded`.
- **Unknown** in the questionnaire is a result: the loaded tables cannot answer claimed-use, observed-use or
  warning questions.

## 7. Limits and costs

- Artifact extraction is the slow step (about 2 h for 6.8 GB of text, pure-Python regex).
- Similarity retrieval (`possible_reuse`, `backend/analysis/candidates.py`) exists but is not exposed in the app: it was slow
  (20-60 s per case) and found few candidates on the full corpus.
- Search takes about 1.5 s and a full case about 2.5 s on a laptop; the timeline is limited to the first 80
  appearances and the graph to 100 nodes.
- Not loaded: `computer_use_turns`, `claude_code_*` and screenshots, so there is no `observed_use`.
- A Node/React frontend (the brief's stack) is not built yet; this is a dependency-free page served by the API.
