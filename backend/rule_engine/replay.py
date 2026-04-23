import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from backend.rule_engine.rule_engine import RuleEngine


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


def replay(input_path: Path, output_path: Path, ruleset_path: Optional[Path]) -> None:
    engine = RuleEngine(config_path=ruleset_path)
    output_records = []

    for record in _read_jsonl(input_path):
        profile = record.get("profile", {})
        job = record.get("job")

        if job:
            result = engine.evaluate_job(profile, job)
        else:
            result = engine.process_profile(profile)

        output_records.append({
            "input": record,
            "output": result,
        })

    _write_jsonl(output_path, output_records)


def _key_for_record(record: Dict[str, Any]) -> str:
    payload = record.get("input", record)
    try:
        return json.dumps(payload, sort_keys=True, ensure_ascii=True)
    except Exception:
        return str(payload)


def compare_outputs(
    baseline_path: Path,
    candidate_path: Path,
    max_score_diff: float = 0.15,
) -> Dict[str, Any]:
    baseline = { _key_for_record(r): r for r in _read_jsonl(baseline_path) }
    candidate = { _key_for_record(r): r for r in _read_jsonl(candidate_path) }

    total = 0
    mismatched = 0
    max_diff = 0.0

    for key, cand in candidate.items():
        base = baseline.get(key)
        if not base:
            continue
        total += 1

        base_out = base.get("output", {})
        cand_out = cand.get("output", {})

        # Job-level compare
        if "job" in base_out and "job" in cand_out:
            if base_out.get("passed") != cand_out.get("passed"):
                mismatched += 1
                continue
            diff = abs(float(base_out.get("score_delta", 0.0)) - float(cand_out.get("score_delta", 0.0)))
            max_diff = max(max_diff, diff)
            if diff > max_score_diff:
                mismatched += 1
            continue

        # Profile-level compare (top job score)
        base_ranked = base_out.get("ranked_jobs", []) if isinstance(base_out, dict) else []
        cand_ranked = cand_out.get("ranked_jobs", []) if isinstance(cand_out, dict) else []
        if base_ranked and cand_ranked:
            base_top = base_ranked[0]
            cand_top = cand_ranked[0]
            if base_top.get("job") != cand_top.get("job"):
                mismatched += 1
                continue
            diff = abs(float(base_top.get("score", 0.0)) - float(cand_top.get("score", 0.0)))
            max_diff = max(max_diff, diff)
            if diff > max_score_diff:
                mismatched += 1
            continue

    mismatch_rate = (mismatched / total) if total else 0.0
    return {
        "total_compared": total,
        "mismatched": mismatched,
        "mismatch_rate": round(mismatch_rate, 6),
        "max_score_diff": round(max_diff, 6),
        "threshold": max_score_diff,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay rule engine on historical data")
    parser.add_argument("--input", required=True, help="Path to JSONL input")
    parser.add_argument("--output", required=True, help="Path to JSONL output")
    parser.add_argument("--ruleset", default=None, help="Optional ruleset YAML path")
    parser.add_argument("--baseline", default=None, help="Optional baseline output JSONL for drift compare")
    parser.add_argument("--report", default=None, help="Optional path to write drift report JSON")
    parser.add_argument("--max-score-diff", default=0.15, type=float, help="Drift threshold")
    args = parser.parse_args()

    replay(Path(args.input), Path(args.output), Path(args.ruleset) if args.ruleset else None)

    if args.baseline:
        report = compare_outputs(
            Path(args.baseline),
            Path(args.output),
            max_score_diff=args.max_score_diff,
        )
        if args.report:
            with open(args.report, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=True, indent=2)
        else:
            print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
