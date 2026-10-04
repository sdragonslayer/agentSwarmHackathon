# SwarmScope

**Trace the handoff. Inspect the evidence.**

SwarmScope is an evidence-backed debugger for agent swarms. Select an agent action, claim, or shared artifact to see its observed history:
- where it first appears in the available record
- which author labels wrote or repeated it, separating genuinely new text from carried-forward and restored copies
- how it changes over time
- which connections remain unestablished

Built for the [AI Village × Grove Research AI Swarm Dynamics Hackathon](https://swarmchasing.com/) (Oct 3–4, 2026).

> Status: working end to end on two datasets, the AI Village text tables and the German message board (collusion.wiki):
> ingest, revision/memory lineage, artifact extraction, evidence links, a per-artifact investigation report (what labels do with it, topics, spread, explicit references), integrity
> gates (16 on the wiki, 10 on AI Village), a dependency-free web app, a static results report, and a human-review pack.
> Also: topic/cue analysis, explicit references and coordination traces on the wiki (`docs/EXPERIMENTS.md`).
> Not built: Transluce and SwarmTraces adapters, the React frontend, an LLM layer, and `observed_use` evidence.
> Start with [`docs/WRITEUP.md`](docs/WRITEUP.md) (what it is and found), then [`docs/USAGE.md`](docs/USAGE.md). Results:
> [`docs/RESULTS.md`](docs/RESULTS.md), [`docs/wiki_findings.md`](docs/wiki_findings.md). Demo: [`docs/DEMO.md`](docs/DEMO.md).
> Things still to check by hand: [`TODO.md`](TODO.md).

## Quick start

```powershell
uv sync
uv run pytest                                              # offline, synthetic data only

# German message board (about 15 s), data in data/raw/full-wiki-logs/
uv run python -m backend.ingest.wiki --raw data/raw/full-wiki-logs --db data/derived/wiki.duckdb
uv run python -m backend.analysis.build --db data/derived/wiki.duckdb
uv run python -m backend.analysis.validate --db data/derived/wiki.duckdb --raw data/raw/full-wiki-logs
$env:SWARMSCOPE_DB = "data/derived/wiki.duckdb"; uv run uvicorn backend.app.main:app --port 8766   # open http://127.0.0.1:8766/
```

AI Village needs its gated text tables and about 2.5 hours for the full build; commands are in [`docs/USAGE.md`](docs/USAGE.md).
See [`docs/DATA.md`](docs/DATA.md) for how to obtain each dataset. Datasets are never committed to this repo.

## Data sources and terms

- **German message board:** [collusion.wiki](https://collusion.wiki/explorer/download)
- **AI Village:** gated, [Hugging Face](https://huggingface.co/datasets/aidigestorg/ai-village). Used under its research terms: no training, no re-identification, attribution required.
- **Transluce urlquery agent activity:** [transluce.org/agent-activity](https://transluce.org/agent-activity)
- **SwarmTraces:** [swarmtraces.org](https://swarmtraces.org/)

Counts and findings describe only the loaded snapshots. Author labels are not verified agent identities, and textual similarity is not evidence of causal transmission. Reports, screenshots and review packs contain corpus text and are kept under the ignored `data/` folder.
