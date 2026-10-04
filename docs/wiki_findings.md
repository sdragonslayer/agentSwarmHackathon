# German message board (collusion.wiki): what was checked and what it shows

Local copy: `data/raw/full-wiki-logs/` (uncompressed JSONL). Checked 2026-10-03. Build with
`uv run python -m backend.ingest.wiki` then `uv run python -m backend.analysis.build --db data/derived/wiki.duckdb`
(about 3 s + 8 s). Validate with
`uv run python -m backend.analysis.validate --db data/derived/wiki.duckdb --raw data/raw/full-wiki-logs` (16 gates).

## The release
`revisions.jsonl` 14,591 rows; `events.jsonl` 19,913 rows (14,591 save, 5,217 delete, 101 probe, 4 revert);
`labels.jsonl` 3,103 rows; `pages.jsonl` 4,579 rows; `manifest.json` generated 2026-09-03T03:42:36Z, cut
`revision.write_date >= 2026-05-01`. `revisions.jsonl` and `events.jsonl` hash to the values in the brief, and all five
files match the release's own `SHA256SUMS`. The manifest warns that save/delete/revert/probe populations overlap, so the
19,913 physical event rows are not 19,913 incidents; we never sum them.

## Conventions verified against the real data (this discharges the "validate hunk offsets" rule)
- **Body hash.** `body` holds the raw bytes one character per byte. `sha256(body.encode('latin-1'))` equals
  `body_sha256` for all 14,591 rows. A UTF-8 hash of `body` fails for exactly the 251 rows with `body_encoding`
  `utf8` (250) or `latin1` (1). The adapter decodes by the documented encoding (utf8/ascii: bytes as UTF-8;
  latin1: kept) and stores that text; the source hash is kept and re-checked after load (`source_sha256`).
- **Hunks.** Lines are split on `\n` (not `splitlines`). Offsets are 0-based and half-open. For all 10,012
  revisions with a base, the text between hunks is identical in base and new text; `lines` equals the `\n`-split
  count for all 14,591. We do not build on hunks (lineage compares bodies); the check just proves the convention.
- **Lineage.** `diff_base` is always the immediate predecessor in the same page (10,012 of 10,012). Each page's first
  revision has none: 4,562 are `page_created` (whole text is new, complete history) and 17 are
  `earlier_revisions_not_published` (history before the cut is missing: incomplete lineage). `seq` has gaps because of the cut.
- **Events.** Every save event links to exactly one revision (14,591 distinct `revision_ref`) with the same time, so a
  save and its revision are one action.
- **Clock.** `time_grade` reqlog 14,482 / rclog 103 / write_date 6; `winning_clock` is always `revision.pref_ts`;
  `uncertainty_seconds` is always 1. The manifest never defines that field, so it is stored verbatim in
  `clock_provenance` and no time bounds are derived. `archived_at` is never used as action time.
- **Authors.** 899 revisions have a blank `label` (the published labels file has a matching blank entry). They stay
  unknown author (NULL), never one shared author. `ip16` is not a label and is not merged into anything.
  `labels.jsonl` 3,103 = 3,102 named labels + the blank entry. A label on a revision identifies the *editor*, not the
  author of every sentence the revision still contains.

## Results (all numbers are counts of text occurrences in this release)
- 185,849 non-blank lines across 14,591 revisions: **43.2% carried forward** from the previous revision, **25.1%
  restored** (reappear after removal), 31.7% new, edited or first-seen. One page, `WillkommenImWiki`, has 2,327
  revisions and 41,872 of the 46,637 restored lines (89.8%).
- **Occurrence inflation:** URLs 115,837 occurrences in full text vs 42,916 in new text (**2.7×**); hex ids
  14,531 vs 2,209 (**6.6×**).
- **Label-level spread IS inflated here (unlike AI Village).** Artifacts that appear in revisions saved by 2 or more
  labels: URLs 8,292 in full text vs 3,485 when only text a label actually wrote counts (**2.4×**); hex ids 316 vs 88
  (**3.6×**). Reason: saving a revision inherits other labels' text. Example: a `proxymule.com` proxy URL for fetching
  a `sec.gov` file appears in the revisions of **26** labels, but only **8** labels wrote it.
- 12,774 `same_content` edges (12,571 URL, 203 hex id), all undirected and rule-derived. None is `sequence_ordered`:
  the wiki has per-page revision order but no cross-page source sequence, so cross-page order is only
  `timestamp_ordered_unbounded` (recorded time, clock uncertainty unknown).
- Time to process: ingest 3 s, lineage 1.6 s, artifacts 5 s, edges 0.2 s, validation about 10 s.
- Lead cases (inspect in the app): a list of proxy/mirror URLs for fetching `https://www.sec.gov/files/county.json`
  (8 labels wrote it in new text; one label, `Agent0MassCountyResearch`, posted it in 15 revisions of different
  pages), `https://www.sec.gov/files/county.json?a=.txt` (8 labels, 15 revisions), and a one-label carryover case
  (220 revisions contain a URL written once).

## Caveats
- These are shared strings in revisions, not proof that one label read or copied another's text; the same page can
  be read by every label, and agents may share prompts. The questionnaire lists these alternatives for every case.
- Many revisions are automated or repetitive posts (one label saved the same list on many pages), so item counts
  overstate independent writing; label-level and new-text counts are the safer measures.
- Precision of edges and extractions is not measured yet (no human review of the wiki output).
- Not used: delete, probe and revert events beyond loading them, page-family labels, and the deletion-response notes.
