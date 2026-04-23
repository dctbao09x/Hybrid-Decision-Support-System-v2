# Controller Specification
## Hybrid Decision Support System - MainController 8-Step Pipeline

**Version:** 1.2.0  
**Generated:** 2026-01-15  
**Status:** Production

---

## Overview

The `MainController` is the central orchestrator that ALL API requests MUST pass through. It implements an 8-step pipeline ensuring consistent:
- Authentication & Authorization
- Request validation
- Context enrichment
- Service dispatch
- Result collection
- XAI integration
- Audit logging

---

## 8-Step Dispatch Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                     MainController.dispatch()                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Step 1: VALIDATE                                               │
│    └─→ _dispatch_validate(service, action, payload)             │
│         • Check service exists in valid_services                │
│         • Check action valid for service                        │
│         • Validate payload schema                               │
│                                                                  │
│  Step 2: AUTHENTICATE                                           │
│    └─→ _dispatch_authenticate(context)                          │
│         • Extract auth token from context                       │
│         • Verify token validity                                 │
│         • Load user identity                                    │
│                                                                  │
│  Step 3: AUTHORIZE                                              │
│    └─→ _dispatch_authorize(service, action, auth_result)        │
│         • Check user has permission for service                 │
│         • Check user has permission for action                  │
│         • Enforce RBAC policies                                 │
│                                                                  │
│  Step 4: LOAD CONTEXT                                           │
│    └─→ _dispatch_load_context(context, auth_result)             │
│         • Set correlation_id                                    │
│         • Load user profile/preferences                         │
│         • Merge auth info into context                          │
│                                                                  │
│  Step 5: DISPATCH TO SERVICE                                    │
│    └─→ _dispatch_to_service(service, action, payload, ctx)      │
│         • Route to appropriate handler                          │
│         • Execute service logic                                 │
│         • Return raw result                                     │
│                                                                  │
│  Step 6: COLLECT RESULT                                         │
│    └─→ Calculate duration, prepare response                     │
│         • Measure execution time                                │
│         • Format response structure                             │
│                                                                  │
│  Step 7: EXPLAIN                                                │
│    └─→ _dispatch_explain(result, context)                       │
│         • For scoring/recommend/infer services                  │
│         • Generate XAI explanations                             │
│         • Attach explanation to result                          │
│                                                                  │
│  Step 8: LOG                                                    │
│    └─→ _dispatch_log(service, action, duration, ctx, result)    │
│         • Write audit log entry                                 │
│         • Update metrics                                        │
│         • Track for analytics                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Dispatch Method Signature

```python
async def dispatch(
    self,
    service: str,      # Service name: "scoring", "market", etc.
    action: str,       # Action: "rank", "score", "signal", etc.
    payload: Dict[str, Any],      # Request body
    context: Optional[Dict[str, Any]] = None,  # Request context
) -> Dict[str, Any]:
    """
    Returns:
        {
            ...service_result,
            "_meta": {
                "correlation_id": str,
                "user_id": str,
                "service": str,
                "action": str,
                "duration_ms": float
            }
        }
    """
```

---

## Valid Services and Actions

| Service | Valid Actions |
|---------|---------------|
| `scoring` | rank, score, weights, reset, config |
| `feedback` | submit, list, export |
| `market` | signal, trends, forecast, gap |
| `explain` | run, get, history |
| `recommend` | full, quick |
| `pipeline` | run, status |
| `crawlers` | start, stop, status |
| `eval` | run, get, baselines |
| `rules` | evaluate, get, reload |
| `taxonomy` | resolve, get, detect |
| `kb` | get, list, search |
| `chat` | message, history |
| `mlops` | train, deploy, rollback |
| `governance` | approve, reject, status |
| `liveops` | command, status |

---

## Service Handlers

Each service/action combination maps to a handler method:

```python
self.handlers: Dict[Tuple[str, str], Callable] = {
    # Scoring handlers
    ("scoring", "rank"): self._handle_scoring_rank,
    ("scoring", "score"): self._handle_scoring_score,
    ("scoring", "weights"): self._handle_scoring_weights,
    ("scoring", "reset"): self._handle_scoring_reset,
    ("scoring", "config"): self._handle_scoring_config,
    
    # Feedback handlers
    ("feedback", "submit"): self._handle_feedback_submit,
    ("feedback", "list"): self._handle_feedback_list,
    
    # Market handlers
    ("market", "signal"): self._handle_market_signal,
    ("market", "trends"): self._handle_market_trends,
    
    # ... additional handlers
}
```

---

## Handler Example: Scoring Rank

```python
async def _handle_scoring_rank(
    self,
    payload: Dict[str, Any],
    context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Handle scoring rank request.
    
    Payload:
        - user_id: str
        - skills: List[str]
        - interests: List[str]
        - weights: Optional[Dict]
        - limit: Optional[int]
        
    Returns:
        - careers: List[CareerMatch]
        - profile_id: str
        - timestamp: str
    """
    # Create domain model from payload
    profile = UserProfile(
        user_id=payload.get("user_id", context.get("user_id", "anonymous")),
        skills=payload.get("skills", []),
        interests=payload.get("interests", []),
        weights=payload.get("weights")
    )
    
    # Call scoring service
    result = await self.scoring_service.rank_careers(
        profile=profile,
        limit=payload.get("limit", 10)
    )
    
    # Convert to serializable response
    return {
        "careers": [career.to_dict() for career in result.careers],
        "profile_id": str(profile.user_id),
        "timestamp": datetime.utcnow().isoformat()
    }
```

---

## Error Handling

```python
try:
    result = await self._dispatch_to_service(service, action, payload, ctx)
except Exception as e:
    await self._dispatch_log_error(service, action, e, ctx)
    raise HTTPException(status_code=500, detail=str(e))
```

---

## Context Structure

```python
context = {
    "correlation_id": "uuid-string",     # Request correlation
    "user_id": "user-123",               # Authenticated user
    "auth_token": "Bearer xxx",          # Auth header
    "source": "api|cli|internal",        # Request source
    "timestamp": "2026-01-15T...",       # Request time
}
```

---

## Enforcement Rules

### MUST DO:
1. ✅ All routers call `controller.dispatch()`
2. ✅ Pass service name and action
3. ✅ Include full payload
4. ✅ Include request context

### MUST NOT:
1. ❌ Import service classes directly
2. ❌ Instantiate services in routers
3. ❌ Bypass the 8-step pipeline
4. ❌ Skip authentication/authorization

---

## Integration Example

### Router → Controller

```python
@router.post("/rank")
async def rank_careers(
    request: RankRequest,
    controller: MainController = Depends(get_controller)
):
    return await controller.dispatch(
        service="scoring",
        action="rank",
        payload=request.model_dump(),
        context={"user_id": request.user_id}
    )
```

---

## Testing

Controller enforcement is tested by:
- `tests/test_controller_enforcement.py` - Static analysis
- `tests/test_main_controller.py` - Unit tests
- `tests/integration/test_dispatch.py` - Integration tests

Run enforcement check:
```bash
python tests/test_controller_enforcement.py
```

---

*Maintained by Architecture Team - Last Updated: 2026-01-15*
