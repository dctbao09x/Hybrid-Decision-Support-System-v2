import argparse
import json
import os
import sys


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_metric(report: dict, key: str, fallback_key: str = "") -> float:
    if key in report:
        return report.get(key, 0)
    if fallback_key and fallback_key in report:
        return report.get(fallback_key, 0)
    return report.get(key, 0)


def check_threshold(name: str, actual: float, expected: float, higher_is_better: bool = True) -> dict:
    passed = actual >= expected if higher_is_better else actual <= expected
    return {"metric": name, "actual": actual, "expected": expected, "passed": passed}


def check_regression(name: str, current: float, baseline: float, max_drop: float, max_increase: float, higher_is_better: bool) -> dict:
    if higher_is_better:
        passed = current >= (baseline - max_drop)
    else:
        passed = current <= (baseline + max_increase)
    return {
        "metric": name,
        "current": current,
        "baseline": baseline,
        "max_drop": max_drop,
        "max_increase": max_increase,
        "passed": passed
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--thresholds", required=True)
    parser.add_argument("--extraction", required=True)
    parser.add_argument("--explanation", required=True)
    parser.add_argument("--fallback", required=True)
    parser.add_argument("--injection", required=True)
    parser.add_argument("--baseline-dir", default="")
    args = parser.parse_args()

    thresholds = load_json(args.thresholds)
    extraction = load_json(args.extraction)
    explanation = load_json(args.explanation)
    fallback = load_json(args.fallback)
    injection = load_json(args.injection)
    baseline_dir = args.baseline_dir

    require_baseline = bool(thresholds.get("regression", {}).get("require_baseline", False))
    max_drop = float(thresholds.get("regression", {}).get("max_drop", 0.0))
    max_increase = float(thresholds.get("regression", {}).get("max_increase", 0.0))

    results = []

    results.append(check_threshold("extraction.json_strict_valid_rate", get_metric(extraction, "json_strict_valid_rate", "json_valid_rate"), thresholds["extraction"]["json_strict_valid_rate"], True))
    results.append(check_threshold("extraction.interest_f1", extraction.get("interest_f1", 0), thresholds["extraction"]["interest_f1"], True))
    results.append(check_threshold("extraction.skill_f1", extraction.get("skill_f1", 0), thresholds["extraction"]["skill_f1"], True))
    results.append(check_threshold("extraction.consistency_rate", extraction.get("consistency_rate", 0), thresholds["extraction"]["consistency_rate"], True))
    results.append(check_threshold("extraction.p90_latency_ms", extraction.get("p90_latency_ms", 0), thresholds["extraction"]["p90_latency_ms"], False))
    results.append(check_threshold("extraction.max_cost_per_request_usd", extraction.get("avg_cost_per_request_usd", 0), thresholds["extraction"]["max_cost_per_request_usd"], False))
    results.append(check_threshold("extraction.edge_json_valid_rate", extraction.get("edge_json_valid_rate", 0), thresholds["extraction"]["edge_json_valid_rate"], True))

    results.append(check_threshold("explanation.must_include_rate", explanation.get("must_include_rate", 0), thresholds["explanation"]["must_include_rate"], True))
    results.append(check_threshold("explanation.hallucination_rate", explanation.get("hallucination_rate", 1), thresholds["explanation"]["hallucination_rate"], False))
    results.append(check_threshold("explanation.consistency_rate", explanation.get("consistency_rate", 0), thresholds["explanation"]["consistency_rate"], True))
    results.append(check_threshold("explanation.p90_latency_ms", explanation.get("p90_latency_ms", 0), thresholds["explanation"]["p90_latency_ms"], False))
    results.append(check_threshold("explanation.max_cost_per_request_usd", explanation.get("avg_cost_per_request_usd", 0), thresholds["explanation"]["max_cost_per_request_usd"], False))

    results.append(check_threshold("fallback.json_strict_valid_rate", get_metric(fallback, "json_strict_valid_rate", "json_valid_rate"), thresholds["fallback"]["json_strict_valid_rate"], True))
    results.append(check_threshold("fallback.missing_flags_rate", fallback.get("missing_flags_rate", 0), thresholds["fallback"]["missing_flags_rate"], True))
    results.append(check_threshold("fallback.consistency_rate", fallback.get("consistency_rate", 0), thresholds["fallback"]["consistency_rate"], True))
    results.append(check_threshold("fallback.edge_json_valid_rate", fallback.get("edge_json_valid_rate", 0), thresholds["fallback"]["edge_json_valid_rate"], True))

    results.append(check_threshold("injection.safe_rate", injection.get("safe_rate", 0), thresholds["injection"]["safe_rate"], True))
    results.append(check_threshold("injection.json_strict_valid_rate", get_metric(injection, "json_strict_valid_rate", "json_valid_rate"), thresholds["injection"]["json_strict_valid_rate"], True))

    if require_baseline:
        if not baseline_dir:
            print(json.dumps({"error": "baseline_dir_required"}, indent=2))
            sys.exit(1)

        baseline_extraction = load_json(os.path.join(baseline_dir, "extraction_baseline.json"))
        baseline_explanation = load_json(os.path.join(baseline_dir, "explanation_baseline.json"))
        baseline_fallback = load_json(os.path.join(baseline_dir, "fallback_baseline.json"))
        baseline_injection = load_json(os.path.join(baseline_dir, "injection_baseline.json"))

        results.append(check_regression("regression.extraction.interest_f1", extraction.get("interest_f1", 0), baseline_extraction.get("interest_f1", 0), max_drop, max_increase, True))
        results.append(check_regression("regression.extraction.skill_f1", extraction.get("skill_f1", 0), baseline_extraction.get("skill_f1", 0), max_drop, max_increase, True))
        results.append(check_regression("regression.extraction.json_strict_valid_rate", get_metric(extraction, "json_strict_valid_rate", "json_valid_rate"), get_metric(baseline_extraction, "json_strict_valid_rate", "json_valid_rate"), max_drop, max_increase, True))
        results.append(check_regression("regression.explanation.must_include_rate", explanation.get("must_include_rate", 0), baseline_explanation.get("must_include_rate", 0), max_drop, max_increase, True))
        results.append(check_regression("regression.explanation.hallucination_rate", explanation.get("hallucination_rate", 1), baseline_explanation.get("hallucination_rate", 1), max_drop, max_increase, False))
        results.append(check_regression("regression.fallback.json_strict_valid_rate", get_metric(fallback, "json_strict_valid_rate", "json_valid_rate"), get_metric(baseline_fallback, "json_strict_valid_rate", "json_valid_rate"), max_drop, max_increase, True))
        results.append(check_regression("regression.injection.safe_rate", injection.get("safe_rate", 0), baseline_injection.get("safe_rate", 0), max_drop, max_increase, True))

    failed = [r for r in results if not r["passed"]]
    print(json.dumps({"results": results, "failed": failed}, indent=2))

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
