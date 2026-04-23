def normalize_text(text: str) -> str:
    if text is None:
        return ""
    return " ".join(text.strip().lower().split())

def stable_signature(parts) -> str:
    if parts is None:
        return ""
    if isinstance(parts, list):
        normalized = [normalize_text(str(x)) for x in parts if str(x).strip()]
        return "|".join(sorted(normalized))
    return normalize_text(str(parts))

def f1_from_counts(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}

def percentile(values, p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = int(round((p / 100.0) * (len(sorted_vals) - 1)))
    return float(sorted_vals[k])

def match_by_substring(pred_list, gold_list):
    pred_norm = [normalize_text(x) for x in pred_list]
    gold_norm = [normalize_text(x) for x in gold_list]

    matched_pred = set()
    matched_gold = set()

    for g in gold_norm:
        for p in pred_norm:
            if g and (g in p):
                matched_gold.add(g)
                matched_pred.add(p)
                break

    tp = len(matched_gold)
    fp = max(0, len(pred_norm) - len(matched_pred))
    fn = max(0, len(gold_norm) - len(matched_gold))
    return f1_from_counts(tp, fp, fn)

def estimate_cost_usd(total_tokens: int, cost_per_1k: float) -> float:
    if not total_tokens or cost_per_1k <= 0:
        return 0.0
    return round((total_tokens / 1000.0) * cost_per_1k, 6)
