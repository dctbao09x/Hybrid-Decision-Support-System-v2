class SpanNames:
    # Standardized span naming convention (v1)
    REQUEST_RECEIVE = "request.receive"
    PRIVACY_REDACTION = "privacy.redaction"
    LLM_EXTRACT = "llm.extract"
    SCHEMA_VALIDATE = "schema.validate"
    RULES_EVALUATE = "rules.evaluate"
    SCORING_COMPUTE = "scoring.compute"
    MARKET_FETCH = "market.fetch"
    EXPLANATION_RENDER = "explanation.render"
    RESPONSE_STREAM = "response.stream"
    DRIFT_DETECT = "drift.detect"
    ROLLBACK_EXECUTE = "rollback.execute"

    # Backward-compatible aliases
    REQUEST = REQUEST_RECEIVE
    INPUT_PRIVACY = PRIVACY_REDACTION
    RULE_EVAL = RULES_EVALUATE
    SCORING = SCORING_COMPUTE
    MARKET = MARKET_FETCH
    EXPLAIN = EXPLANATION_RENDER
    EXPLAIN_STREAM = RESPONSE_STREAM
    DRIFT = DRIFT_DETECT
    ROLLBACK = ROLLBACK_EXECUTE
