"""
Generate realistic training data for the ML Evaluation Service.
Produces data/training.csv with ≥ 200 unique rows.

Career-mapping logic (domain-expert rules + controlled noise):
  - High math + physics + logic + IT interest  → Software Engineer
  - High math + physics, moderate logic         → Mechanical Engineer
  - High math, low physics, low IT interest     → Accountant
  - High physics, moderate math                 → Civil Engineer
  - Moderate scores, high IT interest           → Data Analyst
  - Low math, moderate interest                 → Business Administration
  - High logic, moderate math                   → Cybersecurity Analyst

This script is run once to bootstrap the CSV.
"""

import csv
import random
import hashlib
from pathlib import Path

random.seed(42)

CAREERS = [
    "Software Engineer",
    "Data Analyst",
    "Mechanical Engineer",
    "Accountant",
    "Civil Engineer",
    "Business Administration",
    "Cybersecurity Analyst",
]

# (math_range, physics_range, interest_it_range, logic_range, career, count)
ARCHETYPES = [
    # Software Engineer — high across the board
    ((78, 100), (70, 100), (80, 100), (75, 100), "Software Engineer", 45),
    # Data Analyst — moderate math, high IT interest
    ((60, 85), (45, 75), (70, 100), (55, 80), "Data Analyst", 35),
    # Mechanical Engineer — strong math & physics
    ((70, 95), (75, 100), (10, 50), (60, 85), "Mechanical Engineer", 30),
    # Accountant — math-heavy, low physics / IT
    ((75, 100), (20, 55), (5, 35), (50, 75), "Accountant", 30),
    # Civil Engineer — physics + moderate math
    ((55, 80), (70, 100), (10, 45), (50, 75), "Civil Engineer", 25),
    # Business Administration — moderate all, low IT
    ((35, 65), (25, 55), (10, 40), (35, 60), "Business Administration", 25),
    # Cybersecurity Analyst — high logic + moderate math
    ((55, 85), (40, 70), (60, 95), (78, 100), "Cybersecurity Analyst", 25),
]

OUTPUT = Path(__file__).resolve().parent.parent / "data" / "training.csv"


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def generate() -> list[dict]:
    rows: list[dict] = []
    seen_hashes: set[str] = set()

    for math_r, phys_r, it_r, logic_r, career, count in ARCHETYPES:
        generated = 0
        attempts = 0
        while generated < count and attempts < count * 10:
            attempts += 1
            math = round(_clamp(random.gauss(
                (math_r[0] + math_r[1]) / 2,
                (math_r[1] - math_r[0]) / 4,
            )), 1)
            physics = round(_clamp(random.gauss(
                (phys_r[0] + phys_r[1]) / 2,
                (phys_r[1] - phys_r[0]) / 4,
            )), 1)
            interest_it = round(_clamp(random.gauss(
                (it_r[0] + it_r[1]) / 2,
                (it_r[1] - it_r[0]) / 4,
            )), 1)
            logic = round(_clamp(random.gauss(
                (logic_r[0] + logic_r[1]) / 2,
                (logic_r[1] - logic_r[0]) / 4,
            )), 1)

            row_hash = hashlib.md5(
                f"{math}-{physics}-{interest_it}-{logic}".encode()
            ).hexdigest()

            if row_hash in seen_hashes:
                continue
            seen_hashes.add(row_hash)

            rows.append({
                "math_score": math,
                "physics_score": physics,
                "interest_it": interest_it,
                "logic_score": logic,
                "target_career": career,
            })
            generated += 1

    random.shuffle(rows)
    return rows


def main():
    rows = generate()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["math_score", "physics_score", "interest_it", "logic_score", "target_career"],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Generated {len(rows)} rows → {OUTPUT}")


if __name__ == "__main__":
    main()
