# SwarmScope: an evidence-backed debugger for agent swarms

Implementation brief for a coding agent · Prepared October 2, 2026 (user local date)

## 1. Decision and project pitch

**Build a tool that lets a researcher select an agent action, claim, or shared artifact and inspect its observed history: where it first appears in the available record, which actors reference or reuse it, how it changes, and which connections remain uncertain.**

Start with the German message-board export at collusion.wiki. Make a revision-aware timeline and a small, inspectable provenance graph the core product. Add a fixed investigation questionnaire and an exportable evidence packet. Treat AI Village as a valuable later adapter if access is available; do not make approval for it a prerequisite for the demo.

Working name: **SwarmScope**. Tagline: **“Trace the handoff. Inspect the evidence.”**

The demo should answer a specific question such as: “How did this workaround or answer appear across different author labels, and what evidence connects the appearances?” It must be able to answer “we cannot establish that link.”

This brief specifies a project to implement. It does not claim that any new diffusion chain or research finding has already been established.

## 2. Critique of the visualization idea

Your instinct is strong: incident investigators need to understand sequences, interactions, and shared infrastructure. A timeline connected to source evidence can make a large corpus tractable. However, a generic network visualization is an insufficient research contribution.

Five failure modes matter:

1. **A graph can invent causality.** Two actors using the same technique might have a common prompt, an external source, copied boilerplate, or independent discoveries. An earlier mention alone does not establish transmission.
2. **Names are not necessarily agents.** Authors can change names, share labels, or omit them. A label graph cannot automatically answer how many independent agents participated.
3. **The collection process changes the apparent story.** Missing reads, deleted pages, incomplete snapshots, and uncertain clocks affect every reconstruction. “First observed here” is defensible; “invented by this agent” usually is not.
4. **Beautiful graphs can be less useful than search.** A global hairball makes a good screenshot but often makes investigation slower. Start from a question or a selected event, then expand only the relevant neighborhood.
5. **Existing resources already offer exploration.** SwarmTraces has an evidence search viewer [S4]; collusion.wiki has explorer pages [S1]. Differentiate through revision handling, explicit edge evidence, competing explanations, and measured investigation usefulness. Do not claim this is the first swarm explorer without a broader literature review.

The most interesting version is therefore **a forensic investigation workflow with a visualization interface**. Its research contribution is whether a conservative reconstruction method helps people answer questions accurately, including recognizing when the data cannot answer them.

### Alternatives considered

These are project judgments, not empirical rankings.

| Direction | Potential value | Main obstacle | Decision |
|---|---|---|---|
| Evidence-backed reconstruction and information tracing | Directly supports incident analysis; concrete visual demo and evaluation | Attribution and observation gaps | Build this |
| Generic summaries plus chat over logs | Quick utility | Weak differentiation; summaries can conceal unsupported links | Use only inside the reconstruction workflow |
| Detect new swarms on the open web | Potentially very valuable | Hard to obtain labeled negatives and verify authorship; collection scope expands rapidly | Later project |
| Agent whistleblowing intake | Could create useful reporting channels | Adoption, incentives, and verification dominate the engineering | Complement existing reporting tools later |
| Aggregate every incident dataset | Useful foundation | Harmonization can consume the whole hackathon without producing an investigation result | Design adapters, ship one |
| Reproduce observed incidents in a controlled sandbox | Stronger causal research | Requires another environment and experiment design | Follow-up after the observational tool |

## 3. Dataset audit and selection

### What was actually checked

The planning pass read the public project pages, downloaded and inspected the wiki revisions/events/labels/manifest exports, and inspected Transluce's ZIP listing, README, and a sample CSV. Wiki revision and event counts were checked against the decompressed files. The AI Village card was accessible, but its schema file returned HTTP 401. The SwarmTraces report and viewer were readable through web retrieval; its raw dataset was not inspected. Do not describe all four schemas as verified.

| Dataset | Verified availability and contents | Suitability and implementation decision |
|---|---|---|
| German-board export [S1, S2] | Public compressed JSONL. Inspected snapshot: 14,591 saved revisions, 4,579 pages, 3,103 published labels. Separate event and manifest files. | Primary MVP: manageable size, revision links, content, and clock provenance. Counts are revisions/pages/labels, not interchangeable counts of messages or agents. |
| AI Village [S5] | Research access is manually reviewed. The card describes chat, computer sessions and turns, memories, goals, screenshots, and a scaffolding changelog. | Rich later source for linking discussion to actions. Read the actual schema after access. Treat generated summaries and agent self-reports as secondary evidence; account for scaffolding changes. Research terms prohibit training/fine-tuning without written permission and re-identification, require attribution, and request publication notification. |
| Transluce URLQuery release [S6, S7] | Inspected archive contains 38,160 distinct report records. It provides report links and research metadata, not full response bodies, screenshots, or raw submitted programs. | Optional report-metadata overlay. Not a drop-in agent transcript corpus. Actor attribution remains unknown unless separately supported. |
| SwarmTraces [S3, S4] | Report describes 80,000+ reconstructed payloads; viewer advertises a redacted gzipped JSONL release. Raw schema unverified here. | Later stress test for uncertain chronology and artifact lineage. Authors report roughly 80% outbound data and 97% of payloads lacking native timestamps, and warn that names do not establish unique agents. Avoid action-success or diffusion claims from payload presence alone. |

The user's approximate “18k posts” description should not become the program's denominator. Display the population actually loaded. The inspected wiki manifest explicitly distinguishes overlapping save/delete/revert/probe populations; its 19,913 physical event rows are not 19,913 independent incidents [S2].

### Acquisition instructions

For the MVP, obtain these publisher-provided files:

- `https://collusion.wiki/explorer/download/revisions.jsonl.gz`
- `https://collusion.wiki/explorer/download/events.jsonl.gz`
- `https://collusion.wiki/explorer/download/pages.jsonl.gz`
- `https://collusion.wiki/explorer/download/labels.jsonl.gz`
- `https://collusion.wiki/explorer/download/manifest.json.gz`

Start with revisions, events, and manifest. Pages and labels are optional indexes, not additional independent observations. Save acquisition time, source URL, compressed hash, decompressed hash, and importer version. Check the publisher's current checksums rather than silently assuming the snapshot is immutable.

Inspected snapshot reference values:

```text
manifest.generated_at = 2026-09-03T03:42:36Z
manifest.cut = revision.write_date >= 2026-05-01
revisions.jsonl SHA256 = 60df4a515178230aa952d9f64f6215aea4bd95ab2f05e31e484cf9b887e3f793
events.jsonl SHA256 = 588584295f1c4a7c3d90b04075ab151504f165ff069534d935cda08853ec28b1
```

If hashes change, record a new snapshot and reconcile the counts; do not force a newer release to match old totals. Preserve the source manifest's collection cut and coverage limitations in the UI.

Optional Transluce archive:

`https://transluce.org/data/urlquery-agent-activity-2026-09-23.zip`

Use `all-reports.csv` alone rather than concatenating it with its component catalogs. Retain report IDs, timestamp precision, disposition, confidence, broad class, inclusion rationale, and caveats. The archive's confidence categories are qualitative judgments about agent-like activity, not authenticated identities or probabilities [S7].

**Access fallback:** spend at most 30 minutes on obtaining the wiki export. If temporarily unavailable, accept the same files through local upload and build against explicitly synthetic fixtures. If real data remains unavailable, deliver a clearly labeled prototype and an acquisition blocker; never pass fixtures off as a real incident. Do not bypass AI Village's gate.

Public downloadability does not settle redistribution rights. Record the license/terms status, keep restricted corpora out of a public repository, and make demo data fetching configurable. Confirm rights before publishing copied datasets.

## 4. Scope and success criteria

Assume a 24–48 hour hackathon, one coding agent, and a human available to review examples. Prioritize a complete vertical slice over broad dataset coverage.

### Must ship

1. Reliable wiki importer with preserved revisions and source pointers.
2. Extraction of **newly added or modified text**, separated from unchanged inherited text.
3. Search and a timeline showing author labels, pages, changes, and uncertainty.
4. A selected artifact's appearances and an evidence-backed graph of references and candidate reuse.
5. A panel explaining every edge, including alternative explanations.
6. A deterministic investigation questionnaire with cited answers and explicit unknowns.
7. One manually reviewed real case plus a negative/ambiguous example.
8. A small evaluation against ordinary search and chronological browsing.

### Stretch only

- Evidence-constrained LLM extraction and claim-level summaries.
- One second-source adapter: Transluce metadata or AI Village if already authorized.
- Comparing propagation of warnings versus workarounds, if both have enough reviewed examples.
- A graph showing how conclusions change when uncertain edges are hidden.

### Exclude from the MVP

Live web crawling, payload execution, de-anonymization, model training, automatic identity merging, a universal incident warehouse, simulated causal interventions on historical logs, and an unrestricted chat agent. Do not promise causal influence estimates from observational similarity.

## 5. Research question and demo story

**Primary question:** Can revision-aware provenance reconstruction improve the accuracy and speed of answering who introduced, referenced, modified, or reused an artifact within an observed agent interaction corpus?

**Secondary question:** How much does naive full-revision analysis inflate apparent diffusion by counting unchanged text again?

Here an artifact may be a distinctive claim, answer, URL with task-specific parameters, instruction, code fragment, or named shared resource. An artifact family groups related versions; membership itself can be uncertain.

Candidate cases should come from the data, not a prewritten sensational narrative. Rank for inspectability: multiple appearances, explicit cross-references, material changes, useful clock evidence, and at least two author labels. Describe this as an interesting-case sample, not a representative sample of swarm behavior.

Suggested demo sequence:

1. Search for a distinctive resource or claim and select an appearance.
2. Open its history. Show newly introduced text alongside inherited material.
3. Select a suspected handoff between two appearances; inspect the exact spans and link type.
4. Switch to conservative mode. Show which links survive and which become unresolved.
5. Open an example where repeated text came from successive page snapshots. Explain why counting those snapshots as messages would exaggerate spread.
6. Export a short report containing supported findings, alternatives, and missing evidence.

If the data do not support a clear multi-actor handoff, demonstrate that limitation and choose an artifact-reuse case. The product must remain useful without manufacturing a diffusion chain.

## 6. Data model

Keep immutable source records separate from derived analysis. Never overwrite source timestamps, text, or identifiers with inferred values.

| Entity | Required fields and meaning |
|---|---|
| `DatasetSnapshot` | ID, source URL, retrieved time, source manifest, hashes, license status, importer version, coverage notes |
| `RawRecord` | Snapshot ID, source file, stable row ID, original serialized data, hash, source pointer |
| `Event` | Stable ID, event kind, page/artifact ID, author-label reference or null, source time, time bounds or null, clock provenance, source ordering fields, raw record references |
| `TextChange` | Revision ID, base revision ID, operation, exact spans in old/new bodies, text, inherited/new/modified/restored/unknown classification, attribution basis |
| `ActorLabel` | Namespaced label, first/last observed use, attribution source, identity status; no default real-agent ID |
| `Artifact` | Type, raw and normalized representation, exact hash, optional family ID, extraction version |
| `Appearance` | Artifact ID, event/change ID, source span, mention/use/claim/unknown role, extracted-versus-reviewed status |
| `EvidenceEdge` | Endpoints, relation type, evidence tier, supporting spans/records, temporal status, alternatives, detector version, reviewer decision |
| `Case` | Seed, dataset snapshots, bounded scope, selected events, review notes, conclusions, unanswered questions |

Use source-local ID namespaces. An empty author label means unknown, not one shared anonymous agent. Do not merge blank labels, truncated IP addresses, or similarly named labels into an actor.

### Verified wiki fields to map

Revision rows inspected contain:

```text
rev_id, page_id, page_key, wiki, name, seq, rcs_rev, rcs_path,
body, body_len, body_sha256, lines,
diff_base, diff_base_reason, hunks,
label, ip16,
time, time_grade, winning_clock, uncertainty_seconds,
request_time, success_time, recent_changes_time, write_date, archived_at,
request_action, change_summary, related_event_id, relation_type,
round_id, body_encoding
```

Hunks contain `op`, `a0`, `a1`, `b0`, `b1`. **Verify their indexing and line-splitting convention by reconstructing real changes before relying on them.** The field names alone do not establish the offset convention. Validate source `body_sha256` against its documented encoding/representation; do not silently normalize Unicode or line endings first.

Event fields vary by event type. An inspected probe row contains `event_id`, `event_type`, `time`, `time_grade`, `ip16`, `request_action`, `param_family`, `source_refs`, and `success_observed`. Profile each type before mapping. Retain unexpected fields in raw records and report schema drift.

The revision's `label` identifies the editor associated with that revision, not the author of every sentence remaining in the page. A newly inserted quotation is an insertion by this editor but may contain another actor's words. Keep edit attribution and textual speaker attribution separate.

## 7. Reconstruction algorithm

### A. Build revision lineage before extracting messages

1. Group revisions by source namespace and page. Preserve `diff_base` and revision sequence.
2. Join explicit bases by ID. Do not choose a predecessor solely by timestamp; inspected rows can share a timestamp.
3. Derive inserted, removed, and changed spans; retain the full page as context.
4. Unchanged inherited content is not a new utterance or independent adoption.
5. If the base is missing, classify the available text as first observed in an incomplete lineage. Do not assume every word was newly authored.
6. Mark restorations/reverts separately. Restoring an older body should not become a fresh invention.
7. Do not force every hunk to be one message: a hunk can contain several speakers or partial edits. Create span-level changes first, optional utterance segmentation second.
8. Link save events and revision records using verified source identifiers to avoid representing one save as two independent actions.

### B. Extract artifacts and candidate relationships

Start deterministically with URLs, page references, exact distinctive snippets, and code/text hashes. Preserve original strings. Maintain separate exact and normalized matches. URL normalization must preserve meaningful query parameters and case-sensitive paths. A shared domain is too broad to count as a shared artifact.

Use token-shingle similarity or a text index to retrieve possible paraphrases/copies. Downweight globally common boilerplate and repeated templates. Preserve rare changed constants or phrases as evidence features. Similarity retrieves candidates; it does not authorize a transmission edge.

Avoid all-pairs comparison. Index exact identifiers/hashes, then retrieve at most 20 approximate candidates per selected appearance within a configurable case scope. Permit explicit references outside a time window. Store retrieval settings so results are reproducible.

### C. Give edges semantics that match their evidence

| Relation | What supports it | What it does not establish |
|---|---|---|
| `revision_of` | Explicit revision lineage | Communication between different actors |
| `references` | A source span explicitly names or links a resolvable artifact/page/message | That the referencing actor read all its content |
| `same_content` | Exact distinctive content or artifact hash | Direction, copying, or independent actor identity |
| `possible_reuse` | Distinctive overlap or transformation plus compatible context | Causal transmission |
| `reports_use` | Text explicitly claims use, with an identifiable referent | Successful execution or truthful reporting |
| `observed_use` | A separately recorded action/output demonstrates the specific use | Why it was used or where the idea originated |
| `contradicts` / `corrects` | Identifiable propositions and cited source spans, reviewed for meaning | That a correction was received or acted on |

Evidence tiers: `source_recorded`, `rule_derived`, `model_proposed`, `human_reviewed`. These are provenance categories, not a universal numerical confidence scale. Human review can reject a source's behavioral interpretation while accepting that the source record exists.

Keep distinct fields for whether the record exists, the behavior is directly observed, the actor attribution is reliable, and temporal order is established. A clearly recorded self-report can still be false. Do not turn a heuristic score into a probability such as “91% causal influence.”

### D. Use partial chronology

Store supplied clock grades and uncertainty verbatim. Only derive a time interval after checking what the source's uncertainty field means; do not assume it is a calibrated confidence interval or a symmetric error bound. If no defensible bounds exist, leave them unknown.

For defensible intervals A and B, strict timestamp precedence requires `A.latest < B.earliest`. Overlap means unresolved order unless a separate sequence/reference establishes it. Distinguish source sequence order from wall-clock order. Never use `archived_at` as the action time or treat an embedded timestamp as a trusted execution clock.

A `possible_reuse` edge may be undirected. The general evidence graph can contain cycles. Only a separately filtered, validated temporal subgraph should be presented as a directed propagation path. Do not invent missing times to force a DAG.

### E. Optional LLM layer

The complete MVP must work without an API key. If a model is available, use it for narrow extraction or concise explanations over retrieved evidence bundles.

Require structured outputs containing source IDs, exact supporting spans, relation type, uncertainty, and alternatives. Validate that every quoted span exists. Reject missing/invalid citations. Distinguish structural citation validity from semantic support; a real quote can still fail to support the claim.

Cache by source hashes, model ID, prompt version, and extractor version. Use no model tools or browsing while processing logs. Logs are untrusted data and may contain instructions; the extractor must not follow them. Precompute results for the demo rather than making navigation depend on model latency.

## 8. Product interaction and visual design

Use three coordinated areas on desktop:

- **Case/search pane:** search by text, page, author label, or artifact; saved cases; dataset scope and coverage summary.
- **Main timeline:** horizontal time with lanes for author labels or pages, expandable activity clusters, revision changes, uncertainty ranges, and an undated area. Allow page lanes when actor attribution is weak.
- **Evidence inspector:** original text, highlighted changed spans, previous revision comparison, raw identifiers, clock details, link rationale, alternatives, and review controls.

The graph is a second view of the selected case, not the homepage. Show at most 100 nodes initially, with explicit expansion and aggregation. Use event/artifact nodes for the main evidence view; an actor-label summary graph is optional and clearly labeled.

Interactions that matter:

1. Click an event to see its exact source and before/after diff.
2. Click an artifact to highlight its appearances across pages/labels.
3. Click an edge to inspect the evidence and its limitations.
4. Toggle candidate reuse on/off without hiding the source records.
5. Filter by time precision and attribution quality.
6. Accept/reject/mark uncertain an inferred edge, recording reviewer rationale.
7. Export a stable case link locally and a Markdown/JSON evidence packet.

Use labels and line styles as well as color. Solid lines can represent explicit source links; dashed lines represent proposed reuse. The legend must explain that even an explicit reference does not prove causal influence. Always show “author labels” rather than “agents” when identities are unverified.

Default metrics: number of source revisions, novel text changes, artifact appearances, distinct author labels, reviewed links, and unknown-attribution records. Put the denominator and selected scope next to every rate. Do not display a “swarm danger score.”

## 9. Built-in investigation questionnaire

Run these questions for a selected case. Each answer contains: claim, status (`supported`, `partial`, `unknown`, `conflicting`), citations, and limitations. Use deterministic templates first; optional model prose must preserve the same structure.

| Question | Required behavior |
|---|---|
| What is the earliest observed appearance? | Report within the loaded scope; include ties/uncertain order and collection boundaries. |
| Which author labels introduced new material? | Attribute changes to editors; distinguish quotations and unknown authors. |
| Which later appearances explicitly reference earlier material? | Show resolvable references and evidence spans. |
| Which appearances merely resemble one another? | Separate similarity candidates from supported references. |
| How did the content change? | Show meaningful additions, omissions, corrections, and changed parameters. |
| Did anyone claim to use the information? | Cite the self-report and label it as such. |
| Is use or success independently observed? | Require an action/output record supporting the specific outcome; otherwise abstain. |
| Were there warnings or corrections? | Identify reviewed examples; lack of a recorded response is not proof they were ignored. |
| What competing explanation fits? | Consider common source, inherited page text, templates, aliasing, and independent work. |
| What cannot be reconstructed? | Identify missing reads, uncertain identities, lost revisions, ambiguous clocks, and unobserved outcomes. |

If there are no per-agent read logs, do not calculate the percentage of agents who “saw but ignored” a warning. Availability on a shared board is not established exposure.

## 10. Technical implementation contract

Suggested stack, chosen for a small local project rather than mandated versions:

- Python ingestion and analysis; SQLite with full-text search for the MVP.
- FastAPI for a small query API.
- React and TypeScript frontend, a timeline component, and a graph library such as Cytoscape.js.
- Filesystem raw snapshots plus SQLite derived tables; no graph database or vector service required.

Before installing, check current official documentation and repository conventions; pin compatible dependencies. A different familiar stack is acceptable if it preserves the behavior and ships faster.

Repository layout:

```text
backend/app/             API, schemas, queries
backend/ingest/          snapshot handling and source adapters
backend/analysis/       revision diffs, artifacts, evidence rules
frontend/src/           search, timeline, graph, inspector
data/raw/               ignored local publisher files
data/derived/           ignored indexes and cached extraction
fixtures/synthetic/     small explicitly synthetic edge cases
cases/                  reviewed case definitions, subject to data rights
eval/                   question set, annotations, scoring, results
docs/                   data audit, methods, limitations
```

Proposed commands to implement, not claims about an existing CLI:

```bash
python -m backend.ingest.wiki --input data/raw/wiki --db data/derived/swarm.db
python -m backend.analysis.build --db data/derived/swarm.db
python -m backend.analysis.export_case --case cases/demo.json --format markdown
```

Minimum API behavior:

| Endpoint | Contract |
|---|---|
| `GET /datasets` | Snapshots, provenance, counts, coverage and terms status |
| `GET /search` | Paginated full-text/entity search with highlights |
| `GET /events/{id}` | Event, raw source references, diff and attribution |
| `GET /artifacts/{id}/appearances` | Paginated appearances, sorted only where ordering is justified |
| `GET /cases/{id}/graph` | Bounded graph plus omitted/aggregated counts |
| `GET /cases/{id}/questions` | Structured evidence-backed answers |
| `POST /reviews` | Local review decision with immutable audit record |
| `GET /cases/{id}/export` | Markdown or JSON evidence packet |

Performance targets to measure, not promise in advance: full wiki import and deterministic index build under 5 minutes on a typical 16 GB development laptop; selected-case graph under 2 seconds; ordinary search under 1 second after indexing. Record actual hardware and timings. Avoid sending full raw corpora to the browser.

Keep analysis offline by default. Do not execute embedded programs, render raw HTML, follow payload URLs automatically, or turn the backend into a URL-fetching proxy. Render corpus content as inert text, constrain decompression, and reject archive path traversal. These requirements follow directly from handling adversarial logs and payload corpora.

## 11. Evaluation: make it a research project

### A. Data correctness gates

Test meaningful failure cases:

- An unchanged paragraph across ten revisions produces one introduction, not ten adoptions.
- A restoration is distinguished from newly authored text.
- A missing base remains unknown rather than implicitly empty.
- The same name in different datasets does not automatically merge identities.
- Empty labels do not become one agent.
- A quoted claim is not attributed as an original claim by the editor.
- Overlapping timestamp intervals do not yield a fabricated directed chronology.
- Revisions and save events do not double-count the same underlying action.
- Similar boilerplate does not create a supported handoff.
- Every exported citation resolves to the exact source span and snapshot.

### B. Hand-reviewed evidence benchmark

Create a small annotation set of approximately 60 candidate relationships and 20 investigation questions across at least three bounded episodes if the data support that many. Include explicit references, plausible reuse, same-topic non-links, revision carryover, unknown identities, and unanswerable questions.

Have a human review labels. If two reviewers are available, independently double-label at least 20 relationships and adjudicate disagreements. Record both the relation semantics and whether the evidence supports them. Do not use the same LLM to generate all labels and declare its own predictions correct.

Split by episode/artifact family rather than random pairs from the same page, to reduce leakage. Use development episodes to adjust heuristics and leave at least one episode untouched until the final run. If limited data make this impossible, report the result as an in-sample pilot.

Compare:

1. Full-revision text search with chronological browsing.
2. Revision-aware search without the evidence graph.
3. SwarmScope with typed edges and evidence inspection.

This ablation tests whether improvements come from correct revision handling, the visual workflow, or both.

### C. Metrics

| Metric | Definition |
|---|---|
| Supported-edge precision | Human-supported edges divided by proposed edges in each relation/evidence tier; report counts and uncertainty. |
| Recoverable-link recall | Fraction of links found by exhaustive human review inside the small annotated episode that the method retrieves. Outside that scope, recall is unknown. |
| Answer accuracy | Correct source-supported answers out of the reviewed question set; grade abstentions separately. |
| False attribution count | Claims that wrongly assign origin, identity, receipt, or successful action. |
| Citation coverage/support | Fraction of factual clauses with resolving citations, and fraction whose citations actually support the clause. |
| Investigation time | Time to correctly answer a question using each interface. |
| Revision inflation | Difference between full-revision occurrence counts and counts after removing inherited carryover; call it occurrence inflation, not a direct estimate of false transmission. |

With 3–5 volunteer reviewers, use disjoint but comparable tasks and counterbalance condition order to reduce learning effects. Treat timings as exploratory usability results. Do not claim statistical generality from a small convenience sample.

Suggested acceptance goals: all exported citations resolve; no silent identity merges; no fabricated dates; at least one real case with reviewed evidence; and a target of at least 90% precision for the prominently displayed supported relation class. Report the observed numerator/denominator even if the target is missed. If precision is poor, narrow which relations appear by default rather than relabeling uncertain edges as established.

## 12. Build schedule and stop rules

| Window | Work | Exit condition |
|---|---|---|
| Hours 0–2 | Download, inspect schema/manifest, reconcile counts, select a page history | One real lineage rendered as a checked diff; acquisition audit written |
| Hours 2–6 | Immutable ingestion, text changes, URL/snippet extraction, full-text search | Search returns exact spans with revision provenance |
| Hours 6–12 | Timeline and evidence inspector | A researcher can investigate one case end to end |
| Hours 12–18 | Typed graph, conservative toggle, questionnaire, exports | Every edge explains itself; unsupported answers abstain |
| Hours 18–24 | Review examples, correctness gates, demo polish | One real case and one ambiguity/carryover example work offline |
| Hours 24–36, optional | Annotation set, ablation, usability pilot | Honest preliminary evaluation with reproducible inputs |
| Hours 36–48, optional | Second adapter or deeper case study | Add only if core evidence integrity and demo reliability hold |

If the schedule slips, cut model summaries, second datasets, animation, and automatic case discovery before cutting source provenance or revision handling. A reliable timeline with a strong evidence inspector is a valid fallback to an unfinished graph.

## 13. Deliverables and definition of done

Deliver:

- Runnable repository with pinned dependencies and a short start guide.
- Downloader/importer that records source snapshots and checksums.
- Working search, timeline, case graph, and source inspector.
- One reviewed case report plus one ambiguous/negative example.
- Exported Markdown and machine-readable JSON for each demonstrated case.
- Evaluation inputs, observed results, and stated limitations.
- A three-minute demo script and screenshots or recording if practical.
- A data audit distinguishing inspected data, missing data, and optional adapters.

The result is done when someone can start from a finding, inspect every supporting step, identify which actor labels and artifacts are involved, and understand why some apparent connections are not established.

Do not require a novel misconduct discovery to call the hackathon successful. A reproducible finding that common analysis methods overcount spread, or that a suspected handoff is unsupported, is useful if carefully demonstrated.

## 14. Follow-up research with the strongest upside

After the MVP, investigate **whether actionable workarounds propagate differently from warnings and corrections**. This connects the tool to monitoring and multi-agent safety, but requires additional annotation and ideally read/action observations.

On historical logs, compare observed references, reuse, transformations, and follow-up claims, with matched opportunities and explicit coverage caveats. Do not infer warning effectiveness from board availability alone.

For causal claims, create a separate controlled multi-agent experiment with benign synthetic tasks: randomize whether an agent receives a workaround, warning, correction, or neither; log delivery and subsequent behavior. Test whether the observational reconstruction recovers known communication paths under missing logs and alias changes. This would validate both the tool and stronger hypotheses about information flow. It is a separate project, not a prerequisite for the hackathon.

## 15. Immediate instructions to the coding agent

1. Read this brief and any repository instructions. Inspect the environment before choosing dependency versions.
2. Start with the wiki dataset. Do not wait for AI Village access or implement all adapters.
3. Inspect 20 varied revisions and at least one example of every available event type. Record schema and coverage problems.
4. Validate revision base/hunk semantics before extracting messages or building edges.
5. Implement one vertical slice: source revision → novel text → artifact appearance → typed relationship → clickable evidence.
6. Build a no-key deterministic mode first. Make any model layer optional and cached.
7. Maintain a visible distinction between observed facts, derived relationships, claims, and unknowns.
8. Select demo cases only after examining the records. Never invent real agent actions to fit the product story.
9. Implement the integrity gates and collect a small honest evaluation.
10. Finish with a runnable demo, evidence packet, and concise account of what remains uncertain.

## Sources

Source facts were checked during this planning pass. Counts describe the inspected release, not all activity that ever occurred. The implementation, evaluation design, and recommendation above are proposed work.

- **[S1] German-board download page:** [collusion.wiki/explorer/download](https://collusion.wiki/explorer/download). Public download inventory and counts; accessed directly after the search retriever failed to open this path.
- **[S2] Wiki publisher exports:** [manifest](https://collusion.wiki/explorer/download/manifest.json.gz), [revisions](https://collusion.wiki/explorer/download/revisions.jsonl.gz), [events](https://collusion.wiki/explorer/download/events.jsonl.gz), [labels](https://collusion.wiki/explorer/download/labels.jsonl.gz). Downloaded and inspected for this brief; the manifest explains populations and clock provenance.
- **[S3] SwarmTraces report:** [swarmtraces.org](https://swarmtraces.org/), especially its limitations section. Report published September 25, 2026. Dataset schema was not independently inspected.
- **[S4] SwarmTraces evidence viewer:** [swarmtraces.org/viewer](https://swarmtraces.org/viewer/). Existing evidence search and redacted dataset download entry point.
- **[S5] AI Village dataset card:** [aidigestorg/ai-village](https://huggingface.co/datasets/aidigestorg/ai-village). Access conditions, data inventory, behavioral caveats, and changelog guidance. Gated schema unavailable in this planning pass.
- **[S6] Transluce report:** [Early rogue AI agent activity and attempts to hack found on urlquery.net](https://transluce.org/agent-activity), published September 23, 2026.
- **[S7] Transluce downloadable archive:** [urlquery-agent-activity-2026-09-23.zip](https://transluce.org/data/urlquery-agent-activity-2026-09-23.zip). Inspected README, file inventory, and sample CSV; package directory is named `urlquery-agent-activity-2026-09-22-v5`.
- **[S8] Adjacent reporting interface:** [AI Agent Hotline](https://agenthotline.ai/). Reviewed as a complementary direction, not selected as the MVP.
