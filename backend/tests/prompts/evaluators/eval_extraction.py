import argparse
import json
import os
from typing import List, Tuple

from ollama_client import generate
from metrics import estimate_cost_usd, f1_from_counts, match_by_substring, normalize_text, percentile, stable_signature
from schemas import parse_extraction_output

MAX_SKILL_LEN = 60
MAX_FLAG_LEN = 80


def load_jsonl(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_cost_per_1k() -> float:
    try:
        return float(os.getenv("PROMPT_EVAL_COST_PER_1K_TOKENS_USD", "0"))
    except ValueError:
        return 0.0


def extract_predicted(model) -> Tuple[List[str], List[str]]:
    interests = [str(item).upper() for item in model.inferred_interests]
    skills = [s.skill_name for s in model.skills]
    return interests, skills


def score_sets(pred: List[str], gold: List[str]) -> dict:
    pred_set = set(pred)
    gold_set = set(gold)
    tp = len(pred_set & gold_set)
    fp = len(pred_set - gold_set)
    fn = len(gold_set - pred_set)
    return f1_from_counts(tp, fp, fn)


def build_signature(model) -> str:
    interests = [str(i).upper() for i in model.inferred_interests]
    skills = [normalize_text(s.skill_name) for s in model.skills]
    traits = f"{model.traits.extraversion_level}:{model.traits.stress_tolerance}"
    return "|".join([stable_signature(interests), stable_signature(skills), traits])


def generate_valid_output(prompt: str, model: str, max_retries: int):
    last_err = ""
    meta = None
    for _ in range(max_retries + 1):
        raw, meta = generate(prompt, model=model, format_json=True)
        parsed, last_err = parse_extraction_output(raw)
        if parsed:
            return parsed, meta, ""
    return None, meta, last_err


def run_eval(dataset_path: str, template_path: str, model: str, max_retries: int, edge_path: str, consistency_runs: int) -> dict:
    dataset = load_jsonl(dataset_path)
    template = load_template(template_path)

    interest_tp = interest_fp = interest_fn = 0
    skill_tp = skill_fp = skill_fn = 0
    valid_count = 0
    oversize_count = 0
    latencies = []
    total_tokens = 0
    failures = []
    invalid_json_count = 0
    schema_error_count = 0
    consistent_count = 0

    for sample in dataset:
        prompt = template.replace("{{user_input}}", sample["input"])
        signatures = []
        first_valid = None

        for _ in range(max(consistency_runs, 1)):
            model_out, meta, err = generate_valid_output(prompt, model, max_retries)
            if meta:
                latencies.append(meta["latency_ms"])
                total_tokens += meta["total_tokens"]
            if model_out:
                signatures.append(build_signature(model_out))
                if first_valid is None:
                    first_valid = model_out
            else:
                if err.startswith("invalid_json"):
                    invalid_json_count += 1
                else:
                    schema_error_count += 1

        if not first_valid:
            failures.append({"id": sample["id"], "error": "invalid_or_schema"})
            continue

        valid_count += 1
        if len(signatures) == max(consistency_runs, 1) and len(set(signatures)) == 1:
            consistent_count += 1

        pred_interests, pred_skills = extract_predicted(first_valid)
        gold = sample["expected"]
        gold_interests = [g.upper() for g in gold.get("interests", [])]
        gold_skills = gold.get("skills", [])

        pred_set = set(pred_interests)
        gold_set = set(gold_interests)
        interest_tp += len(pred_set & gold_set)
        interest_fp += len(pred_set - gold_set)
        interest_fn += len(gold_set - pred_set)

        for s in pred_skills:
            if len(s) > MAX_SKILL_LEN:
                oversize_count += 1
        for flag in first_valid.missing_info_flags:
            if isinstance(flag, str) and len(flag) > MAX_FLAG_LEN:
                oversize_count += 1

        pred_norm = [normalize_text(x) for x in pred_skills]
        gold_norm = [normalize_text(x) for x in gold_skills]
        matched_pred = set()
        matched_gold = set()
        for g in gold_norm:
            for p in pred_norm:
                if g and g in p:
                    matched_gold.add(g)
                    matched_pred.add(p)
                    break
        skill_tp += len(matched_gold)
        skill_fp += max(0, len(pred_norm) - len(matched_pred))
        skill_fn += max(0, len(gold_norm) - len(matched_gold))

    interest_scores = f1_from_counts(interest_tp, interest_fp, interest_fn)
    skill_scores = f1_from_counts(skill_tp, skill_fp, skill_fn)

    total = len(dataset)
    json_strict_valid_rate = valid_count / total if total else 0.0
    consistency_rate = consistent_count / total if total else 0.0

    cost_per_1k = get_cost_per_1k()
    total_cost_usd = estimate_cost_usd(total_tokens, cost_per_1k)
    avg_cost_usd = round((total_cost_usd / total), 6) if total else 0.0

    edge_json_valid_rate = 0.0
    if edge_path:
        edge_data = load_jsonl(edge_path)
        edge_valid = 0
        for sample in edge_data:
            edge_prompt = template.replace("{{user_input}}", sample.get("input", ""))
            model_out, meta, _ = generate_valid_output(edge_prompt, model, max_retries)
            if meta:
                latencies.append(meta["latency_ms"])
                total_tokens += meta["total_tokens"]
            if model_out:
                edge_valid += 1
        edge_json_valid_rate = edge_valid / len(edge_data) if edge_data else 0.0

    report = {
        "total_samples": total,
        "json_valid_rate": json_strict_valid_rate,
        "json_strict_valid_rate": json_strict_valid_rate,
        "invalid_json_count": invalid_json_count,
        "schema_error_count": schema_error_count,
        "interest_precision": interest_scores["precision"],
        "interest_recall": interest_scores["recall"],
        "interest_f1": interest_scores["f1"],
        "skill_precision": skill_scores["precision"],
        "skill_recall": skill_scores["recall"],
        "skill_f1": skill_scores["f1"],
        "consistency_rate": consistency_rate,
        "edge_json_valid_rate": edge_json_valid_rate,
        "p50_latency_ms": percentile(latencies, 50),
        "p90_latency_ms": percentile(latencies, 90),
        "p99_latency_ms": percentile(latencies, 99),
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost_usd,
        "avg_cost_per_request_usd": avg_cost_usd,
        "oversize_fields": oversize_count,
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
