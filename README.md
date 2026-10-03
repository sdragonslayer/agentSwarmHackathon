# SwarmScope

**Trace the handoff. Inspect the evidence.**

SwarmScope is an evidence-backed debugger for agent swarms. Select an agent action, claim, or shared artifact to see its observed history:
- where it first appears in the available record
- which author labels reference or reuse it
- how it changes over time
- which connections remain unestablished

Built for the [AI Village × Grove Research AI Swarm Dynamics Hackathon](https://swarmchasing.com/) (Oct 3–4, 2026).

> Status: early work in progress. The data acquisition tooling is in place; analysis, API, and UI are under construction.

## Quick start

```powershell
uv sync
uv run pytest
uv run python -m backend.ingest.fetch wiki --dry-run
```

See [`docs/DATA.md`](docs/DATA.md) for how to obtain each dataset (German message board, AI Village, Transluce, SwarmTraces). Datasets are never committed to this repo.

## Data sources and terms

- **German message board:** [collusion.wiki](https://collusion.wiki/explorer/download)
- **AI Village:** gated, [Hugging Face](https://huggingface.co/datasets/aidigestorg/ai-village). Used under its research terms: no training, no re-identification, attribution required.
- **Transluce urlquery agent activity:** [transluce.org/agent-activity](https://transluce.org/agent-activity)
- **SwarmTraces:** [swarmtraces.org](https://swarmtraces.org/)

Counts and findings describe only the loaded snapshots. Author labels are not verified agent identities, and textual similarity is not evidence of causal transmission.
