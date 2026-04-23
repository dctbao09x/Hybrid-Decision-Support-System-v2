# LiveOps Operations Runbook

**Version**: 1.0  
**Last Updated**: 2026-01-XX  
**Classification**: Operations - Production

---

## Quick Reference

### API Base URL
- Development: `http://127.0.0.1:8000`
- Production: `https://api.hdss.internal`

### Critical Paths
- WebSocket: `/api/v1/live/ws?token={jwt}`
- Health: `/api/v1/widgets/health-status`
- Command Status: `/api/v1/ops/commands/{id}`

---

## 1. Service Startup

### Start API Server

```powershell
cd "F:\Hybrid Decision Support System"
.\venv\Scripts\python.exe -m uvicorn backend.run_api:app --host 0.0.0.0 --port 8000
```

### Verify Service

```powershell
# Health check
curl http://localhost:8000/api/v1/widgets/health-status

# Auth check
curl -H "Authorization: Bearer {token}" http://localhost:8000/api/v1/ops/commands
```

---

## 2. Common Operations

### 2.1 Kill a Crawler

**Prerequisites**: 
- Valid JWT token with `operator` or `admin` role
- HMAC signature

```javascript
// Frontend service call
await liveOpsService.killCrawler({
  site_name: "bloomberg",
  force: false,
  reason: "Timeout exceeded"
});
```

**Backend equivalent**:
```python
from backend.ops.command_engine.engine import CommandEngine
engine = CommandEngine()
await engine.submit(
    command_type="crawler/kill",
    target="bloomberg",
    user_id="operator@example.com",
    params={"force": False}
)
```

### 2.2 Pause/Resume Jobs

```javascript
// Pause
await liveOpsService.pauseJob({ job_id: "job-12345" });

// Resume
await liveOpsService.resumeJob({ job_id: "job-12345" });
```

### 2.3 Knowledge Base Rollback

```javascript
await liveOpsService.rollbackKB({
  version: "2026-01-15-snapshot",
  backup_current: true,
  reason: "Data corruption detected"
});
```

**Approval Required**: Yes (for production)

### 2.4 Model Freeze

```javascript
await liveOpsService.freezeModel({
  model_id: "drift-detector-v2",
  reason: "Performance degradation"
});
```

### 2.5 Trigger Retrain

```javascript
await liveOpsService.retrainModel({
  model_id: "sentiment-classifier",
  config_override: { epochs: 50 }
});
```

---

## 3. Monitoring & Observability

### 3.1 Dashboard Widgets

```bash
# System health
GET /api/v1/widgets/health-status

# Model drift
GET /api/v1/widgets/drift-summary

# Cost breakdown
GET /api/v1/widgets/cost-breakdown

# SLA metrics
GET /api/v1/widgets/sla-metrics

# Error aggregation
GET /api/v1/widgets/top-errors

# Queue depth
GET /api/v1/widgets/queue-depth
```

### 3.2 WebSocket Events

Connect and subscribe:
```javascript
const ws = new WebSocket(`wss://api.hdss.internal/api/v1/live/ws?token=${jwt}`);
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`Event: ${data.event_type}`, data);
};
```

Event types:
| Event | Description |
|-------|-------------|
| `command.queued` | Command added to queue |
| `command.started` | Execution began |
| `command.progress` | Progress update (0-100%) |
| `command.completed` | Execution finished |
| `command.failed` | Execution failed |
| `system.alert` | System-level alert |
| `circuit.tripped` | Circuit breaker opened |

### 3.3 Audit Log Inspection

```powershell
# Tail recent entries
Get-Content backend/ops/command_engine/audit.log -Tail 20 | ConvertFrom-Json

# Verify hash chain integrity
python -c "
import json
from hashlib import sha256

with open('backend/ops/command_engine/audit.log') as f:
    lines = f.readlines()

prev = None
for line in lines:
    entry = json.loads(line)
    if prev and entry.get('prev_hash') != prev:
        print(f'BROKEN CHAIN at {entry[\"entry_id\"]}')
        break
    prev = entry.get('entry_hash')
else:
    print(f'Chain intact: {len(lines)} entries')
"
```

---

## 4. Troubleshooting

### 4.1 Command Stuck in Queue

**Symptoms**: Command status shows `pending` for extended time

**Resolution**:
```python
from backend.ops.command_engine.dispatcher import dispatcher

# Check circuit breaker status
print(dispatcher.circuit_state)

# Force reset if needed
dispatcher.reset_circuit()

# Manual dequeue if stuck
dispatcher.dequeue_command(command_id)
```

### 4.2 WebSocket Disconnects

**Symptoms**: Clients losing connection, events not delivered

**Checklist**:
1. Verify JWT token not expired
2. Check server logs for `AuthError`
3. Ensure `LIVEOPS_SIGNING_SECRET` matches frontend

**Force reconnect from client**:
```javascript
liveOpsService.reconnectWebSocket();
```

### 4.3 HMAC Signature Failures

**Symptoms**: 401 Unauthorized on command endpoints

**Debug**:
```python
from backend.ops.security.command_signing import verifier
import time

result = verifier.verify(
    user_id="test@example.com",
    command_type="crawler/kill",
    target="bloomberg",
    timestamp=int(time.time()),
    nonce="test-nonce-12345678",
    signature="computed-signature-here"
)
print(f"Signature valid: {result}")
```

**Common causes**:
- Timestamp drift > 300 seconds
- Nonce reused
- Secret mismatch between frontend/backend

### 4.4 Audit Hash Chain Broken

**Symptoms**: Daily checksum validation fails

**Resolution**:
```python
# Identify break point
python -c "
import json
with open('backend/ops/command_engine/audit.log') as f:
    lines = f.readlines()

prev = None
for i, line in enumerate(lines):
    entry = json.loads(line)
    if prev and entry.get('prev_hash') != prev:
        print(f'Break at line {i+1}: {entry[\"entry_id\"]}')
    prev = entry['entry_hash']
"
```

**Recovery**: Contact security team - potential tampering

---

## 5. Emergency Procedures

### 5.1 Kill All Running Commands

```python
from backend.ops.command_engine.engine import CommandEngine
engine = CommandEngine()
await engine.emergency_stop_all()
```

### 5.2 Disable LiveOps Endpoints

Edit `backend/api/router_registry.py`:
```python
# Temporary emergency disable:
# LIVEOPS_ROUTERS = []

# Or comment out this entry in LIVEOPS_ROUTERS:
# RouterInfo(name="liveops", router=liveops_router, prefix="/api/v1/live", ...)
```

Restart service.

### 5.3 Circuit Breaker Manual Trip

```python
from backend.ops.command_engine.dispatcher import dispatcher
dispatcher.trip_circuit("Manual trip - incident investigation")
```

---

## 6. Maintenance Tasks

### 6.1 Rotate Signing Secret

1. Generate new secret:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. Update environment:
   ```bash
   export LIVEOPS_SIGNING_SECRET="new-secret-here"
   ```

3. Update frontend config
4. Restart all services
5. Verify with test command

### 6.2 Archive Audit Logs

```powershell
# Monthly archive
$date = Get-Date -Format "yyyy-MM"
Copy-Item backend/ops/command_engine/audit.log "archive/audit-$date.log"

# Compress
Compress-Archive "archive/audit-$date.log" "archive/audit-$date.zip"

# Clear (keep last 1000 entries)
(Get-Content backend/ops/command_engine/audit.log -Tail 1000) | Set-Content backend/ops/command_engine/audit.log
```

### 6.3 Database Maintenance

```sql
-- Vacuum SQLite queue
sqlite3 backend/ops/command_engine/command_queue.db "VACUUM;"

-- Archive completed commands
sqlite3 backend/ops/command_engine/command_queue.db "
  INSERT INTO command_archive SELECT * FROM command_queue WHERE status IN ('completed','failed');
  DELETE FROM command_queue WHERE status IN ('completed','failed');
"
```

---

## 7. Contact & Escalation

| Level | Contact | Response Time |
|-------|---------|---------------|
| L1 | Operations Team | 15 min |
| L2 | Backend Engineering | 30 min |
| L3 | Security Team | 1 hour |

---

**Document Owner**: SRE Team  
**Review Cycle**: Quarterly
