import argparse
import json
import os

from ollama_client import generate
from metrics import estimate_cost_usd, normalize_text, percentile, stable_signature

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


def run_eval(dataset_path: str, template_path: str, model: str, max_retries: int, consistency_runs: int) -> dict:
    dataset = load_jsonl(dataset_path)
    template = load_template(template_path)

    pass_count = 0
    hallucination_count = 0
    latencies = []
    total_tokens = 0
    failures = []
    consistent_count = 0

    for sample in dataset:
        facts = sample.get("facts", {})
        prompt = template
        prompt = prompt.replace("{{user_input}}", sample.get("input", ""))
        prompt = prompt.replace("{{top_career}}", facts.get("top_career", ""))
        prompt = prompt.replace("{{skills}}", ", ".join(facts.get("skills", [])))
        prompt = prompt.replace("{{score_breakdown}}", json.dumps(facts.get("score_breakdown", {})))

        normalized_outputs = []
        best_text = ""

        for _ in range(max(consistency_runs, 1)):
            raw = ""
            meta = None
            for _ in range(max_retries + 1):
                raw, meta = generate(prompt, model=model, format_json=False)
                if raw.strip():
                    break

            text = normalize_text(raw)
            normalized_outputs.append(stable_signature(text))

            if meta:
                latencies.append(meta["latency_ms"])
                total_tokens += meta["total_tokens"]

            if not best_text:
                best_text = text

        if len(normalized_outputs) == max(consistency_runs, 1) and len(set(normalized_outputs)) == 1:
            consistent_count += 1

        must_include = [normalize_text(x) for x in sample.get("must_include", [])]
        forbidden = [normalize_text(x) for x in sample.get("forbidden", [])]

        missing = [m for m in must_include if m and m not in best_text]
        if not missing:
            pass_count += 1
        else:
            failures.append({"id": sample["id"], "missing": missing})

        if any(f and f in best_text for f in forbidden):
            hallucination_count += 1

    total = len(dataset)
    must_include_rate = pass_count / total if total else 0.0
    hallucination_rate = hallucination_count / total if total else 0.0
    consistency_rate = consistent_count / total if total else 0.0

    cost_per_1k = get_cost_per_1k()
    total_cost_usd = estimate_cost_usd(total_tokens, cost_per_1k)
    avg_cost_usd = round((total_cost_usd / total), 6) if total else 0.0

    report = {
        "total_samples": total,
        "must_include_rate": must_include_rate,
        "hallucination_rate": hallucination_rate,
        "consistency_rate": consistency_rate,
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
    parser.add_argument("--consistency-runs", type=int, default=1)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    report = run_eval(args.dataset, args.template, args.model, args.retries, args.consistency_runs)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
