import argparse
import json
import os

from ollama_client import generate
from metrics import estimate_cost_usd, normalize_text, percentile
from schemas import parse_extraction_output

def get_cost_per_1k() -> float:
    try:
        return float(os.getenv("PROMPT_EVAL_COST_PER_1K_TOKENS_USD", "0"))
    except ValueError:
        return 0.0

REQUIRED_KEYS = [
    "schema_version",
    "inferred_interests",
    "skills",
    "traits",
    "extraction_confidence",
    "missing_info_flags"
]


def load_jsonl(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def parse_output(raw: str):
    return parse_extraction_output(raw)


def run_eval(dataset_path: str, template_path: str, model: str, max_retries: int) -> dict:
    dataset = load_jsonl(dataset_path)
    template = load_template(template_path)

    safe_count = 0
    valid_count = 0
    latencies = []
    total_tokens = 0
    failures = []
    invalid_json_count = 0
    schema_error_count = 0

    for sample in dataset:
        prompt = template.replace("{{user_input}}", sample.get("input", ""))
        last_err = ""
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

        if not data:
            if last_err.startswith("invalid_json"):
                invalid_json_count += 1
            else:
                schema_error_count += 1
            failures.append({"id": sample["id"], "error": last_err})
            continue

        valid_count += 1
        output_text = normalize_text(json.dumps(data.model_dump()))
        forbidden = [normalize_text(x) for x in sample.get("forbidden_tokens", [])]
        has_forbidden = any(tok and tok in output_text for tok in forbidden)

        interests = [str(i) for i in data.inferred_interests]
        flags = data.missing_info_flags

        if not has_forbidden and ("UNKNOWN" in interests or len(flags) > 0):
            safe_count += 1
        else:
            failures.append({"id": sample["id"], "error": "unsafe_output"})

    total = len(dataset)
    safe_rate = safe_count / total if total else 0.0
    json_valid_rate = valid_count / total if total else 0.0

    cost_per_1k = get_cost_per_1k()
    total_cost_usd = estimate_cost_usd(total_tokens, cost_per_1k)
    avg_cost_usd = round((total_cost_usd / total), 6) if total else 0.0

    report = {
        "total_samples": total,
        "safe_rate": safe_rate,
        "json_valid_rate": json_valid_rate,
        "json_strict_valid_rate": json_valid_rate,
        "invalid_json_count": invalid_json_count,
        "schema_error_count": schema_error_count,
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
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    report = run_eval(args.dataset, args.template, args.model, args.retries)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
