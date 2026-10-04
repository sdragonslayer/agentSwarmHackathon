# TODO

## Manual checks (you)
Needs a human; nothing here can be settled by the tool.
1. **Score the human review.** Open `data/derived/review/review_pack.html` (or give it to a second reviewer), export results,
   then `uv run python -m backend.analysis.review_score --results <file> --out data/derived/review/scores.md`. Put the
   numbers (precision with intervals, extraction precision, lineage agreement) into `docs/WRITEUP.md`, replacing the
   "not yet measured" sentence. Stop the app first (one process per database).
2. **Read the lead wiki cases yourself** before quoting them: `art:url:37841cb86f34d434` (proxymule), `…5927772e2c450d13`
   (`county.json?a=.txt`). Confirm they really are lists of proxy/mirror URLs for fetching `sec.gov/files/county.json` and
   that "26 labels in full text vs 8 who wrote it" holds in the Table view. The tool shows strings and labels, not intent.
3. **Data rights and terms.** AI Village research terms require attribution, forbid re-identification/training and ask to be
   notified on publication. Confirm what you may show (quoted corpus text, label names, screenshots) in a public write-up;
   redistribution rights for the wiki are unconfirmed. `data/derived/report*.html`, the review pack and
   `data/derived/results/figures/` contain corpus text and must not be published as-is.
4. **Check nothing from `data/` is in git.** The repo history has commits you made ("demo", "running tests on ai village"):
   run `git ls-files data .env` (should print nothing) and `git log --stat | findstr data/`.
5. **Ask or note the discrepancies:** the AI Village card says 31 agents, the release has 46 distinct agent labels; the wiki's
   `uncertainty_seconds` is always 1 and undocumented (we derive no time bounds because of it).
6. **Reproduce from scratch once.** The AI Village database was built incrementally while the code evolved (a schema
   migration added columns). Rebuild it end to end (`ingest.aivillage`, then `analysis.build`, about 2.5 h) and rerun
   `validate` to confirm the numbers in `docs/RESULTS.md` do not change.
7. **Check the app yourself:** `#case=` demo links in `docs/DEMO.md`, the search box (artifact hits, text hits, "Plot all
   hits"), Conservative mode, Even spacing, Graph, Export Markdown, and recording a review on a link.
8. **Refine the cue lexicon.** The collusion.wiki site could not be fetched in this session (access denied). Allow the domain or paste its description, then adjust `config/lexicon.toml` and rerun `build --steps cues`. Also review a sample of cue lines for precision (e.g. does "answer" mean a posted answer?).
9. **Check the experiment claims** in `docs/EXPERIMENTS.md` in the app's Topics & traces tab (heatmap cells, exchanges), and decide whether the short paraphrases of exchange content are fine to publish (corpus-text rights).
10. **Decide on the 3 `possible_reuse` rows** that the review-pack build added to the AI Village database (similarity
   retrieval is not exposed in the UI; they appear only in the review pack and exports). Delete them or keep them.

## Open work (code)
- Speed up artifact extraction (about 2 h on 6.8 GB): prefilter lines, skip inherited lines when counting, or move to SQL/Rust.
- Similarity retrieval (`candidates.py`) needs an inverted index on rare shingles before it is useful at scale.
- Cross-dataset exact-artifact matching (`same_content` across databases).
- Wiki: use the deletion/recreation relations and the probe events (page families are already used as topics).
- Run `cues`/`references` on AI Village (hours on 16M lines) or add a faster path; label mentions need a tokenizer for names with spaces.
- Cue precision study and a lexicon refined from collusion.wiki's own description; optional LLM claim extraction (verified quote spans).
- Node + React/Vite frontend (the static page in `backend/app/static/` is the current UI).
- Claim/use detection and `observed_use` (needs `computer_use_turns`; deliberately out of scope for now).
- Transluce and SwarmTraces adapters (see `docs/USAGE.md` §9 for the adapter recipe).
- LLM layer (budget ≤ $100): claim extraction with verified quote spans, edge adjudication. The tool must keep working with no key.

## Never cut
Provenance and revision handling; evidence semantics in `CLAUDE.md`.
