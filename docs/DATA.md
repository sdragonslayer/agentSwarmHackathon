# Getting the data

Everything goes under `data/` (gitignored). Never commit it. Redistribution rights for these datasets are unconfirmed, and AI Village is gated.
Every command supports `--dry-run`, which prints URLs and target paths without downloading. Add `--check-size` to send HEAD requests for file sizes.

## 0. One-time setup

```powershell
uv sync                      # installs the pinned environment from uv.lock
```

Create `.env` in the repo root (it's gitignored):

```
HF_TOKEN=            # Hugging Face token with approved access to aidigestorg/ai-village
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
LLM_BUDGET_USD=100   # hard cap across both providers
```

Instead of setting `HF_TOKEN`, you can run `uv run hf auth login`.

## Recommended order

| # | Command | Source / access | Lands in | Size |
|---|---|---|---|---|
| 1 | `uv run python -m backend.ingest.fetch wiki` | [collusion.wiki/explorer/download](https://collusion.wiki/explorer/download), public | `data/raw/wiki/*.gz` + `SNAPSHOT.json` | small; check with `--dry-run --check-size` |
| 2 | `uv run python -m backend.ingest.fetch transluce` | [transluce.org/agent-activity](https://transluce.org/agent-activity), public ZIP | `data/raw/transluce/` (keeps only `all-reports.csv` + README) | small |
| 3 | `uv run python -m backend.ingest.fetch aivillage schema` | [HF gated dataset](https://huggingface.co/datasets/aidigestorg/ai-village). **Request access on that page first.** | `docs/aivillage_schema.md`, `docs/aivillage_card.md`, `data/derived/aivillage/schema.json` | a few MB (Parquet footers only) |
| 4 | `uv run python -m backend.ingest.fetch aivillage text` | same | `data/derived/aivillage/text/*.parquet` | shown before download; binary/screenshot columns dropped |
| 5 | `uv run python -m backend.ingest.fetch swarmtraces --url <URL>` | [swarmtraces.org/viewer](https://swarmtraces.org/viewer/): copy the redacted JSONL.gz link | `data/raw/swarmtraces/` | check `--dry-run --check-size` |
| 6 | `uv run python -m backend.ingest.fetch aivillage slice ...` | same as 3 | `data/derived/aivillage/slices/<name>/` | shown before download |

Each real run writes a `SNAPSHOT.json` recording the URL, retrieval time, compressed and decompressed SHA-256, and importer version. A re-run keeps the previous snapshot as `SNAPSHOT.<time>.json`. Interrupted downloads resume from `*.part` files.

## Notes per source

**Wiki.** After downloading, the tool compares the decompressed hashes of `revisions.jsonl` and `events.jsonl` with the snapshot inspected in the brief (manifest dated 2026-09-03). A mismatch only produces a warning. It means the publisher released a newer snapshot: keep it, then reconcile the counts. Don't force them to match.

**Transluce.** Use `all-reports.csv` alone; don't also concatenate the component catalogs. Its confidence labels are qualitative judgments, not probabilities or confirmed identities.

**SwarmTraces.** The download URL isn't verified, so it isn't hard-coded. Pass it with `--url` or set `[swarmtraces].url` in `config/sources.toml`. Most payloads have no native timestamp.

**AI Village (~117 GB, mostly screenshots).** The release is JSONL tables plus per-day screenshot tars, not Parquet,
so the `fetch aivillage ...` commands do not apply. Download only the text tables (a few GB):

```powershell
uv run hf download aidigestorg/ai-village --repo-type dataset --local-dir data/raw/aivillage `
  --include "village-transcript.json" "README.md" "events.jsonl.gz" "chat_messages.jsonl.gz" `
  "chat_rooms.jsonl.gz" "agents.jsonl.gz" "villages.jsonl.gz" "village_goals.jsonl.gz" `
  "agent_goals.jsonl.gz" "computer_use_sessions.jsonl.gz" "agent_memories.jsonl.gz" "summaries.jsonl.gz"
```

Then build (all local, offline; the database is ~8-10 GB):

```powershell
uv run python -m backend.ingest.aivillage        # raw tables -> data/derived/swarm.duckdb
uv run python -m backend.analysis.build          # lineage, artifacts, edges
uv run python -m backend.analysis.validate       # integrity gates
```

What was verified about these files is in `docs/aivillage_findings.md`.

The research terms prohibit training/fine-tuning without written permission and prohibit re-identification. They also require attribution and ask for notification on publication.

## Inspecting what you downloaded

```powershell
uv run python -m backend.ingest.profile data/raw/wiki/revisions.jsonl.gz --sample 3
uv run python -m backend.ingest.profile data/raw/wiki/events.jsonl.gz --group-by event_type
uv run python -m backend.ingest.profile data/raw/transluce/extracted/<pkg>/all-reports.csv
uv run python -m backend.ingest.profile data/derived/aivillage/text/<table>.parquet
```

Send me the outputs of the `events --group-by event_type` profile and `docs/aivillage_schema.md`. The adapters' field mappings are built from these.
