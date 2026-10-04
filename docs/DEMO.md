# Demo script (about 3 minutes)

Two datasets, two apps (each database is opened by one process at a time):

```powershell
uv run uvicorn backend.app.main:app --port 8765                                   # AI Village  http://127.0.0.1:8765/
$env:SWARMSCOPE_DB = "data/derived/wiki.duckdb"; uv run uvicorn backend.app.main:app --port 8766   # wiki  http://127.0.0.1:8766/
```

Deep links jump to a case (`#case=<artifact id>`; add `&item=@memory` to open an inspector, `&view=graph`, `&even=1`).
Artifact ids are content hashes, so they are stable for these releases. Everything below is what the tool shows; none of
it is a finding about causation. Screenshots of each beat are in `data/derived/results/figures/`.

## 0:00 The problem (AI Village overview, 20 s)
Open the AI Village overview. Hero: **78.7% of 73.1M memory lines are carried forward unchanged** from the same label's
previous memory. Chart: URLs appear **4.35M times in full text but only 655k times in new text (6.6×)**. "Count every
rewrite as a new utterance and a string written once looks like it spread hundreds of times."

## 0:20 The same trap on a wiki, and it hits label counts too (45 s)
Wiki app: `http://127.0.0.1:8766/#case=art%3Aurl%3A37841cb86f34d434` (a `proxymule.com` proxy URL for fetching a
`sec.gov` file). The case header says **26 labels have it in their revisions in full text, but only 8 wrote it**: saving a
revision inherits other labels' text, and a revision's label is the editor, not the author of every line. Overview
numbers: URLs shared across 2+ labels are **8,292 naively vs 3,485** counting only text a label actually wrote (2.4×).
Open the timeline: one label (Agent0MassCountyResearch) accounts for 15 of the 22 new-text revisions, posted on
different pages. Use **Even spacing** when events cluster, **Graph** for one arc per label.

## 1:05 A carryover case (20 s)
AI Village: `#case=art%3Aurl%3A64d52a40e249fbd6&item=@memory`. `animal-welfare-site-64148b.gitlab.io/guides.html`
appears **767 times in 497 items but is written once by one label**. The inspector tags each memory line *carried*.
Carryover never crosses labels on AI Village, so its label counts are unaffected (14,128 URLs in 2+ labels either way).

## 1:25 A real cross-label case with explicit text (45 s)
AI Village: `#case=art%3Aurl%3A79f9794fee7be0a6` (village-chronicle PR #3). Opus 4.5 (Claude Code) announces the PR in
chat; about 35 s later Claude Sonnet 4.6's memory records it ("OPENED …"); then Opus 4.5 replies "Heads up, I already
opened PR #3". Hover a dot: its links light up and the rest fade. Click a link: evidence tier `rule_derived`, undirected,
with the competing explanations (shared chat, shared prompt, independent discovery, carried memory). Toggle
**Conservative mode**: links whose order is not established by the source's own sequence drop out, and the page says how
many. Claim to make: *the string appears in both labels' new text and the order is recorded*; not *Sonnet learned it from Opus*.

## 2:10 Abstaining (25 s)
AI Village: `#case=art%3Aurl%3Ab4dfd9556a079905&item=@memory` (a Google Doc link). o3 posts it, Claude Opus 4 says it
tried it and suspects a typo, and its later memory lists it as "(typo)". In the questions panel, *earliest appearance* is
**supported** with a cited span, while *explicit references* and *warnings or corrections* are **unknown**: no detector is
run, and the tool says so instead of guessing.

## 2:35 Evidence you can hand someone (25 s)
Click **Export Markdown**. Every statement carries an exact source span and its limitations. Mention that 16 integrity
gates pass on the wiki and 10 on AI Village, including checks that fail when the data is deliberately corrupted, and
that precision numbers come from the 133-item human review pack (not yet scored).

## Safe things to say
- "Author labels", not "agents". Counts are about text occurrences, not people.
- Shared strings and similar wording never establish causation. Order is only as strong as the source's sequence.
- The cases are chosen for being inspectable, not representative.
