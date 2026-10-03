# TODO

Owner: **U** = you (human), **A** = agent session (backend), **B** = agent session (frontend), **C** = agent session (data/LLM). See the plan's schedule.

## Now (Oct 2, tonight)
- [ ] U: Request AI Village access on Hugging Face (manual review; do it first)
- [ ] U: Install Node LTS (needed for the frontend)
- [ ] U: Create `.env` from the template in `docs/DATA.md`
- [ ] U: `git init`, first commit, create the GitHub repo (private until data rights are checked)
- [ ] U: Run `fetch wiki` and `fetch transluce`; send the outputs of `profile ... events.jsonl.gz --group-by event_type` and `profile ... revisions.jsonl.gz`
- [ ] U: Copy the SwarmTraces download link from swarmtraces.org/viewer; run `fetch swarmtraces --url ...`
- [ ] U: Once access is granted: `fetch aivillage schema`, then share `docs/aivillage_schema.md`
- [ ] A: DuckDB schema (`snapshot`, `raw_record`, `event`, `text_change`, `actor_label`, `artifact`, `appearance`, `evidence_edge`, `review`, `case`)
- [ ] A: Synthetic fixtures for every correctness gate (brief §11A)
- [ ] A: Wiki adapter + hunk-convention validator (rebuild bodies, check `body_sha256`)
- [ ] B: Vite + React + TS scaffold with a mock-JSON three-pane shell (once Node is installed)

## Oct 3 AM
- [ ] U: `fetch aivillage text`; pick 2–3 episodes; `fetch aivillage slice ...` for their computer-use turns
- [ ] A: lineage.py: new/inherited/modified/restored/unknown spans
- [ ] A: artifacts.py: URLs (keep params/case), page refs, code blocks, distinctive n-grams, run over novel spans only
- [ ] A: inflation.py: **headline number** (full-revision vs novel-span occurrence counts, with denominators)
- [ ] B: Timeline (lanes by label or page, plus an undated area) + Inspector (diff highlighting, raw IDs, clock)
- [ ] C: AI Village adapter (mapping from the schema doc)
- [ ] C: LLM client: cache, $100 hard cap, cost dry-run, quote validation

## Oct 3 PM
- [ ] A: candidates.py (MinHash LSH, ≤20 per appearance), edges.py, chronology.py
- [ ] A: FastAPI endpoints (`/datasets`, `/search`, `/events`, `/artifacts/.../appearances`, `/cases/.../graph`)
- [ ] B: Case graph (Cytoscape, ≤100 nodes, solid = explicit, dashed = proposed) + conservative-mode toggle
- [ ] C: Extraction batch (Sonnet, batch API) over novel spans + chat for the selected episodes
- [ ] C: Claim↔action matching (`reports_use` vs `observed_use`) on AI Village

## Oct 3 night
- [ ] A: questions.py (10 deterministic templates), export_case.py (Markdown + JSON), `/reviews`
- [ ] B: Review controls, export UI
- [ ] C: Edge adjudication (Opus + OpenAI second opinion); disagreements go to human review
- [ ] U: Pick demo cases from the real data (1 real case + 1 ambiguous/carryover); review ~20 edges

## Oct 4 AM
- [ ] A: Transluce + SwarmTraces adapters; cross-source exact-artifact matching (`same_content` only)
- [ ] C: Small eval: precision on reviewed edges, inflation table, citation resolution check
- [ ] B: Polish, screenshots

## Oct 4 PM: submit
- [ ] U: 3-minute demo video (search → history → edge → conservative mode → carryover → export)
- [ ] U: Write-up: findings first (inflation number, claim-vs-action results), then method and limitations, then data audit
- [ ] U: Check data rights before making the repo public; confirm no `data/` content in git history

## Cut order if behind
SwarmTraces adapter → embeddings → second-model adjudication → graph (keep timeline + inspector). Never cut provenance or revision handling.
