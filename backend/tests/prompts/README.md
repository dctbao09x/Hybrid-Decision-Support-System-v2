# Prompt Evaluation Framework

## Overview
This folder contains datasets, prompt templates, and evaluators for prompt regression testing.
It covers extraction, explanation, and fallback prompts with strict JSON validation and quality gates.

## Structure
- datasets/: gold data, injection cases, and edge cases (JSONL)
- templates/: prompt versions (v1, v2, etc.)
- evaluators/: Python scripts for metrics and gating
- promptfoo_*.yaml: quick sanity checks with promptfoo
- prompt_registry.json: prompt metadata for versioning and audit trail

## Quick Run (local Ollama)
Set the model and host if needed:
- PROMPT_EVAL_MODEL=llama3.2:1b
- OLLAMA_HOST=http://localhost:11434
Optional cost config:
- PROMPT_EVAL_COST_PER_1K_TOKENS_USD=0.0005

Run extraction evaluation:
- python backend/tests/prompts/evaluators/eval_extraction.py \
  --dataset backend/tests/prompts/datasets/extraction_gold.jsonl \
  --template backend/tests/prompts/templates/extract_v1.prompt.txt \
  --edge backend/tests/prompts/datasets/edge_cases.jsonl \
  --consistency-runs 3 \
  --out backend/tests/prompts/reports/extraction_report.json

Run explanation evaluation:
- python backend/tests/prompts/evaluators/eval_explanation.py \
  --dataset backend/tests/prompts/datasets/explanation_gold.jsonl \
  --template backend/tests/prompts/templates/explain_v1.prompt.txt \
  --consistency-runs 3 \
  --out backend/tests/prompts/reports/explanation_report.json

Run fallback evaluation:
- python backend/tests/prompts/evaluators/eval_fallback.py \
  --dataset backend/tests/prompts/datasets/fallback_gold.jsonl \
  --template backend/tests/prompts/templates/fallback_v1.prompt.txt \
  --edge backend/tests/prompts/datasets/edge_cases.jsonl \
  --consistency-runs 3 \
  --out backend/tests/prompts/reports/fallback_report.json

Run injection evaluation:
- python backend/tests/prompts/evaluators/eval_injection.py \
  --dataset backend/tests/prompts/datasets/injection_redteam.jsonl \
  --template backend/tests/prompts/templates/extract_v1.prompt.txt \
  --out backend/tests/prompts/reports/injection_report.json

Run quality gate:
- python backend/tests/prompts/evaluators/gate.py \
  --thresholds backend/tests/prompts/thresholds.json \
  --extraction backend/tests/prompts/reports/extraction_report.json \
  --explanation backend/tests/prompts/reports/explanation_report.json \
  --fallback backend/tests/prompts/reports/fallback_report.json \
  --injection backend/tests/prompts/reports/injection_report.json \
  --baseline-dir backend/tests/prompts/baselines

## Baseline and Regression
- Baselines live in backend/tests/prompts/baselines and should be refreshed from the last stable prompt.
- The gate enforces max regression (see thresholds.json).

## Offline vs Online Evaluation
- Offline: run the evaluators above on versioned datasets (gold + edge + injection).
- Online (shadow): store production traces separately and evaluate using the same scripts.

## Prompt Versioning Strategy
- Use semantic versioning in file names: extract_v1.prompt.txt, extract_v1_1.prompt.txt
- Store metadata in git history and release tags
- Compare new vs. baseline via datasets and gates before deployment
- Update prompt_registry.json when promoting a new prompt to stable
