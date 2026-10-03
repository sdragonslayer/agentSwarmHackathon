"""DuckDB schema for SwarmScope.

Source records are immutable: ingest tables (snapshot, actor_label, event, text_item) are written once per
snapshot. Derived tables (text_change, lineage_summary, artifact, appearance, evidence_edge, ...) carry
`detector_version` and can be dropped and rebuilt without touching source data.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

DEFAULT_DB = Path("data/derived/swarm.duckdb")

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
    snapshot_id VARCHAR PRIMARY KEY,
    source VARCHAR NOT NULL,
    retrieved_at VARCHAR,
    importer_version VARCHAR NOT NULL,
    files JSON,
    terms VARCHAR,
    coverage_notes VARCHAR
);

-- An author label as it appears in the source. Never an asserted real-world agent; never auto-merged.
CREATE TABLE IF NOT EXISTS actor_label (
    label_id VARCHAR PRIMARY KEY,          -- namespaced: av:agent:<uuid>, av:user:<uuid>
    snapshot_id VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,                 -- agent | human
    display_name VARCHAR,                  -- latest name seen; NULL/empty means unknown
    model_string VARCHAR,
    first_seen TIMESTAMP,
    last_seen TIMESTAMP,
    identity_status VARCHAR NOT NULL DEFAULT 'unverified_label'
);

CREATE TABLE IF NOT EXISTS actor_label_name (
    label_id VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    first_seen TIMESTAMP,
    last_seen TIMESTAMP,
    n BIGINT
);

-- Every source event. Times are verbatim source strings plus a parsed timestamp; bounds stay NULL because
-- the source gives no uncertainty for them. event_index is the source's own sequence order.
CREATE TABLE IF NOT EXISTS event (
    event_id VARCHAR PRIMARY KEY,          -- av:ev:<uuid>
    snapshot_id VARCHAR NOT NULL,
    event_index BIGINT,
    kind VARCHAR NOT NULL,
    actor_label_id VARCHAR,                -- NULL = unknown
    room_id VARCHAR,
    session_id VARCHAR,
    source_time VARCHAR,
    time_ts TIMESTAMP,
    clock_provenance VARCHAR,
    time_lower TIMESTAMP,
    time_upper TIMESTAMP,
    input_tokens BIGINT,
    output_tokens BIGINT,
    cost BIGINT,
    source_file VARCHAR,
    source_id VARCHAR
);

-- Every piece of utterance-like source text, one row per source record.
CREATE TABLE IF NOT EXISTS text_item (
    item_id VARCHAR PRIMARY KEY,           -- av:chat:<uuid>, av:mem:<uuid>, ...
    snapshot_id VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    actor_label_id VARCHAR,
    event_id VARCHAR,
    room_id VARCHAR,
    session_id VARCHAR,
    source_time VARCHAR,
    time_ts TIMESTAMP,
    text VARCHAR NOT NULL,
    text_sha256 VARCHAR NOT NULL,
    text_len BIGINT NOT NULL,
    generated BOOLEAN NOT NULL DEFAULT FALSE,   -- LLM-written secondary material (summaries)
    stream_key VARCHAR,                    -- items in the same stream carry text forward (lineage)
    source_file VARCHAR,
    source_table VARCHAR,
    source_id VARCHAR
);

-- Derived: non-inherited spans of items that sit in a lineage stream.
CREATE TABLE IF NOT EXISTS text_change (
    item_id VARCHAR NOT NULL,
    base_item_id VARCHAR,                  -- inferred predecessor in the stream; NULL when none observed
    line_no INTEGER NOT NULL,
    text VARCHAR NOT NULL,
    classification VARCHAR NOT NULL,       -- new | modified | restored | first_observed
    similarity DOUBLE,                     -- only for modified; rapidfuzz ratio vs closest base line
    attribution_basis VARCHAR NOT NULL,
    detector_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS lineage_summary (
    item_id VARCHAR PRIMARY KEY,
    stream_key VARCHAR NOT NULL,
    base_item_id VARCHAR,
    lineage_status VARCHAR NOT NULL,       -- first_in_stream (incomplete lineage) | inferred_predecessor
    n_lines INTEGER NOT NULL,
    n_inherited INTEGER NOT NULL,
    n_new INTEGER NOT NULL,
    n_modified INTEGER NOT NULL,
    n_restored INTEGER NOT NULL,
    n_first_observed INTEGER NOT NULL,
    detector_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS artifact (
    artifact_id VARCHAR PRIMARY KEY,       -- art:<type>:<sha1 of raw>
    artifact_type VARCHAR NOT NULL,        -- url | commit_sha | pr_ref | ...
    raw VARCHAR NOT NULL,                  -- exact string as it appeared first
    normalized VARCHAR NOT NULL,
    extraction_version VARCHAR NOT NULL
);

-- One row per appearance in non-inherited text; inherited carryover is only counted in artifact_counts.
CREATE TABLE IF NOT EXISTS appearance (
    artifact_id VARCHAR NOT NULL,
    item_id VARCHAR NOT NULL,
    actor_label_id VARCHAR,
    event_id VARCHAR,
    time_ts TIMESTAMP,
    line_no INTEGER,
    span_start INTEGER,
    span_end INTEGER,                      -- span offsets index into text_item.text of item_id
    novelty VARCHAR NOT NULL,              -- standalone | first_observed | new | modified | restored
    role VARCHAR NOT NULL DEFAULT 'unknown',    -- mention | use | claim | unknown
    review_status VARCHAR NOT NULL DEFAULT 'extracted',
    extraction_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS artifact_counts (
    artifact_id VARCHAR PRIMARY KEY,
    full_occurrences BIGINT NOT NULL,      -- every occurrence in every item, inherited text included
    novel_occurrences BIGINT NOT NULL,     -- occurrences in non-inherited text only
    full_items BIGINT NOT NULL,
    novel_items BIGINT NOT NULL,
    full_labels BIGINT NOT NULL,
    novel_labels BIGINT NOT NULL,
    extraction_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_edge (
    edge_id VARCHAR PRIMARY KEY,
    src_item_id VARCHAR NOT NULL,
    dst_item_id VARCHAR NOT NULL,
    relation VARCHAR NOT NULL,             -- same_content | possible_reuse | references | ...
    evidence_tier VARCHAR NOT NULL,        -- source_recorded | rule_derived | model_proposed | human_reviewed
    artifact_id VARCHAR,
    support JSON,                          -- spans / record ids backing the edge
    temporal_status VARCHAR NOT NULL,      -- sequence_ordered | timestamp_ordered_unbounded | unresolved
    alternatives JSON,
    directed BOOLEAN NOT NULL DEFAULT FALSE,
    detector_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS review (
    review_id VARCHAR PRIMARY KEY,
    edge_id VARCHAR NOT NULL,
    decision VARCHAR NOT NULL,             -- accept | reject | uncertain
    rationale VARCHAR,
    reviewer VARCHAR,
    created_at VARCHAR NOT NULL
);
"""


def connect(path: str | Path = DEFAULT_DB, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = Path(path)
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path), read_only=read_only)
    # Disk budget: the whole project's new data must stay well under 20 GB, so bound query spill files.
    con.execute("SET max_temp_directory_size = '4GB'")
    if not read_only:
        con.execute(SCHEMA)
    return con


def reset_derived(con: duckdb.DuckDBPyConnection, *tables: str) -> None:
    for t in tables:
        con.execute(f"DELETE FROM {t}")
