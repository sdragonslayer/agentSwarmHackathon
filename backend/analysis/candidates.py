"""Possible-reuse candidates for one case: similarity retrieval, never a claim of transmission.

For each non-inherited appearance of a seed artifact, take the line it sits in (or the whole message for chat),
and retrieve at most K similar text from *other* author labels inside a time window, using word-shingle MinHash.
Common boilerplate is downweighted: a candidate must share at least MIN_RARE shingles that are rare in the pool.
Candidates become `possible_reuse` edges (rule_derived, undirected) with their evidence features and the standing
alternatives. Retrieval settings are recorded in `support` so results are reproducible.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

import duckdb
from datasketch import MinHash, MinHashLSH

from backend.analysis.edges import ALTERNATIVES

CANDIDATE_VERSION = "candidates-0.1"
SHINGLE_WORDS = 5
NUM_PERM = 64
LSH_THRESHOLD = 0.3
MAX_CANDIDATES = 20
WINDOW_DAYS = 2
MIN_RARE = 2
RARE_MAX_DF = 3
POOL_LIMIT = 60_000
MIN_WORDS = 8
WORD_RE = re.compile(r"\w+", re.UNICODE)


def shingles(text: str) -> set[str]:
    words = [w.lower() for w in WORD_RE.findall(text)]
    if len(words) < SHINGLE_WORDS:
        return set()
    return {" ".join(words[i:i + SHINGLE_WORDS]) for i in range(len(words) - SHINGLE_WORDS + 1)}


def _minhash(sh: set[str]) -> MinHash:
    m = MinHash(num_perm=NUM_PERM)
    for s in sh:
        m.update(s.encode("utf-8"))
    return m


def _temporal(a_idx, b_idx, a_ts, b_ts) -> str:
    if a_idx is not None and b_idx is not None and a_idx != b_idx:
        return "sequence_ordered"
    if a_ts is not None and b_ts is not None and a_ts != b_ts:
        return "timestamp_ordered_unbounded"
    return "unresolved"


def build_for_artifact(con: duckdb.DuckDBPyConnection, artifact_id: str) -> dict[str, int]:
    """(Re)create possible_reuse edges for one seed artifact."""
    con.execute("DELETE FROM evidence_edge WHERE artifact_id = ? AND relation = 'possible_reuse'", [artifact_id])
    seeds = con.execute(
        """
        SELECT a.item_id, a.actor_label_id, a.time_ts, e.event_index, a.line_no, t.kind, t.text
        FROM appearance a JOIN text_item t USING (item_id) LEFT JOIN event e ON e.event_id = a.event_id
        WHERE a.artifact_id = ? AND a.novelty IN ('standalone', 'first_observed', 'new', 'modified')
        """,
        [artifact_id],
    ).fetchall()
    if not seeds:
        return {"seeds": 0, "edges": 0}
    seed_units = []
    for item_id, actor, ts, idx, line_no, kind, text in seeds:
        unit = text.split("\n")[line_no] if kind == "memory" or kind == "session_goal" else text
        if len(WORD_RE.findall(unit)) >= MIN_WORDS:
            seed_units.append((item_id, actor, ts, idx, unit))
    times = [s[2] for s in seed_units if s[2] is not None]
    if not seed_units or not times:
        return {"seeds": len(seed_units), "edges": 0}
    # Pool: chat text and non-inherited memory/goal lines from any label within WINDOW_DAYS of some seed, in a
    # deterministic order so a truncated pool is reproducible (and reported, never silent).
    con.execute("CREATE OR REPLACE TEMP TABLE _seed_times AS SELECT unnest(?::TIMESTAMP[]) AS ts", [times])
    pool_rows = con.execute(
        f"""
        WITH near AS (
            SELECT DISTINCT t.item_id FROM text_item t JOIN _seed_times s
              ON t.time_ts BETWEEN s.ts - INTERVAL {WINDOW_DAYS} DAY AND s.ts + INTERVAL {WINDOW_DAYS} DAY
            WHERE t.kind IN ('chat_agent', 'chat_human', 'memory', 'session_goal') AND NOT t.generated
        )
        SELECT t.item_id, t.actor_label_id, t.time_ts, e.event_index, t.text, NULL AS line_no
        FROM near JOIN text_item t USING (item_id) LEFT JOIN event e ON e.event_id = t.event_id
        WHERE t.kind IN ('chat_agent', 'chat_human')
        UNION ALL
        SELECT c.item_id, t.actor_label_id, t.time_ts, NULL, c.text, c.line_no
        FROM near JOIN text_change c USING (item_id) JOIN text_item t USING (item_id)
        WHERE c.classification IN ('new', 'modified', 'first_observed')
        ORDER BY 3, 1, 6 LIMIT {POOL_LIMIT + 1}
        """
    ).fetchall()
    truncated = len(pool_rows) > POOL_LIMIT
    pool_rows = pool_rows[:POOL_LIMIT]
    pool = []
    for item_id, actor, ts, idx, text, line_no in pool_rows:
        sh = shingles(text)
        if sh:
            pool.append((item_id, actor, ts, idx, text, line_no, sh))
    df: Counter[str] = Counter()
    for *_, sh in pool:
        df.update(sh)
    lsh = MinHashLSH(threshold=LSH_THRESHOLD, num_perm=NUM_PERM)
    for i, (*_, sh) in enumerate(pool):
        lsh.insert(str(i), _minhash(sh))
    seed_items = {s[0] for s in seed_units}
    has_artifact = {
        r[0] for r in con.execute("SELECT item_id FROM appearance WHERE artifact_id = ?", [artifact_id]).fetchall()
    }
    n_edges = 0
    seen_pairs: set[tuple[str, str]] = set()
    for s_item, s_actor, s_ts, s_idx, unit in seed_units:
        s_sh = shingles(unit)
        if not s_sh:
            continue
        found = []
        for key in lsh.query(_minhash(s_sh)):
            p_item, p_actor, p_ts, p_idx, _, p_line, p_sh = pool[int(key)]
            if p_item == s_item or p_item in seed_items or p_item in has_artifact:
                continue  # same item, or exact-match territory already covered by same_content
            if p_actor is None or s_actor is None or p_actor == s_actor:
                continue
            rare = sorted(x for x in s_sh & p_sh if df[x] <= RARE_MAX_DF)
            if len(rare) < MIN_RARE:
                continue  # shared text is common boilerplate
            jac = len(s_sh & p_sh) / len(s_sh | p_sh)
            found.append((jac, p_item, p_ts, p_idx, p_line, rare[:5]))
        for jac, p_item, p_ts, p_idx, p_line, rare in sorted(found, key=lambda f: -f[0])[:MAX_CANDIDATES]:
            first, second = (s_item, p_item) if (s_ts, s_item) <= (p_ts or s_ts, p_item) else (p_item, s_item)
            if (first, second) in seen_pairs:
                continue
            seen_pairs.add((first, second))
            support = {
                "artifact_id": artifact_id, "seed_item": s_item, "candidate_item": p_item, "candidate_line_no": p_line,
                "jaccard_word_shingles": round(jac, 3), "shared_rare_shingles": rare,
                "settings": {"shingle_words": SHINGLE_WORDS, "num_perm": NUM_PERM, "lsh_threshold": LSH_THRESHOLD,
                             "window_days": WINDOW_DAYS, "max_candidates": MAX_CANDIDATES, "min_rare": MIN_RARE,
                             "rare_max_df": RARE_MAX_DF},
            }
            eid = "edge:" + hashlib.md5(f"{first}|{second}|{artifact_id}|possible_reuse".encode()).hexdigest()
            con.execute(
                "INSERT INTO evidence_edge VALUES (?, ?, ?, 'possible_reuse', 'rule_derived', ?, ?, ?, ?, FALSE, ?)",
                [eid, first, second, artifact_id, json.dumps(support),
                 _temporal(s_idx, p_idx, s_ts, p_ts), json.dumps(ALTERNATIVES), CANDIDATE_VERSION],
            )
            n_edges += 1
    return {"seeds": len(seed_units), "pool": len(pool), "pool_truncated": truncated, "edges": n_edges}
