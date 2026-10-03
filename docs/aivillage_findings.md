# AI Village: what was actually checked

Checked 2026-10-03 against the local download in `data/raw/aivillage/` (the card's JSONL tables, not Parquet; the
`aivillage schema/text/slice` fetch commands target Parquet and do not apply to this dataset, so download with
`hf download` as in `docs/DATA.md`).

## Files and sizes (rows)
| File | Rows | Notes |
|---|---|---|
| events.jsonl.gz | 381,610 | `data` JSON has `actionType`; shape varies by type, so DuckDB schema inference fails (read `data` as JSON). `event_index` 5,839–441,395 with 19,131 gaps. |
| chat_messages.jsonl.gz | 183,485 | 173,493 agent, 9,992 human. |
| agent_memories.jsonl.gz | 246,151 | 6.8 GB of text; 46 labels; up to 34k memories per label. |
| computer_use_sessions.jsonl.gz | 78,362 | `session_goal` often holds long memory dumps. |
| agents / agent_goals / village_goals / chat_rooms / villages | 46 / 33 / 51 / 16 / 1 | The card says 31 agents; the file has 46 distinct names (and 46 distinct ids). |
| summaries.jsonl.gz | 939 | LLM-generated, flagged `generated`, excluded from artifact extraction. |
| village-transcript.json | 404 days, 375,426 events | Derived view of events+chat (no extra evidence). |

Not downloaded: `computer_use_turns`, `claude_code_*`, screenshot tars.

## Verified mappings
- Chat row ↔ event is 1:1 through `events.data.messageId`: all 173,493 AGENT_TALK events match a chat row. 9,992 of
  10,049 USER_TALK events match; the other 57 exist only in events and are loaded from the event (`av:evtalk:`).
  A chat row and its event are one action.
- `created_at` strings are naive UTC: they agree with the transcript's `Z` timestamps to ~0.25 s. The source gives no
  uncertainty, so no time bounds are derived. `event_index` is the source's own sequence; time order and
  `event_index` order disagree only once.
- Every `agentId`/`speakerId` resolves to an `agents` row. Human labels (`av:user:<uuid>`) carry names from
  `speakerName`/`USER_NAME_CHANGE`; empty names stay unknown.
- Memories and session goals carry text forward heavily (consecutive memories of the busiest label share ~83% of
  lines), so they are treated as lineage streams.

## Caveats
- The card describes 31 agents; labels in this release are 46.
- Gaps in `event_index` mean some events are missing from the release.
- No per-agent read logs and no action tables are loaded: "observed use" cannot be established yet.
