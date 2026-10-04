"""Run the derived-table pipeline over an ingested database.

    uv run python -m backend.analysis.build --db data/derived/swarm.duckdb [--steps lineage artifacts edges]
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from backend.db import DEFAULT_DB, connect

STEPS = ("lineage", "artifacts", "edges", "cues", "references")


def run(db: Path, steps: tuple[str, ...] = STEPS) -> dict[str, dict]:
    from backend.analysis import artifacts, edges, lineage, references, topics

    con = connect(db)
    mods = {"lineage": lineage, "artifacts": artifacts, "edges": edges, "cues": topics, "references": references}
    out = {}
    for step in steps:
        t0 = time.time()
        res = mods[step].build(con)
        res["seconds"] = round(time.time() - t0, 1)
        out[step] = res
        print(f"[{step}] {res}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--steps", nargs="+", choices=STEPS, default=list(STEPS))
    args = ap.parse_args()
    run(args.db, tuple(args.steps))


if __name__ == "__main__":
    main()
