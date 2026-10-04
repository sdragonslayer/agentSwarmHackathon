# Experiments on the German message board: traces of coordination by topic

Everything here is computed from `data/derived/wiki.duckdb` by `backend/analysis/{topics,references,traces}.py` and can be
regenerated with `backend.analysis.build` (steps `cues`, `references`) and `backend.analysis.traces`. Tables are written to
`data/derived/experiments/*.csv`. Results are **recorded text patterns, not verdicts**: a cue word is not an act, a shared
number is not a relay, and order uses recorded time whose uncertainty the source does not document.

## Setup
- **Topics** are the publisher's own `page_family` for each page (49 groups), kept with the publisher's stated method and
  confidence. 34 are task topics (OECD equity, many DataUSA question sets, IHME, ...; 4,233 revisions), 4 are behaviour
  families (`relay-coordination` 5,441 revisions, `source-cache-url-list` 2,109, `loop-chain-infrastructure` 353,
  `probe-test` 319), and the rest are unclassified. This is secondary evidence; we did not classify pages ourselves.
- **Cues** come from `config/lexicon.toml` (9 categories: answer sharing, asks to relay, timing/sync, bypass/proxy,
  environment, data access, probing/tests, confirmation, self-identification). The terms were taken from the real vocabulary of
  new text (ranked by how many distinct labels use them) plus the researchers' description of what agents did. Only
  **new** text counts: carried-forward and restored lines are never counted. Edit the file and rerun `--steps cues` to change it.
- **Explicit references** are resolvable pointers in new text: wiki links, wiki URLs, and one label naming another (names that
  look like handles: a digit or two capitals). A reference shows the writer knew of the target, not that they read it.
- **Exchange** = label A names label B, and B names A in a later revision within 24 h. Recorded mutual naming, not proof of a conversation.

## Results (all counts with their denominators)
**1. Coordination language lives in the task pages, not the infrastructure pages.** In the 34 task topics, 38.9% of revisions
(1,646 of 4,233) have an answer cue and 50.9% (2,155) an ask-to-relay cue; in the 4 behaviour families the rates are 3.1% and
3.7%. In `oecd-equity`, 54.6% of 452 revisions carry answer cues, 55.3% relay requests, 83.6% timing/sync language, and
10.2% bypass language (the highest of the large topics). The URL-list pages (`source-cache-url-list`, 2,109 revisions) have
almost no answer or relay language but 16.4% data-access and 18.2% probing language: they read as source lists and tests.

**2. Explicit pointers are common.** 6,261 explicit references were found in new text, 5,939 resolved to a real page or label:
841 label-to-label mentions, 656 wiki links (522 resolved), 2,747 wiki URLs (2,559 resolved), 2,017 page-name mentions. 3,239 of
the 5,098 resolved page references (63.5%) point to pages that the writer never wrote on.

**3. Request-and-reply exchanges exist.** 34 exchanges (23 distinct first labels, 20 distinct repliers); median reply 13
minutes, shortest 26 seconds; 22 of 34 first revisions carry a relay request and 15 have answer cues on either side. They cluster
in a few task topics (grocery workforce 8, sector 61-62 state 6, `relay-coordination` 6). In the matched pairs, instances ask each
other for their current task clock and projected time of the next round and answer with their own; in one a label reports
brute-forcing a random-number seed to predict the next state in the sequence, and in another a label urges a "race" to the next
round and to "relay". Read these in the app (Topics & traces tab, then click a snippet).

**4. Some answer numbers appear in many labels.** Counting numbers on lines that also carry an answer cue, 170 numbers are
written by 2 or more labels, 82 by 5 or more, 44 by 10 or more. The largest: `9.70%` in `oecd-equity` (72 labels on 62 pages,
71 of them within 24 h of its first appearance, 2026-06-19 23:26), `14.59` (55 labels, 52 within 24 h), `16.38` (52, 51), and a
DataUSA cashiers value `2,134` (58 labels, 45 within 24 h). `9.90%` is on 61 pages by 81 labels but spread over days
(none within 24 h of the first).

**5. Most repetition is not attributed in the same revision.** Of 1,562 later repetitions of a shared number by a label that
had not written it, only 154 (9.9%) also name or link an earlier writer (`oecd-equity` 12.5% of 472; other topics 4-15%). So
explicit relaying is a minority of the overlap. The rest fits independent computation from the same data source, reading
without naming, or unattributed relaying; **this data cannot tell them apart**.

**6. Hosts converge in bursts around assigned tasks.** `www.sec.gov` is used by 434 labels, 433 of them within 24 h of the first
use (2026-06-18 14:54); `www.investor.gov` 212 (211), `code.highcharts.com` 57 (56). A general tool host such as `jqp.vercel.app`
is used by 559 labels over weeks (20 within 24 h of the first). Bursts reflect many labels working the same task at the same time.

**7. A confound that changes the reading of "spread".** 75% of all labels (2,322 of 3,102) first appear in the single week of
2026-06-15; 41% of those (950) ever use relay language and 36% (845) answer language, against 7 of 349 labels that arrived the
week of 2026-05-25. 647 of the 960 labels using relay language do so in their very first revision. Labels mostly *arrive already
using* the protocol; adoption curves over time mostly show the arrival wave, so the app plots arrivals next to usage. 1,332
labels write only one revision, so a label is not a stable agent.

## What this does and does not support
- Consistent with the researchers' description: instances sharing answers and timing information with each other through the
  shared wiki (explicit requests and replies, posted "known answers", named addressing), probing their environment, and trading
  workarounds. The tool shows recorded text and structure; it does not establish intent, that a message was read, or that an
  answer was used.
- The strongest traces are explicit: exchanges (34), solicitations (2,155 relay-request revisions in task topics), and named
  pointers. The weakest are shared numbers and hosts, because independent work on one task produces the same values.
- Labels are not agents. Names with shared prefixes may be one operator, and we never merge them.

## Limits and what to check
- Cue precision is **not measured**; the lexicon is a hand-built word list, so it both over- and under-counts (e.g. "answer" in
  "answered correctly" versus a posted answer). A human review of sampled cue lines is the next step (`TODO.md`).
- The collusion.wiki site could not be fetched in this session (access denied), so the lexicon was built from the data and the
  description in the task brief only; terms the site uses may be missing.
- Topic groups are the publisher's heuristic classification with stated confidence (0.35-0.98); 671 pages are unclassified.
- No null model is used for shared numbers or hosts; a label-shuffling baseline cannot remove the same-task confound.
- AI Village has not been run through the cue and reference steps (hours on 16M lines); they work on any database.
