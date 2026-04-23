# LLM Extraction Architecture And Migration

## Architecture Decision

- Mode strategy: configurable deterministic, llm-only, or hybrid.
- Default mode: deterministic_input_only (safe rollout baseline).
- Runtime switch: DECISION_EXTRACTION_MODE.
- Supported values:
  - deterministic_input_only
  - llm_only
  - hybrid
- Production recommendation: hybrid after shadow validation.

## Updated Runtime Flow

1. Stage 2 reads manual features (if provided).
2. Controller resolves extraction mode from DECISION_EXTRACTION_MODE.
3. In hybrid mode, LLM extraction is attempted only when manual feature coverage is low.
4. LLM path calls backend/services/llm_extractor.py.
5. Extractor invokes the real provider client (no mock output path).
6. Output is validated against LLMExtractionEnvelopeV1 with retry budget.
7. Confidence gate is enforced (LLM_EXTRACTION_MIN_CONFIDENCE).
8. On low confidence or validation/provider failure, controller falls back to manual features.
9. Final projected numeric feature signals are merged into Stage 2 output.

## Validation And Fallback Logic

- Schema validation:
  - Strict parsing with Pydantic LLMExtractionEnvelopeV1.
  - Retry budget via LLM_EXTRACTION_MAX_RETRIES.
  - Parse size guard via LLM_EXTRACTION_MAX_RAW_CHARS.
- Confidence gate:
  - Extraction confidence compared to LLM_EXTRACTION_MIN_CONFIDENCE.
  - Low confidence marks fallback path.
- Fallback policy:
  - Prefer caller-provided manual features.
  - If no manual features exist, deterministic projected signals may be retained.
  - Final safety fallback uses UNKNOWN extraction profile.

## Metrics Added

- extraction_success_rate
- schema_validation_failure_rate
- extraction_confidence_distribution (bucketed counter)
- fallback_to_manual_features_rate

All metrics are emitted by DecisionController using the existing Ops metrics collector integration.

## Files Updated

- backend/services/llm_extractor.py
- backend/api/controllers/decision_controller.py
- backend/tests/test_llm_extraction_path.py

## Migration Plan

1. Deploy with DECISION_EXTRACTION_MODE=deterministic_input_only.
2. Verify no regression in one-button latency and success rate.
3. Enable hybrid mode in staging and monitor:
   - extraction_success_rate
   - schema_validation_failure_rate
   - fallback_to_manual_features_rate
4. Tune thresholds if needed:
   - LLM_EXTRACTION_MIN_CONFIDENCE
   - LLM_EXTRACTION_MAX_RETRIES
5. Promote hybrid mode to production.
6. Use llm_only only for controlled experiments.
