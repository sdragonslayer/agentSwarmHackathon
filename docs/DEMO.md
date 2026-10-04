# Demo script (about 3 minutes)

Run the app first: `uv run uvicorn backend.app.main:app --port 8765`, open http://127.0.0.1:8765/. The deep links
below jump straight to each case (they only work against the database built from the AI Village release; the
artifact ids are content hashes, so they are stable). All claims below are what the tool shows; none is a finding
about causation.

Screenshots of each beat are in `data/derived/results/figures/` (`demo1_…` to `demo5_…`, `app_overview`,
`report_light`, `report_dark`).

## 0:00 The problem (overview page, 20 s)
Open the overview. The hero number: **78.7% of 73.1M memory lines are carried forward unchanged** from the same label's
previous memory. Point at the occurrence-inflation chart: URLs appear **4.35M times in full text but only 655k times
in new text (6.6×)**. "If you count every memory as a new utterance, a string written once looks like it spread
hundreds of times."

## 0:20 A carryover case (25 s)
Link: `#case=art:url:64d52a40e249fbd6&item=@memory`
`https://animal-welfare-site-64148b.gitlab.io/guides.html` appears **767 times in 497 items but is written once by one
label**. In the inspector, the memory's lines are tagged *carried*. Take-away: counting full-text appearances
manufactures spread that doesn't exist. Carryover never crosses labels, so label-level counts are unaffected.

## 0:45 A real cross-label case with explicit text (50 s)
Link: `#case=art:url:79f9794fee7be0a6` (village-chronicle PR #3)
Opus 4.5 (Claude Code) announces the PR in chat; about 35 s later Claude Sonnet 4.6's memory records it ("OPENED …"); then
Opus 4.5 replies in chat, "Heads up, I already opened PR #3". Show:
1. Timeline lanes and links (solid = same exact string). Click a link: evidence tier `rule_derived`, undirected,
   and the competing explanations (common source such as the shared chat, shared prompt, independent discovery,
   carried memory).
2. Click the dots: the exact spans, with the label and recorded time.
3. **Conservative mode**: links whose order is not established by the source's own sequence drop out, and the page
   says how many were hidden. Memories have no event sequence, so ordering involving them stays unresolved.
Claim to make: *the string appears in both labels' new text and the order is recorded*; not *Sonnet learned it from Opus*.

## 1:35 What the text itself shows, and what it can't (35 s)
Link: `#case=art:url:b4dfd9556a079905&item=@memory` (a Google Doc link)
o3 posts a doc link; Claude Opus 4 says it tried the URL, suspects a typo and asks o3 to confirm; its later memory
lists the link as "(typo)". Open the questions: *earliest appearance* is **supported** with a cited span;
*did anyone claim to use it* and *is use independently observed* are **unknown**, because claim detection is not run
and the action tables are not loaded. "The tool abstains instead of guessing."

## 2:10 A shared resource is not a handoff (25 s)
Link: `#case=art:url:d4462f5456534de3` (github.com/ai-village-agents/basecamp)
Eight labels, 59 new-text items (426 occurrences in full text). Everyone uses the village's own repo, so a shared string is weak evidence. The
questions panel lists this as the likely competing explanation (widely shared, common source).

## 2:35 Evidence you can hand someone (25 s)
Click **Export Markdown**. Every statement carries an exact source span; limitations travel with each answer. Mention
the 8 integrity gates (`validate`), the 133-item human-review pack, and that precision numbers come from the review.

## Safe things to say
- "Author labels", not "agents". Counts are about text occurrences, not people.
- Similarity and shared strings never establish causation. Order is only as strong as the source's sequence.
- The cases are chosen for being inspectable, not representative.
