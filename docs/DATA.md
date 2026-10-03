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

**AI Village (~117 GB, mostly screenshots).** Nothing is downloaded in bulk:
1. `schema` reads only the Parquet footers, then lists each table with its row count, columns, and the estimated size of a text-only pull. **Read `docs/aivillage_schema.md` and `docs/aivillage_card.md` before going further.** Table names are inferred from file paths. Correct `text_tables` / `computer_use_table` in `config/sources.toml` if they're wrong.
2. `text` pulls the small text tables (chat, memories, goals, changelog). It prints which columns it drops and an estimated download size, then asks for confirmation. Use `--tables a b` to choose tables, `--dry-run` to preview, and `--yes` to skip the prompt.
3. `slice` pulls a filtered window of a big table, for example computer-use turns for one goal/episode or time range:
   ```powershell
   uv run python -m backend.ingest.fetch aivillage slice --table turns `
     --where-column goal_id --equals <id1> <id2> --dry-run
   uv run python -m backend.ingest.fetch aivillage slice --table turns `
     --time-column timestamp --start 2026-05-01 --end 2026-05-08 --dry-run
   ```
   Column names here are examples; use the real ones from the schema doc. Drop `--dry-run` once the estimate looks right. Pick episodes from the `text` output before pulling slices.
   Pulls estimated above `default_max_gb` (5 GB) are refused unless you pass `--yes --max-gb N`.

The research terms prohibit training/fine-tuning without written permission and prohibit re-identification. They also require attribution and ask for notification on publication.

## Inspecting what you downloaded

```powershell
uv run python -m backend.ingest.profile data/raw/wiki/revisions.jsonl.gz --sample 3
uv run python -m backend.ingest.profile data/raw/wiki/events.jsonl.gz --group-by event_type
uv run python -m backend.ingest.profile data/raw/transluce/extracted/<pkg>/all-reports.csv
uv run python -m backend.ingest.profile data/derived/aivillage/text/<table>.parquet
```

Send me the outputs of the `events --group-by event_type` profile and `docs/aivillage_schema.md`. The adapters' field mappings are built from these.
