# SwarmScope

**Trace the handoff. Inspect the evidence.**

SwarmScope is an offline, evidence-backed debugger for agent swarms. Pick a URL, commit id, phrase or topic and see its recorded
history: where it first appears, which author labels actually *wrote* it (as opposed to inheriting it from an earlier version), what
the text around it is doing, who explicitly pointed at whom, and which connections the record cannot establish. Built for the
[AI Village × Grove Research AI Swarm Dynamics Hackathon](https://swarmchasing.com/) (Oct 3-4, 2026).

It runs the same pipeline on two datasets: the German message board export from [collusion.wiki](https://collusion.wiki/explorer/download)
(about 15 seconds end to end) and the AI Village text tables (about 2.5 hours, dominated by artifact extraction).

## What it does
- Loads each dataset into a local DuckDB file without changing any source value. Every author label stays separate; a blank label is
  "unknown", never one shared agent. **Labels are not verified agents.**
- Splits every page revision or agent memory line by line into *carried forward*, *new*, *edited*, *restored* and *first seen*, so
  copies are not counted as new writing. Counts of URLs, commit-like ids and repo references are reported twice: in all text and in new
  text only ("occurrence inflation").
  - *Carried forward*: the line is already in the immediately preceding version of the same page (wiki) or the same label's memory
    (AI Village). *Restored*: not in the previous version, but in an earlier one (removed, then back). *Edited*: a close edit of a line
    the previous version had (fuzzy match, lines of 20+ characters). *New*: not seen before in the stream. *First seen*: the first item
    of a stream with no source-stated history, so its lineage is incomplete (never treated as empty or new).
  - Matching is on exact lines (blank lines dropped, trailing whitespace trimmed). "Carried forward" does not mean someone copy-pasted
    from another label: text from a different label is never treated as inherited.
- Tags what new text is doing with a word list you can edit (`config/lexicon.toml`: sharing answers, asking others to relay, timing,
  bypass/proxy talk, probing), grouped by the dataset's own topic classification. Cues are matched words, **not verdicts**.
- Extracts explicit references (one label naming another, wiki links) and request-and-reply exchanges.
- Builds a per-case report whose statements cite exact source spans and say "unknown" where the data cannot answer.
- Serves a local web app (timeline, graph, text inspector with per-line lineage, Conservative mode, Topics & traces tab, review and
  Markdown/JSON export), a static results page, CSV tables, and a human-review pack with a scorer.

## Quick start
Requires [uv](https://docs.astral.sh/uv/) and Python 3.12. Everything runs offline; no API keys are used.
```powershell
uv sync
uv run pytest                      # 81 offline tests on synthetic data
uv run ruff check backend tests
```

### Run it on the German message board
1. Put the export in `data/raw/full-wiki-logs/`: `revisions.jsonl`, `events.jsonl`, `labels.jsonl`, `pages.jsonl`, `manifest.json`
   (and `SHA256SUMS`). Download it from <https://collusion.wiki/explorer/download>; if you get `.gz` files, decompress them first.
2. Build, validate and open:
```powershell
uv run python -m backend.ingest.wiki --raw data/raw/full-wiki-logs --db data/derived/wiki.duckdb
uv run python -m backend.analysis.build --db data/derived/wiki.duckdb
uv run python -m backend.analysis.validate --db data/derived/wiki.duckdb --raw data/raw/full-wiki-logs   # 16 integrity gates
$env:SWARMSCOPE_DB = "data/derived/wiki.duckdb"
uv run uvicorn backend.app.main:app --port 8766          # open http://127.0.0.1:8766/
```

### Run it on AI Village (gated; about 10 GB of disk)
Request access to <https://huggingface.co/datasets/aidigestorg/ai-village>, log in with `uv run hf auth login`, then download only
the text tables (not the screenshot archives):
```powershell
uv run hf download aidigestorg/ai-village --repo-type dataset --local-dir data/raw/aivillage `
  --include "events.jsonl.gz" "chat_messages.jsonl.gz" "chat_rooms.jsonl.gz" "agents.jsonl.gz" "villages.jsonl.gz" `
  "village_goals.jsonl.gz" "agent_goals.jsonl.gz" "computer_use_sessions.jsonl.gz" "agent_memories.jsonl.gz" "summaries.jsonl.gz"
uv run python -m backend.ingest.aivillage                   # -> data/derived/swarm.duckdb, about 2 minutes
uv run python -m backend.analysis.build --steps lineage artifacts edges    # about 2.5 hours
uv run python -m backend.analysis.validate                  # 10 integrity gates
uv run uvicorn backend.app.main:app --port 8765             # open http://127.0.0.1:8765/
```
The cue and reference steps (`--steps cues references`) also work here but have not been run on this much text.

## Using the app
Search for a URL, commit id or phrase, or pick a case on the left. A **timeline** shows one lane per author label (the ring marks the
earliest recorded appearance; hover a dot and its links light up; **Even spacing** helps when events cluster); **Graph** groups
appearances into one arc per label. Click a dot to read the text with every line tagged carried / new / edited / restored; click a
link to see its evidence, ordering strength and competing explanations and record an accept / reject / uncertain review.
**Conservative mode** keeps only links whose order the source's own sequence establishes. The **Topics & traces** tab (wiki) shows
a topic-by-cue heatmap (click a cell for examples), explicit traces per topic, mutual-naming exchanges with their text, resource
adoption, and weekly arrivals of new labels beside how many use each cue. Export any case as Markdown or JSON.
Deep links: `#case=<artifact id>`, `&item=@memory`, `&view=graph`, `&even=1`, `#tab=topics`, `#phrase=<text>`.

## Other outputs
```powershell
uv run python -m backend.analysis.report --db data/derived/wiki.duckdb --out data/derived/report_wiki.html   # static results page
uv run python -m backend.analysis.export_results --db data/derived/wiki.duckdb --out data/derived/results_wiki  # CSV + JSON
uv run python -m backend.analysis.traces --db data/derived/wiki.duckdb          # coordination experiments -> data/derived/experiments/
uv run python -m backend.analysis.review_pack --db data/derived/wiki.duckdb --out data/derived/review_wiki      # human-review pack
uv run python -m backend.analysis.review_score --key data/derived/review_wiki/review_key.json --results <exported>.json
```
The review pack is a self-contained page (answers autosave in the browser, **Export results** downloads JSON); the key stays hidden
from reviewers until scoring. The scorer reports precision with 95% intervals.

## Notes
- DuckDB allows one process per database file: stop the app before any build, report, export or review step. Each dataset gets its
  own database file because a loader wipes the database it is given. `SWARMSCOPE_DB` selects the file for the app.
- Reports, review packs and screenshots contain corpus text: keep them under the ignored `data/` folder.
- Shared strings, similar wording and cue words never establish causation or intent. Order uses recorded database time, whose
  uncertainty neither source documents; links are undirected and carry competing explanations.
- Layout: `backend/ingest` (adapters), `backend/analysis` (lineage, artifacts, edges, cues, references, traces, questions, validation,
  reports), `backend/app` (API and the single-page UI in `static/`), `config/` (sources, cue lexicon), `tests/` (synthetic fixtures).
- Not built: Transluce and SwarmTraces adapters, an LLM layer, a React frontend, and evidence of actions taken (needs AI Village's
  computer-use tables).

## Data sources and terms
- **German message board:** [collusion.wiki](https://collusion.wiki/explorer/download). Redistribution rights unconfirmed; data is never committed.
- **AI Village:** gated, [Hugging Face](https://huggingface.co/datasets/aidigestorg/ai-village). Research terms: no training or
  fine-tuning without written permission, no re-identification, attribution required, notify AI Village on publication.
- **Transluce urlquery agent activity:** [transluce.org/agent-activity](https://transluce.org/agent-activity) (not used yet).
- **SwarmTraces:** [swarmtraces.org](https://swarmtraces.org/) (not used yet).

Counts and findings describe only the loaded snapshots.
