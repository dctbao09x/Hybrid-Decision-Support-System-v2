# RUNBOOK_LIVE_OPS.md
## Live Ops Runbook

### Overview

This runbook provides operational procedures for the Live Ops Integration Layer.

---

## 1. Daily Operations

### 1.1 System Health Check

**Frequency**: Every morning, 9:00 AM

**Steps**:
1. Open Admin Dashboard → Live Ops → System Health Widget
2. Verify all services show "healthy" status
3. Check job queue backlog < 100 items
4. Verify error rate < 1%
5. Review overnight alerts in Slack #ops-alerts

**If issues found**:
- Follow relevant incident procedure below
- Escalate to on-call if critical

### 1.2 Command History Review

**Frequency**: Daily

**Steps**:
1. Open Admin Dashboard → Live Ops → Command History
2. Filter by last 24 hours
3. Review any failed commands
4. Check approval queue for pending items

---

## 2. Common Procedures

### 2.1 Kill Crawler

**When**: Crawler consuming excessive resources or stuck

**UI Steps**:
1. Open Admin Dashboard → Live Ops → Command Panel
2. Select "Kill Crawler" command
3. Enter site_name (e.g., "newssite_prod")
4. Enable "Dry Run" to preview impact
5. Review simulation result
6. Disable dry run, click Execute
7. Wait for confirmation
8. Verify crawler stopped in Job Queue widget

**CLI Alternative** (emergency only):
```bash
curl -X POST https://api.example.com/api/v1/live/crawler/kill \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"site_name": "newssite_prod", "reason": "Resource exhaustion"}'
```

### 2.2 Pause/Resume Jobs

**When**: Need to temporarily halt processing

**UI Steps**:
1. Open Admin Dashboard → Live Ops → Command Panel
2. Select "Pause Job" command
3. Enter job_id from Job Queue widget
4. Add reason for audit
5. Click Execute
6. Verify job shows "paused" status

**To Resume**:
1. Select "Resume Job" command
2. Enter same job_id
3. Execute

### 2.3 Knowledge Base Rollback

**When**: Bad data ingested, need to restore previous version

**⚠️ CRITICAL OPERATION - Requires Approval**

**Pre-requisites**:
- Identify target version from KB version history
- Notify dependent services
- Schedule maintenance window

**UI Steps**:
1. Open Admin Dashboard → Live Ops → Command Panel
2. Select "Rollback KB" command
3. Enter version (format: "v2024.01.15")
4. Enable backup_current = true
5. Add detailed reason
6. Enable Dry Run first
7. Review impact analysis
8. Disable dry run, Execute
9. Wait for approval notification
10. Second admin approves via Approval Queue
11. Monitor progress in Job Queue

**Post-Rollback**:
- Verify KB integrity via health check
- Notify dependent services
- Update incident ticket

### 2.4 Freeze/Unfreeze Model

**When**: Model producing bad predictions, need to halt updates

**UI Steps**:
1. Open Admin Dashboard → Live Ops → Command Panel
2. Select "Freeze Model" command
3. Enter model_id (e.g., "scoring_model_v3")
4. Set duration_hours (0 = indefinite)
5. Add reason
6. Execute
7. Wait for approval if production model

**To Unfreeze**:
- Set duration_hours = 0 and re-execute with "unfreeze" in reason

### 2.5 Trigger Model Retrain

**When**: Drift detected or scheduled retraining

**UI Steps**:
1. Open Admin Dashboard → Live Ops → Command Panel
2. Select "Retrain Model" command
3. Enter model_id
4. Optionally specify dataset_version
5. Set priority (high for urgent)
6. Execute
7. Monitor in Job Queue widget

---

## 3. Incident Response

### 3.1 High Error Rate

**Indicators**:
- Error Rate widget shows > 5%
- Slack alert from monitoring

**Response**:
1. Check Error Rate widget for top error codes
2. Identify affected service
3. Check service logs in Kibana
4. If crawler issue → Kill Crawler procedure
5. If model issue → Freeze Model procedure
6. If KB issue → Consider rollback
7. Update incident ticket
8. Post-mortem within 24 hours

### 3.2 Job Queue Backlog

**Indicators**:
- Job Queue widget shows queued > 500
- Processing rate dropping

**Response**:
1. Identify bottleneck service
2. Check for stuck jobs (running > 1 hour)
3. Kill stuck jobs if necessary
4. Scale up workers if available
5. Consider pausing non-critical jobs
6. Monitor until backlog < 100

### 3.3 Model Drift Detected

**Indicators**:
- Drift widget shows drift_score > 0.3
- model_drift_detected = true

**Response**:
1. Review drift metrics detail
2. Check input data distribution
3. If data issue → Fix data pipeline
4. If model degradation → Trigger retrain
5. Consider freezing model if predictions critical
6. Schedule model review meeting

### 3.4 Circuit Breaker Triggered

**Indicators**:
- Command execution fails with "circuit open"
- Service showing degraded in Health widget

**Response**:
1. Identify affected service
2. Check service health directly
3. Wait for circuit reset (default 60s)
4. If persists, investigate service logs
5. Manual service restart if necessary
6. Verify circuit recovers

### 3.5 WebSocket Connection Issues

**Indicators**:
- Dashboard shows "Disconnected"
- Users report stale data

**Response**:
1. Check API server health
2. Verify WebSocket endpoint accessible
3. Check for firewall/proxy issues
4. Review connection limits
5. Restart API server if necessary
6. Users can force reconnect via UI

---

## 4. Approval Procedures

### 4.1 Approve Command

**When**: Command requires approval

**Steps**:
1. Receive notification (Slack/email)
2. Review command details in Approval Queue
3. Verify requester and reason
4. Check impact analysis
5. Approve or Deny with comment
6. For dual approval, wait for second approver

### 4.2 Emergency Override

**When**: Critical situation, normal approval too slow

**Requirements**:
- superadmin role
- MFA verification
- Documented emergency reason

**Steps**:
1. Use emergency override button
2. Complete MFA challenge
3. Enter detailed emergency justification
4. Execute command
5. Automatic security alert generated
6. Post-incident review required within 24 hours

---

## 5. Testing Procedures

### 5.1 Dry Run Mode

**Purpose**: Test command impact without execution

**Steps**:
1. Enable "Dry Run" checkbox in Command Panel
2. Execute command
3. Review simulation result:
   - Execution steps
   - Estimated duration
   - Impact analysis
   - Validation errors/warnings
4. Adjust parameters if needed
5. Disable dry run for actual execution

### 5.2 Chaos Testing (Staging Only)

**Purpose**: Test system resilience

**Pre-requisites**:
- superadmin role
- Staging environment only
- Notify team before testing

**Steps**:
1. Open Admin Dashboard → Live Ops → Chaos Testing
2. Select scenario (latency, failure, timeout)
3. Configure parameters
4. Start test
5. Monitor system behavior
6. Verify recovery after test ends
7. Document results

---

## 6. Monitoring & Alerts

### 6.1 Dashboard Widgets

| Widget | Refresh | Alert Threshold |
|--------|---------|-----------------|
| System Health | 10s | Any service unhealthy |
| Job Queue | 5s | Queued > 500 or failed > 10 |
| Drift | 1min | Score > 0.3 |
| Cost | 5min | > 80% budget |
| SLA | 30s | < 99.5% or violation |
| Error Rate | 10s | > 5% |

### 6.2 Alert Channels

- **Slack**: #ops-alerts (all alerts)
- **Email**: On-call group (critical only)
- **PagerDuty**: Critical incidents

### 6.3 Alert Response Times

| Severity | Response SLA |
|----------|-------------|
| Critical | 15 minutes |
| High | 1 hour |
| Medium | 4 hours |
| Low | Next business day |

---

## 7. Contacts & Escalation

### On-Call Schedule
See PagerDuty: Live Ops team

### Escalation Path
1. On-call engineer (L1)
2. Senior engineer (L2) - 30 min escalation
3. Engineering manager (L3) - 1 hour escalation
4. CTO (L4) - Critical incidents only

### Slack Channels
- #ops-alerts - Automated alerts
- #ops-discussion - Team discussion
- #incidents - Active incident coordination

---

## 8. Change Log

| Date | Change | Author |
|------|--------|--------|
| 2024-XX-XX | Initial version | Ops Team |
