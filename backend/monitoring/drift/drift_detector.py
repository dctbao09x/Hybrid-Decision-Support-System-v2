import math
from dataclasses import dataclass
from typing import Iterable, List, Dict

@dataclass
class DriftResult:
    name: str
    score: float
    method: str


def _to_list(values: Iterable[float]) -> List[float]:
    return [float(v) for v in values]


def _histogram(values: List[float], bins: int) -> List[int]:
    if not values:
        return [0] * bins
    min_v = min(values)
    max_v = max(values)
    if min_v == max_v:
        counts = [0] * bins
        counts[0] = len(values)
        return counts
    width = (max_v - min_v) / bins
    counts = [0] * bins
    for v in values:
        idx = int((v - min_v) / width)
        if idx == bins:
            idx -= 1
        counts[idx] += 1
    return counts


def _normalize(counts: List[int]) -> List[float]:
    total = sum(counts)
    if total == 0:
        return [0.0] * len(counts)
    return [c / total for c in counts]


def psi(baseline: Iterable[float], current: Iterable[float], bins: int = 10) -> DriftResult:
    base = _to_list(baseline)
    curr = _to_list(current)
    base_counts = _histogram(base, bins)
    curr_counts = _histogram(curr, bins)
    base_dist = _normalize(base_counts)
    curr_dist = _normalize(curr_counts)

    score = 0.0
    for b, c in zip(base_dist, curr_dist):
        if b == 0 or c == 0:
            continue
        score += (c - b) * math.log(c / b)
    return DriftResult(name="psi", score=score, method="psi")


def js_divergence(baseline: Iterable[float], current: Iterable[float], bins: int = 10) -> DriftResult:
    base = _to_list(baseline)
    curr = _to_list(current)
    base_dist = _normalize(_histogram(base, bins))
    curr_dist = _normalize(_histogram(curr, bins))
    m = [(b + c) / 2 for b, c in zip(base_dist, curr_dist)]

    def _kl(p, q):
        out = 0.0
        for pi, qi in zip(p, q):
            if pi == 0 or qi == 0:
                continue
            out += pi * math.log(pi / qi)
        return out

    score = 0.5 * _kl(base_dist, m) + 0.5 * _kl(curr_dist, m)
    return DriftResult(name="js_divergence", score=score, method="js_divergence")


def ks_statistic(baseline: Iterable[float], current: Iterable[float]) -> DriftResult:
    base = sorted(_to_list(baseline))
    curr = sorted(_to_list(current))
    if not base or not curr:
        return DriftResult(name="ks", score=0.0, method="ks")
    base_len = len(base)
    curr_len = len(curr)
    i = j = 0
    d = 0.0
    while i < base_len and j < curr_len:
        if base[i] <= curr[j]:
            i += 1
        else:
            j += 1
        d = max(d, abs(i / base_len - j / curr_len))
    return DriftResult(name="ks", score=d, method="ks")


def mean_shift(baseline: Iterable[float], current: Iterable[float]) -> DriftResult:
    base = _to_list(baseline)
    curr = _to_list(current)
    if not base or not curr:
        return DriftResult(name="mean_shift", score=0.0, method="mean_shift")
    base_mean = sum(base) / len(base)
    curr_mean = sum(curr) / len(curr)
    score = abs(curr_mean - base_mean) / max(abs(base_mean), 1e-9)
    return DriftResult(name="mean_shift", score=score, method="mean_shift")


def summarize(results: List[DriftResult]) -> Dict[str, float]:
    return {r.method: r.score for r in results}
