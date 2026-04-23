# Access Control Policy
## GĐ2 - ANTI-BYPASS & CONTROL ENFORCEMENT

**Version:** 1.0  
**Effective Date:** 2026-02-17  
**Classification:** INTERNAL  

---

## 1. PURPOSE

This policy defines access control rules for the SIMGR scoring system,
ensuring all scoring operations go through authorized channels only.

---

## 2. SCOPE

This policy applies to:
- All API requests to scoring endpoints
- All internal scoring operations
- All background jobs accessing scoring
- All test/debug access to scoring core

---

## 3. ACCESS LAYERS

### 3.1 Allowed Access Path

```
┌─────────────────────────────────────────────────────────────┐
│                     PUBLIC INTERNET                          │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              API LAYER (with RBAC)                          │
│         /api/v1/scoring/*, /api/v1/recommendations          │
└───────────────────────────┬─────────────────────────────────┘
                            │ Authenticated
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  FIREWALL LAYER                              │
│            Blocks: /_internal/*, /debug/*, /test/*          │
└───────────────────────────┬─────────────────────────────────┘
                            │ Allowed paths only
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              CONTROLLER LAYER                                │
│              MainController.dispatch()                       │
│              Issues: control_token                           │
└───────────────────────────┬─────────────────────────────────┘
                            │ Token + Caller validated
                            ▼
┌─────────────────────────────────────────────────────────────┐
│               SCORING CORE                                   │
│     RankingEngine, SIMGRCalculator, SIMGRScorer             │
│     Protected by: @enforce_controller_only                   │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Blocked Access Paths

| Source | Target | Status | Reason |
|--------|--------|--------|--------|
| API Direct | Scoring Core | ❌ BLOCKED | Must use controller |
| Scripts | Scoring Core | ❌ BLOCKED | No auth context |
| Background Jobs | Scoring Core | ❌ BLOCKED | No controller |
| CLI Tools | Scoring Core | ❌ BLOCKED | No token |
| Notebooks | Scoring Core | ❌ BLOCKED | Unauthorized import |

---

## 4. AUTHENTICATION & AUTHORIZATION

### 4.1 Authentication
- All API requests MUST be authenticated
- Session tokens validated by RBAC middleware
- Anonymous access = DENIED

### 4.2 Authorization (RBAC)
- READ: Admin, Ops, Auditor, Analyst
- WRITE: Admin, Ops
- EXECUTE: Admin, Ops, API_User

---

## 5. CONTROL TOKEN

### 5.1 Token Generation
```
token = HMAC-SHA256(secret, request_id + timestamp)
```

### 5.2 Token Lifecycle
1. MainController generates token on dispatch
2. Token injected into scoring context
3. Scoring core verifies token
4. Token expires after 5 minutes

### 5.3 Token Validation Rules
- ✓ HMAC signature must match
- ✓ Request ID must match
- ✓ Token must not be expired
- ✓ Issuer must be MainController

---

## 6. RUNTIME GUARDS

### 6.1 Call Stack Inspection
All scoring core methods inspect call stack to verify:
- Caller is from allowed module
- Controller pattern in stack
- No unauthorized bypasses

### 6.2 Allowed Caller Patterns
```python
ALLOWED_CALLER_PATTERNS = [
    "main_controller.py",
    "MainController",
    "dispatch",
    "scoring_service",
]
```

### 6.3 Blocked Callers
- Direct script invocation
- Background task workers
- CLI tools
- Jupyter notebooks

---

## 7. API FIREWALL

### 7.1 Blocked Endpoints
- `/_internal/*` - Internal endpoints
- `/debug/*` - Debug endpoints
- `/test/*` - Test endpoints
- `/admin/*/score` - Admin scoring bypass

### 7.2 Allowed Endpoints
- `/api/v1/*` - Production API
- `/health` - Health check
- `/docs`, `/redoc` - Documentation

---

## 8. AUDIT LOGGING

### 8.1 Required Fields
Every scoring operation logs:
- `request_id` - Unique request identifier
- `caller` - Calling function
- `token_hash` - First 16 chars of token
- `weight_version` - Weight version used
- `latency` - Operation duration
- `status` - SUCCESS/BLOCKED/ERROR

### 8.2 Log Format
```
[CONTROL_TRACE] ts=... req=... caller=... token=... weights=... op=... latency=... status=...
```

---

## 9. VIOLATIONS

### 9.1 Bypass Attempt
- Logged with full stack trace
- Request blocked immediately
- Alert generated (if configured)

### 9.2 Invalid Token
- Token verification failed
- Request blocked
- Logged as security event

### 9.3 Unauthorized Caller
- Caller not in whitelist
- BypassAttemptError raised
- Operation terminated

---

## 10. EXCEPTIONS

### 10.1 Test Mode
Test harness can enable `test_mode` to bypass guards.
- ONLY for automated testing
- MUST be disabled in production
- Logged as warning

### 10.2 Emergency Override
No emergency override exists.
All scoring MUST go through controller.

---

## 11. COMPLIANCE

This policy implements:
- GĐ2 Anti-Bypass requirements
- Zero implicit trust principle
- Defense in depth architecture
- Audit trail requirements

---

**Document End**  
Last Updated: 2026-02-17  
Approved By: Principal System Security & Control Architect
