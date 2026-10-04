"""Score human review results against the system's claims.

    uv run python -m backend.analysis.review_score --key data/derived/review/review_key.json \\
        --results data/derived/review/review_results_AB.json [more result files] [--out data/derived/review/scores.md]

Edge precision is the share of sampled links a reviewer marked "accept"; "uncertain" counts as not supported and is
also reported on its own. Every rate is reported with its numerator, denominator and a Wilson 95% interval, because
these samples are small. With two or more reviewers, simple agreement per section is reported too.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - m), min(1.0, c + m))


def fmt(k: int, n: int) -> str:
    if n == 0:
        return "n/a (0 reviewed)"
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {100 * k / n:.0f}% (95% CI {100 * lo:.0f}-{100 * hi:.0f}%)"


def load_results(paths: list[Path]) -> list[dict]:
    out = []
    for p in paths:
        d = json.loads(p.read_text(encoding="utf-8"))
        out.append({"reviewer": d.get("reviewer") or p.stem, "results": d["results"]})
    return out


def score(key: dict, reviews: list[dict]) -> tuple[dict, str]:
    items = {i["id"]: i for i in key["items"]}
    tallies: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # name -> [hits, n]
    extra: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for rv in reviews:
        for iid, r in rv["results"].items():
            it, a1 = items.get(iid), r.get("a1")
            if it is None or not a1:
                continue
            sec = it["section"]
            if sec == "edge":
                name = f"{it['relation']} / {it['artifact_type']}"
                tallies[name][1] += 1
                tallies[name][0] += a1 == "accept"
                tallies[f"{it['relation']} (all types)"][1] += 1
                tallies[f"{it['relation']} (all types)"][0] += a1 == "accept"
                tallies[f"{it['relation']} / order {it['temporal_status']}"][1] += 1
                tallies[f"{it['relation']} / order {it['temporal_status']}"][0] += a1 == "accept"
                extra[f"{it['relation']}: marked uncertain"][1] += 1
                extra[f"{it['relation']}: marked uncertain"][0] += a1 == "uncertain"
                if r.get("a2"):
                    extra[f"{it['relation']}: text shows handoff (explicit)"][1] += 1
                    extra[f"{it['relation']}: text shows handoff (explicit)"][0] += r["a2"] == "explicit"
            elif sec == "extraction":
                name = f"extraction precision / {it['artifact_type']}"
                tallies[name][1] += 1
                tallies[name][0] += a1 == "yes"
                tallies["extraction precision (all types)"][1] += 1
                tallies["extraction precision (all types)"][0] += a1 == "yes"
                if r.get("a2"):
                    extra["extractions judged distinctive"][1] += 1
                    extra["extractions judged distinctive"][0] += r["a2"] == "distinctive"
            elif sec == "lineage":
                want = {"inherited": "same", "modified": "edit", "new": "new"}[it["system_class"]]
                name = f"lineage class '{it['system_class']}' agrees with reviewer"
                tallies[name][1] += 1
                tallies[name][0] += a1 == want
                tallies["lineage (all classes)"][1] += 1
                tallies["lineage (all classes)"][0] += a1 == want
            elif sec == "cue":
                for name, ok in ((f"cue lines: yes ({it['category']})", a1 == "yes"), ("cue lines: yes (all categories)", a1 == "yes"),
                                 ("cue lines: yes or partly (all categories)", a1 in ("yes", "partly"))):
                    tallies[name][1] += 1
                    tallies[name][0] += ok
            elif sec == "exchange":
                tallies["exchanges: genuine reply (yes)"][1] += 1
                tallies["exchanges: genuine reply (yes)"][0] += a1 == "yes"
                tallies["exchanges: yes or partly"][1] += 1
                tallies["exchanges: yes or partly"][0] += a1 in ("yes", "partly")
                if r.get("a2"):
                    extra["exchanges: carrying answers or timing"][1] += 1
                    extra["exchanges: carrying answers or timing"][0] += r["a2"] in ("answers", "timing")
            elif sec == "reference":
                for name in (f"references: real pointer ({it['ref_type']})", "references: real pointer (all types)"):
                    tallies[name][1] += 1
                    tallies[name][0] += a1 == "yes"
            elif sec == "question":
                name = f"answer '{it['question_id']}' correct"
                tallies[name][1] += 1
                tallies[name][0] += a1 == "correct"
                tallies["answers (all)"][1] += 1
                tallies["answers (all)"][0] += a1 == "correct"
    lines = ["# Human review scores", "", f"Reviewers: {', '.join(r['reviewer'] for r in reviews)}", "",
             "| Measure | Result |", "|---|---|"]
    for name in sorted(tallies):
        lines.append(f"| {name} | {fmt(*tallies[name])} |")
    for name in sorted(extra):
        lines.append(f"| {name} | {fmt(*extra[name])} |")
    if len(reviews) >= 2:
        both = defaultdict(lambda: [0, 0])
        a, b = reviews[0]["results"], reviews[1]["results"]
        for iid in set(a) & set(b):
            if iid in items and a[iid].get("a1") and b[iid].get("a1"):
                s = items[iid]["section"]
                both[s][1] += 1
                both[s][0] += a[iid]["a1"] == b[iid]["a1"]
        lines += ["", f"Agreement between {reviews[0]['reviewer']} and {reviews[1]['reviewer']} (exact match on the first answer):", ""]
        lines += [f"- {s}: {fmt(*v)}" for s, v in sorted(both.items())]
    goal = (
        "The brief's acceptance goal is at least 90% precision for the prominently displayed supported relation "
        "class; report the observed numerator and denominator even if it is missed."
    )
    lines += ["", goal]
    return {k: {"hits": v[0], "n": v[1]} for k, v in tallies.items()}, "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", type=Path, default=Path("data/derived/review/review_key.json"))
    ap.add_argument("--results", type=Path, nargs="+", required=True)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    key = json.loads(args.key.read_text(encoding="utf-8"))
    _, md = score(key, load_results(args.results))
    print(md)
    if args.out:
        args.out.write_text(md, encoding="utf-8")


if __name__ == "__main__":
    main()
