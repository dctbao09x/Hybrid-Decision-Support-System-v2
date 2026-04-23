# LIVEOPS_REMEDIATION_REPORT_2026.md

## Remediation ID
`liveops-remediation-2026`

## Summary
This remediation fixes the FAIL findings from the prior LiveOps audit with minimal refactor and no full rewrite.

## Implemented Fixes

### 1) Router & Mount Fix
- Mounted LiveOps router on unified gateway:
  - `app.include_router(liveops_router, prefix="/api/v1/live", dependencies=[Depends(auth_admin)])`
- Mounted websocket endpoint:
  - `/ws/live`
- Added LiveOps health endpoint: `GET /api/v1/live/health`

### 2) Auth & RBAC Enforcement
- Added reusable role dependency: `require_role([...])`
- Added websocket auth verifier: `auth_admin_websocket(...)`
- Enforced role checks on command endpoints and approval endpoint.

### 3) Command Signing + Nonce
- Added required fields to command requests:
  - `nonce`, `timestamp`, `signature`
- Added backend verifier:
  - HMAC-SHA256 validation
  - timestamp window validation
  - nonce replay protection

### 4) Command Pipeline Wiring
- Integrated `SafetyPolicyEngine` check in `CommandEngine.submit(...)`
- Integrated `ApprovalWorkflow` with pending approval state and approve API path
- Added command listing and approval methods in engine

### 5) Queue Persistence + Backpressure
- Added SQLite WAL queue persistence in dispatcher (`storage/liveops_queue.db`)
- Added backpressure controls:
  - `max_queue_size`
  - `drop_policy` (`reject_new` / `drop_low_priority`)

### 6) Audit Immutability
- Added tamper-evident hash chain fields in audit entry:
  - `prev_hash`, `entry_hash`
- Added daily rolling checksum file:
  - `logs/admin_ops/audit_checksum_YYYYMMDD.sha256`

### 7) Frontend Recovery
- Added missing `service.ts` for LiveOps module
- Added API adapters for commands/widgets/approve/list
- Added signed command request generation in frontend
- Frontend build verified: `npm run build` PASS

### 8) Contract Sync
- Synced `config/ops.yaml` with implemented endpoints:
  - Added `/health`
  - Updated path parameter names for `/commands/{command_id}` routes

### 9) Test Plan + Automation
- Added `TEST_PLAN_LIVEOPS.md`
- Added backend integration tests:
  - `backend/tests/liveops/test_liveops_integration.py`
- Added frontend integration tests:
  - `ui-vite/tests/integration/liveops.spec.ts`

## Verification Snapshot
- `GET /api/v1/live/health` -> 200 (with auth)
- `GET /api/v1/live/poll` -> 200 (with auth)
- `POST /api/v1/live/crawler/kill` -> reachable and processed (no 404)
- LiveOps router mount log present in runtime initialization
- `POST /api/v1/live/job/pause` (signed, dry-run) -> 200 and command `state=done`
- `POST /api/v1/live/job/pause` (invalid signature) -> 403
- Evidence log updated: `deploy_logs/liveops_verification_20260215.log`

## Gate Result
- Status: **PASS**
- Criteria satisfied:
  - LiveOps endpoints mounted and reachable (no 404)
  - HTTP + WS auth/RBAC enforced
  - Signed command protocol (HMAC + nonce + timestamp) enforced
  - End-to-end command pipeline wired (policy/approval/queue/executor/audit)
  - Frontend LiveOps integration restored and tests/build passing
  - Integration tests passing (backend + frontend)

## Notes
- Websocket auth is enforced via token query/header and role gate.
- Approval behavior is now active for protected commands.
- Queue is persisted in SQLite WAL mode to survive process restart.
- Audit logs are now tamper-evident at record level.
