# AI Village results (first full run)

Run 2026-10-03 on the local download of `aidigestorg/ai-village` text tables. Everything below is computed from
`data/derived/swarm.duckdb` (not committed; it contains corpus text and is subject to the dataset's research terms).
Open `data/derived/report.html` for the figures. Regenerate with `uv run python -m backend.analysis.report`.

## Scope
381,610 events; 535,405 text items (246,151 memories, 183,542 chat, 78,361 session goals, 25,939 session
summaries, 352 outreach messages, goals); 3,245 author labels (46 agents, 3,199 human labels). LLM-generated
summaries (939) are loaded but excluded from artifact extraction. Not loaded: `computer_use_turns`,
`claude_code_*`, screenshots.

## Headline findings
1. **Most memory text is carryover.** 78.7% of 73.1M memory lines (57.5M) repeat the same label's previous memory;
   only 19.9% of session-goal lines do. Counting every memory as new text overstates new writing about 4.7×.
2. **Occurrence inflation is large and varies by artifact type.**

   | Artifact | Distinct | Occurrences, full text | Occurrences, new text only | Inflation |
   |---|---|---|---|---|
   | URLs | 57,574 | 4,348,513 | 654,798 | 6.6× |
   | Hex ids (commit/hash-like) | 82,640 | 4,946,145 | 1,167,001 | 4.2× |
   | Repo refs (`owner/repo#N`) | 251 | 2,112 | 864 | 2.4× |

   Scope: all loaded non-generated text. This counts text occurrences; it is not an estimate of false transmission.
3. **Carryover does not cross labels, so label-level spread is unchanged.** Artifacts that appear in 2+ labels' text:
   14,128 URLs / 20,845 hex ids / 31 repo refs, the same whether carryover is counted or not. Inflation distorts
   item and occurrence counts, not how many labels share a string.
4. **The extreme cases are one label repeating itself.** The most inflated URL appears 767 times across 497 items but
   is written once, by one label.
5. **Shared artifacts are real but mostly shared project resources.** Of the 57,574 URLs, 14,128 appear in new
   text of 2+ labels, led by github.com, gitlab.com, ai-village-agents.github.io and docs.google.com. The most
   shared URLs are village-wide project sites, so a shared string here is weak evidence of any handoff.

## Evidence edges
465,636 `same_content` edges: 170,625 URL, 294,829 hex id, 182 repo-ref. Each links an artifact's earliest
non-inherited appearance to later appearances by *different* author labels. All are `rule_derived`, undirected and
carry competing explanations. Edges are a star around the first appearance, so edge count tracks appearance count,
not independent links. Temporal status: only 14,282 (3.1%) are `sequence_ordered`; the other 451,354 are
`timestamp_ordered_unbounded` (memories have no source sequence number and the source gives no clock uncertainty),
so wall-clock order is not established for most. 546 widely repeated artifacts (more than 200 new-text items) get no
edges. No `possible_reuse` edges were built globally; similarity retrieval runs per case (`candidates.py`).

## Validation (all pass on the real data, `uv run python -m backend.analysis.validate`)
- Chat rows and events are one action: 173,493 AGENT_TALK events = 173,493 chat items, no duplicate or missing links.
- Labels namespaced and never merged; every event actor resolves to a label.
- Source times kept verbatim, no invented bounds; `event_index` and time order disagree once.
- Lineage accounting: line counts add up for all 324,512 stream items; 15,955,029 non-inherited line rows match the
  summaries; first item per stream is "incomplete lineage"; no cross-label inheritance.
- Independent check: 200 sampled consecutive memory pairs recomputed in SQL, 0 mismatches.
- 10,000 sampled appearance spans resolve to exact source text; citations for 200 sampled artifact reports resolve.
- Edges: none within one label or touching an unknown label, none directed, none from generated text.
- Real data exposed one bug the synthetic tests missed (template URLs like `http://host:${TOKEN}` crashed URL parsing);
  it is fixed and covered by a regression test.

## What this does not show
- **No human-reviewed precision yet.** Edge and artifact quality are checked for integrity, not accuracy. A hand
  sample of 25 hex ids looked like real git SHAs/hash prefixes (0 obvious false positives); that is a spot check, not
  a measured rate.
- No claim/use detection and no `observed_use`: `computer_use_turns` is not loaded, so "did anyone act on this" is
  unanswerable and the questionnaire abstains.
- Cases in the report are the most inspectable shared artifacts, not a representative sample of agent behavior.
- Dates are recorded database times; the release has 19,131 gaps in `event_index`.
- The card says 31 agents, the release has 46 labels; no merging is attempted.

## Cost
Ingest 2 min; lineage about 25 min; artifact extraction 7,356 s (about 2 h; Python regex over 6.8 GB); edges 8 s;
report 21 s; validation about 1 min. DB 9.5 GB; total new disk use about 12.7 GB including the raw download.
Extraction is the one step worth optimizing before running on other large corpora.

## Addendum: app, review pack, similarity candidates, demo cases
- **App**: `uv run uvicorn backend.app.main:app --port 8765` serves a dependency-free three-pane page (search and cases,
  timeline/graph with conservative mode, inspector with per-line lineage and append-only review). See `docs/USAGE.md`.
  Measured on the real database: search about 1.5 s, full case about 2.5 s, graph 0.15 s.
- **Similarity candidates are weak and slow on the full corpus.** Retrieval takes 20-60 s per case; its ±2-day
  window still exceeds the 60,000-line pool cap (reported as `pool_truncated`), and across 6 sampled cases it found 3
  `possible_reuse` candidates. "No candidates" means "none found in the searched pool". Needs an inverted index on
  rare shingles before it is useful at scale.
- **Human review pack** (`data/derived/review/`): 133 items, seeded and stratified, answers hidden from reviewers:
  43 links (20 URL, 15 hex id, 5 repo-ref `same_content`, 3 `possible_reuse`), 40 artifact extractions, 30 lineage lines
  (10 each inherited/new/modified), 20 question answers. No human has reviewed it yet, so **precision is still unmeasured**.
- **Demo cases** (chosen by hand from the data; see `docs/DEMO.md`): a carryover case (767 full-text occurrences,
  1 new, one label), a cross-label PR announcement, a Google Doc link flagged as a typo, a commit link passed
  chat to memory to another label's memory, and a village-wide shared repo.
- Figures: `data/derived/results/figures/` (report light/dark, app overview, five demo cases, review page); tables:
  `data/derived/results/*.csv` and `results.json`.
