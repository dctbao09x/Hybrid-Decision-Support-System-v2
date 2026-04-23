from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUEST_LATENCY = Histogram(
    "http_request_latency_seconds",
    "HTTP request latency in seconds",
    ["route", "method", "status"],
)

LLM_EXTRACTION_TIME = Histogram(
    "llm_extraction_latency_seconds",
    "Time spent extracting features from LLM",
    ["model"],
)

LLM_ERROR_COUNTER = Counter(
    "llm_schema_error_total",
    "Total count of LLM JSON schema extraction failures",
)

RULE_CONFLICT_COUNTER = Counter(
    "rule_engine_conflict_total",
    "Total count of rule conflicts or unknown routing",
)

SCORE_DRIFT_COUNTER = Counter(
    "scoring_drift_total",
    "Total count of scoring drift alerts",
)

INPUT_DRIFT_SCORE = Gauge(
    "input_drift_score",
    "Input drift score across request window",
)

OUTPUT_DRIFT_SCORE = Gauge(
    "output_drift_score",
    "Output drift score across request window",
)

CONFIDENCE_DRIFT_SCORE = Gauge(
    "confidence_drift_score",
    "Confidence drift score across request window",
)

MARKET_DATA_DRIFT_SCORE = Gauge(
    "market_data_drift_score",
    "Market data drift score across sources",
)

TOTAL_COST_USD = Counter(
    "ai_token_cost_usd_total",
    "Total API cost based on token usage",
)

ROLLBACK_EVENT_COUNTER = Counter(
    "rollback_event_total",
    "Rollback events triggered for model deployments",
    ["trigger_id"],
)

ROLLBACK_ACTION_COUNTER = Counter(
    "rollback_action_total",
    "Rollback actions executed",
    ["action"],
)

CACHE_HIT_COUNTER = Counter(
    "cache_hit_total",
    "Cache hits for downstream calls",
)

CACHE_MISS_COUNTER = Counter(
    "cache_miss_total",
    "Cache misses for downstream calls",
)

HITL_QUEUE_SIZE = Gauge(
    "hitl_queue_size",
    "Human-in-the-loop queue size",
)

MARKET_DATA_FRESHNESS_DAYS = Gauge(
    "market_data_freshness_days",
    "Freshness of market data in days",
)

USER_COMPLETION_COUNTER = Counter(
    "user_completion_total",
    "Users who completed the guidance flow",
)

RECOMMENDATION_ACCEPT_COUNTER = Counter(
    "recommendation_accept_total",
    "Users who accepted recommendations",
)

USER_SATISFACTION_COUNTER = Counter(
    "user_satisfaction_total",
    "User satisfaction votes",
    ["sentiment"],
)

DROPOFF_COUNTER = Counter(
    "user_dropoff_total",
    "Users who dropped off before completion",
)

TIME_TO_DECISION = Histogram(
    "time_to_decision_seconds",
    "Time from input to decision output",
)

RECOMMENDATION_REVISION_COUNTER = Counter(
    "recommendation_revision_total",
    "Number of recommendation revisions",
)

HITL_ESCALATION_COUNTER = Counter(
    "hitl_escalation_total",
    "Number of requests escalated to HITL",
)

RETRAIN_TRIGGER_COUNTER = Counter(
    "retrain_trigger_total",
    "Number of retrain triggers fired",
)

CAREER_REJECT_COUNTER = Counter(
    "career_reject_total",
    "Rejected careers",
    ["career_code"],
)

AVERAGE_CONFIDENCE_BY_CAREER = Gauge(
    "average_confidence_by_career",
    "Average confidence per career",
    ["career_code"],
)
