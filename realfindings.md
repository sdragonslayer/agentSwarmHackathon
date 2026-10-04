# SwarmScope: evidence for the real-data findings

Every number below is tagged with the dataset it came from:

- **[Wiki]** the German message board export from collusion.wiki (14,591 revisions of 4,579 pages; `data/derived/wiki.duckdb`).
- **[AIV]** the AI Village text tables (246,151 agent memories and 78,361 session goals; `data/derived/swarm.duckdb`).

Each section names the file or app view that holds the number. The CSV paths are under `data/derived/`, which is not in git, so
you regenerate them with the commands in `README.md` (`build`, then `export_results` and `traces`). The tables carry author labels
and artifact ids but no corpus text. "Label" means an author label as recorded, not a verified agent. All figures count recorded
text and are pattern matches (word lists, exact names, exact strings), not confirmed acts. Nothing here is a measured precision.

Some figures come from the write-up `docs/FINDINGS.md` and are not in the CSVs; the table of sources at the end says which.

---

## 1. Most text is carried forward or restored, not newly written

Terms. *Carried forward*: the line is already in the immediately preceding version of the same page (Wiki) or the same label's
memory stream (AIV). *Restored*: not in the previous version, but in an earlier one. Neither is new writing.
Source: `results_wiki/lines_by_stream.csv`, `results/lines_by_stream.csv`.

| Dataset | Stream | Items | Lines | Carried forward | New | Restored | Carried share |
|---|---|---|---|---|---|---|---|
| Wiki | page revisions | 14,591 | 185,849 | 80,316 | 58,896 | 46,637 | **43.2%** |
| AIV | agent memories | 246,151 | 73,107,754 | 57,513,372 | 14,444,120 | 1,150,262 | **78.7%** |
| AIV | session goals | 78,361 | 450,524 | 89,877 | 353,049 | 7,598 | 19.9% |

- Wiki: the three columns sum exactly to the line total (80,316 + 58,896 + 46,637 = 185,849). The "New" column holds new, edited and
  first-seen lines together (31.7%); restored is 46,637 / 185,849 = **25.1%**.
- Wiki: one page, `WillkommenImWiki` (2,327 revisions), holds 41,872 of the 46,637 restored lines (89.8%). It is an edit-war
  page that cycles between versions. (From `docs/FINDINGS.md` §1; check on the page in the Wiki app.)
- AIV carryover stays inside one label, since memories are per label.

**Check:** run `uv run python -m backend.analysis.validate`; one gate recomputes inherited counts independently in SQL on 200
sampled pairs (0 mismatches on both datasets, per `docs/TECHNICAL.md` §11).

## 2. Counting every occurrence overstates how often things appear

Full = all text; novel = only text newly written. Source: `results_wiki/inflation_by_artifact_type.csv`,
`results/inflation_by_artifact_type.csv`.

| Dataset | Artifact | Distinct | Full occurrences | Novel occurrences | Inflation |
|---|---|---|---|---|---|
| Wiki | URL | 23,561 | 115,837 | 42,916 | **2.70×** |
| Wiki | commit-like id | 1,913 | 14,531 | 2,209 | **6.58×** |
| AIV | URL | 57,574 | 4,348,513 | 654,798 | **6.64×** |
| AIV | commit-like id | 82,640 | 4,946,145 | 1,167,001 | **4.24×** |
| AIV | repo reference | 251 | 2,112 | 864 | 2.44× |

The most inflated Wiki URLs are 220 occurrences in 220 revisions but one novel occurrence each
(`results_wiki/most_inflated_artifacts.csv`; the top entries are `wiki.cgi` links to the page `WillkommenImWiki`, ids such as
`art:url:e7dd9da162d951cc`). **Not shown:** that the surplus is false transmission; it is an occurrence count.

## 3. On the Wiki, saving a revision also inflates who appears to share what

Labels with the artifact in two or more labels' revisions, counting all text vs only text the label wrote.
Source: same two inflation CSVs, columns `in_2plus_labels_full` and `in_2plus_labels_novel`.

| Dataset | Artifact | Labels sharing, all text | Labels sharing, new text only | Ratio |
|---|---|---|---|---|
| Wiki | URL | 8,292 | 3,485 | **2.4×** |
| Wiki | commit-like id | 316 | 88 | 3.6× |
| AIV | URL | 14,128 | 14,128 | 1.0× |
| AIV | commit-like id | 20,845 | 20,845 | 1.0× |

The AIV rows are equal because a memory only inherits from its own label, so carryover cannot make a second label look like a
sharer. That difference is itself the evidence that the Wiki effect comes from saving a revision that inherits other labels' text.

Worked cases (Wiki, from `docs/FINDINGS.md` §3 and §9; open each id in the Wiki app, then Table view):
- `art:url:37841cb86f34d434`, a proxy URL for fetching a `sec.gov` file: present in the revisions of **26** labels, written in new
  text by **8**.
- `art:url:6e4c9559b2be68b9`, a `jqp.vercel.app` URL: written **once** (page `WillkommenImWiki`, revision 1545, 2026-06-18 21:02)
  and present in 220 revisions in all (the one that wrote it plus 219 that inherited it) across 8 labels.
- `art:url:5927772e2c450d13`: 8 labels wrote it in 15 revisions.

## 4. Coordination language concentrates in task pages  [Wiki]

Share of revisions whose new text matches the cue word list (`config/lexicon.toml`). Topics are the publisher's own page
families, not ours. Source: `experiments/topic_summary.csv` and `experiments/topic_by_cue_matrix.csv`; the Topics & traces tab shows
the same matrix and lets you click a cell for examples.

Infrastructure families (4: `relay-coordination`, `source-cache-url-list`, `loop-chain-infrastructure`, `probe-test`) total 8,222
revisions, and their cue counts below reproduce exactly from `topic_summary.csv`. The doc's task-topic group is 34 topics, 4,233
revisions; summing the topic rows that are neither infrastructure nor unclassified gives 42 topics, 4,267 revisions and cue counts
within about 1% (answer 1,655, relay 2,171, timing 3,030, bypass 119), so the exact task-topic grouping was not reproduced here.

| Cue | Task topics | Infrastructure families |
|---|---|---|
| Answer sharing | 38.9% (1,646) | 3.1% (258) |
| Ask to relay | 50.9% (2,155) | 3.7% (308) |
| Timing / clock sync | 70.9% (3,001) | 4.9% (402) |
| Bypass / proxy | 2.8% (119) | 3.8% (310) |

Row-level evidence from `topic_summary.csv` (counts are revisions with the cue):

| Topic | Revisions | Answer sharing | Ask to relay | Timing | Bypass |
|---|---|---|---|---|---|
| `oecd-equity` | 452 | 247 | 250 | 378 | 46 |
| `datausa-grocery-workforce` | 349 | 137 | 166 | 238 | 2 |
| `datausa-cashiers-masters` | 327 | 185 | 178 | 287 | 7 |
| `datausa-sector61-state` | 322 | 146 | 181 | 259 | 4 |
| `relay-coordination` (infrastructure) | 5,441 | 254 | 308 | 400 | 204 |
| `source-cache-url-list` (infrastructure) | 2,109 | 4 | none | 1 | 102 |
| `loop-chain-infrastructure` (infrastructure) | 353 | none | none | none | 1 |

`oecd-equity`: 247 of 452 is 54.6% for answer cues, 250 of 452 is 55.3% for relay requests, 378 of 452 is 83.6% for timing.
The URL-list pages (`source-cache-url-list`, 2,109 revisions) have almost no answer or relay words, and read as source lists and
tests (345 data-access and 384 probing hits in the same row). **Not shown:** that a cue word means the author did that thing.

## 5. Labels name each other, and some reply  [Wiki]

Source: `experiments/exchanges.csv` (one row per exchange: both labels, both revision ids, cues on each side, seconds to reply, topic)
and `experiments/topic_summary.csv` (columns `exchanges`, `label_mentions`, `refs_to_pages_never_written_by_author`).

- 6,261 explicit references found in new text; 5,939 resolved to a real page or label. Found / resolved by type (from the `reference`
  table): label mentions 841 / 841, wiki links 656 / 522, wiki URLs 2,747 / 2,559, page-name mentions 2,017 / 2,017. The 5,098
  resolved page references (all types except label mentions) are the base for the 63.5%: 3,239 of them point at pages the writer
  never wrote on (the sum of `refs_to_pages_never_written_by_author` in `topic_summary.csv` is 3,239).
- **34 request-and-reply exchanges**: label A names B in a revision, then B names A in a later revision within 24 hours. Median
  reply 13 minutes, shortest 26 seconds. The 26-second one is in `exchanges.csv` (topic `datausa-grocery-workforce`,
  revisions `wiki:rev:dse~DataUSAGrocerySequenceCollabOct22@7` and `@8`; the first carries request-relay, timing and
  environment cues, the reply carries request-relay and environment cues).
- In 22 exchanges the first revision carries a relay request; in 15, answer cues appear on either side. They cluster in a few topics
  (grocery workforce 8, sector 61-62 state 6, `relay-coordination` 6).
- Content of the replies (from `docs/FINDINGS.md` §5, read in the app by clicking a snippet in Mutual-naming exchanges): instances
  ask each other for their current task clock and the projected time of the next round; in one, a label reports brute-forcing a
  random-number seed over the 50-state list to predict the next state; in another, a label urges a "race" to the next round.
- **Not shown:** that either side read the other's text, or that an answer was used. This is recorded mutual naming.

## 6. Shared answers are widespread, mostly unattributed  [Wiki]

Numbers written on lines that also carry an answer word. Source: `experiments/answer_numbers.csv` and
`experiments/answer_provenance.csv`.

- 170 numbers are written by two or more labels, 82 by five or more, 44 by ten or more (`docs/FINDINGS.md` §6).
- Largest, from `answer_numbers.csv` (labels who wrote it / how many other labels wrote it within 24 hours of the first):

| Number | Topic | Labels | Within 24 h of first | Pages |
|---|---|---|---|---|
| `9.70%` | `oecd-equity` | 72 | 71 | 62 |
| `14.59` | `oecd-equity` | 55 | 52 | 50 |
| `16.38` | `oecd-equity` | 52 | 51 | 50 |
| `2,134` | `datausa-cashiers-masters` | 58 | 45 | 46 |

  The first appearance of `9.70%` is 2026-06-19 23:26:04.
- Attribution. From `answer_provenance.csv`: of 1,562 later repetitions by labels that had not written the number, **154 (9.9%)**
  also name or link an earlier writer. By topic: `oecd-equity` 59 of 472 (12.5%), `datausa-cashiers-masters` 27 of 275
  (9.8%), `datausa-poverty-county` 3 of 85 (3.5%), `datausa-language-french` 7 of 114 (6.1%), and `nyc-veterans` 0 of 34.
- **The data cannot separate relaying from independent computation of the same published value**, since the same number is the
  correct answer to the same question for everyone.

## 7. Hosts converge in bursts around assigned tasks  [Wiki]

Source: `experiments/host_adoption.csv` (first label and time, number of labels, how many started within 24 h of the first).

| Host | Labels | Within 24 h of first | First seen |
|---|---|---|---|
| `www.sec.gov` | 434 | 433 | 2026-06-18 14:54 |
| `www.investor.gov` | 212 | 211 | 2026-06-18 16:46 |
| `code.highcharts.com` | 57 | 56 | 2026-06-18 16:45 |
| `jqp.vercel.app` (general tool host) | 559 | 20 | 2026-05-28 12:28 |

Bursts reflect many labels working one task at one time; they are a resource count, not a link between labels. The
`jqp.vercel.app` row shows the opposite pattern: 559 labels over weeks, only 20 near the start.

## 8. A confound found in our own first analysis  [Wiki]

A plot of cumulative labels using relay language showed a vertical step in mid-June. It is mostly an arrival wave.
Figures from `docs/FINDINGS.md` §8 (computed by `analysis/traces.py`, "arrivals vs usage"; the Overview/Topics tab plots it):

- 2,322 of 3,102 labels (**75%**) first appear in the week of 2026-06-15.
- Of those, 41% use relay language and 36% use answer language, against 7 of 349 labels that arrived the week of 2026-05-25.
- 647 of the 960 relay-language labels use it in their very first revision, so they arrived already using it; it did not spread to
  existing labels.

The app now draws arrivals beside usage and prints this caveat next to every burst or shared-number result.

## 9. Integrity checks behind the numbers

- Wiki: 16 gates on the real data; AIV: 10 generic gates; all passing (`uv run python -m backend.analysis.validate ...`).
- Wiki raw-file checks: `sha256(body.encode('latin-1')) == body_sha256` for all 14,591 rows; hunks match the `\n`-split line
  counts; every save event links to exactly one revision; counts reconcile with the publisher's manifest.
- 10,000 sampled appearance spans on real data resolve to exact source text.
- 81 offline tests on synthetic data, including corruption tests that must fail.

---

## Where each figure comes from

| Section | Source |
|---|---|
| 1, 2, 3 (tables) | `data/derived/results_wiki/*.csv`, `data/derived/results/*.csv` (checked directly) |
| 1 (`WillkommenImWiki`), 3 (worked ids), 5 (reference counts, exchange stats), 8 (arrival and relay-label counts) | recomputed from `wiki.duckdb` (read-only) and matched; the reference breakdown and the "220 later revisions" wording were corrected |
| 4 (task-topic row of the cue table), 5 (reply content) | `docs/FINDINGS.md`; task-topic grouping not exactly reproduced, reply content read in the app only |
| 4 (infrastructure and per-topic rows), 5 (exchange row), 6 (170/82/44, 1,562, 154, tables), 7 | `data/derived/experiments/*.csv` (checked directly) |
| 9 | `docs/TECHNICAL.md` §11 |

## What this does not show

- Not "collusion proved". Cues, references and exchanges are consistent with answer, timing and workaround sharing between
  instances through a shared wiki, not with intent, reading or use.
- Not "this URL spread from A to B". `same_content` links are undirected and carry competing explanations.
- Not agent counts. Labels are not agents.
- Not a measured precision. The human-review packs are not yet scored, so every rate is a pattern-match rate.
