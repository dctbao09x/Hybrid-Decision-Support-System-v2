import argparse
import json
import os

from ollama_client import generate
from metrics import estimate_cost_usd, percentile, stable_signature
from schemas import parse_extraction_output

def get_cost_per_1k() -> float:
    try:
        return float(os.getenv("PROMPT_EVAL_COST_PER_1K_TOKENS_USD", "0"))
    except ValueError:
        return 0.0


def load_jsonl(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def parse_output(raw: str):
    return parse_extraction_output(raw)


def run_eval(dataset_path: str, template_path: str, model: str, max_retries: int, edge_path: str, consistency_runs: int) -> dict:
    dataset = load_jsonl(dataset_path)
    template = load_template(template_path)

    valid_count = 0
    missing_flags_ok = 0
    latencies = []
    total_tokens = 0
    failures = []
    invalid_json_count = 0
    schema_error_count = 0
    consistent_count = 0

    for sample in dataset:
        prompt = template.replace("{{user_input}}", sample.get("input", ""))
        last_err = ""
        first_valid = None
        signatures = []

        for _ in range(max(consistency_runs, 1)):
            data = None
            meta = None
            for _ in range(max_retries + 1):
                raw, meta = generate(prompt, model=model, format_json=True)
                data, last_err = parse_output(raw)
                if data:
                    break

            if meta:
                latencies.append(meta["latency_ms"])
                total_tokens += meta["total_tokens"]

            if data:
                signatures.append(stable_signature([str(i) for i in data.inferred_interests]))
                if first_valid is None:
                    first_valid = data
            else:
                if last_err.startswith("invalid_json"):
                    invalid_json_count += 1
                else:
                    schema_error_count += 1

        if not first_valid:
            failures.append({"id": sample["id"], "error": last_err})
            continue

        valid_count += 1
        if len(signatures) == max(consistency_runs, 1) and len(set(signatures)) == 1:
            consistent_count += 1

        expected = sample.get("expected", {})
        expected_interest = expected.get("interest", "UNKNOWN")
        min_flags = int(expected.get("min_missing_flags", 1))
        interests = [str(i) for i in first_valid.inferred_interests]
        flags = first_valid.missing_info_flags

        if expected_interest in interests and len(flags) >= min_flags:
            missing_flags_ok += 1
        else:
            failures.append({"id": sample["id"], "error": "missing_flags_or_interest"})

    total = len(dataset)
    json_valid_rate = valid_count / total if total else 0.0
    missing_flags_rate = missing_flags_ok / total if total else 0.0
    consistency_rate = consistent_count / total if total else 0.0

    edge_json_valid_rate = 0.0
    if edge_path:
        edge_data = load_jsonl(edge_path)
        edge_valid = 0
        for sample in edge_data:
            prompt = template.replace("{{user_input}}", sample.get("input", ""))
            model_out = None
            for _ in range(max_retries + 1):
                raw, meta = generate(prompt, model=model, format_json=True)
                model_out, _ = parse_output(raw)
                if meta:
                    latencies.append(meta["latency_ms"])
                    total_tokens += meta["total_tokens"]
                if model_out:
                    break
            if model_out:
                edge_valid += 1
        edge_json_valid_rate = edge_valid / len(edge_data) if edge_data else 0.0

    cost_per_1k = get_cost_per_1k()
    total_cost_usd = estimate_cost_usd(total_tokens, cost_per_1k)
    avg_cost_usd = round((total_cost_usd / total), 6) if total else 0.0

    report = {
        "total_samples": total,
        "json_valid_rate": json_valid_rate,
        "json_strict_valid_rate": json_valid_rate,
        "invalid_json_count": invalid_json_count,
        "schema_error_count": schema_error_count,
        "missing_flags_rate": missing_flags_rate,
        "consistency_rate": consistency_rate,
        "edge_json_valid_rate": edge_json_valid_rate,
        "p50_latency_ms": percentile(latencies, 50),
        "p90_latency_ms": percentile(latencies, 90),
        "p99_latency_ms": percentile(latencies, 99),
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost_usd,
        "avg_cost_per_request_usd": avg_cost_usd,
        "failures": failures
    }
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--model", default=os.getenv("PROMPT_EVAL_MODEL", "llama3.2:1b"))
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--edge", default="")
    parser.add_argument("--consistency-runs", type=int, default=1)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    report = run_eval(args.dataset, args.template, args.model, args.retries, args.edge, args.consistency_runs)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
