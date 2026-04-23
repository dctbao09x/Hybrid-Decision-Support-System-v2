# OPS_SECURITY.md
## Live Ops Security Guidelines

### 1. Authentication & Authorization

#### JWT Token Requirements
- All LiveOps API endpoints require valid JWT token
- Token must be included in `Authorization: Bearer <token>` header
- WebSocket connections authenticate via initial handshake message

#### Role-Based Access Control (RBAC)

| Role | Permissions |
|------|-------------|
| `viewer` | Read-only access to dashboards and command history |
| `operator` | Execute non-destructive commands (pause/resume jobs) |
| `admin` | Full command execution including destructive operations |
| `superadmin` | Approve commands, manage policies, chaos testing |

#### Permission Matrix

| Command | viewer | operator | admin | superadmin |
|---------|--------|----------|-------|------------|
| View dashboards | ✅ | ✅ | ✅ | ✅ |
| View command history | ✅ | ✅ | ✅ | ✅ |
| Pause/Resume jobs | ❌ | ✅ | ✅ | ✅ |
| Kill crawler | ❌ | ❌ | ✅ | ✅ |
| Freeze model | ❌ | ❌ | ✅ | ✅ |
| KB rollback | ❌ | ❌ | ✅* | ✅ |
| Model retrain | ❌ | ❌ | ✅ | ✅ |
| Approve commands | ❌ | ❌ | ❌ | ✅ |
| Chaos testing | ❌ | ❌ | ❌ | ✅ |
| Policy management | ❌ | ❌ | ❌ | ✅ |

*Requires approval for production scope

### 2. Command Safety Policies

#### Policy Engine Rules

```python
# Production scope requires approval
if command.scope == "production" and command.type in ["crawler_kill", "kb_rollback"]:
    require_approval(approvers=2, timeout_minutes=30)

# Rate limiting per user
max_commands_per_minute = 10
max_destructive_per_hour = 5

# Time restrictions
restricted_hours = ["02:00-06:00"]  # No destructive ops during maintenance
```

#### Approval Workflow

1. **Single Approval**: Non-critical production commands
   - Timeout: 30 minutes
   - Auto-escalation after timeout

2. **Dual Approval**: Critical operations (KB rollback, model freeze)
   - Requires 2 different approvers
   - Timeout: 60 minutes
   - No auto-approval

3. **Emergency Override**: Only superadmin with MFA
   - Logs emergency reason
   - Triggers security alert

### 3. Audit & Compliance

#### Audit Log Contents

Every command execution logs:
- Timestamp (UTC)
- User ID and role
- Command type and parameters
- Target resource
- IP address and user agent
- Approval chain (if applicable)
- Result (success/failure)
- Duration

#### Log Retention

| Log Type | Retention |
|----------|-----------|
| Command audit | 1 year |
| Approval audit | 2 years |
| Security events | 3 years |
| Error logs | 90 days |

#### Compliance Requirements

- All destructive commands require reason field
- Audit logs are append-only
- Log integrity verified via checksums
- PII redacted from logs

### 4. Network Security

#### WebSocket Security

```yaml
# Connection requirements
tls_required: true
origin_whitelist:
  - "https://admin.example.com"
  - "https://ops.example.com"

# Connection limits
max_connections_per_user: 3
idle_timeout_seconds: 300
ping_interval_seconds: 30
```

#### API Rate Limiting

| Endpoint Category | Rate Limit |
|------------------|------------|
| Read endpoints | 100/minute |
| Write endpoints | 20/minute |
| Destructive commands | 5/hour |
| WebSocket messages | 50/minute |

### 5. Incident Response

#### Automatic Escalation Triggers

- Failed login attempts > 5 in 10 minutes
- Command failure rate > 20% in 5 minutes
- Circuit breaker triggered
- Chaos testing outside sandbox
- Unauthorized command attempt

#### Response Actions

1. **Alert**: Notify on-call via PagerDuty/Slack
2. **Block**: Temporary IP/user block
3. **Audit**: Enhanced logging enabled
4. **Rollback**: Automatic rollback if configured

### 6. Secrets Management

#### Sensitive Data Handling

- API keys stored in HashiCorp Vault
- Database credentials rotated every 30 days
- JWT signing keys rotated every 90 days
- Webhook secrets per-integration

#### Environment Isolation

```yaml
environments:
  development:
    allow_chaos_testing: true
    approval_required: false
    
  staging:
    allow_chaos_testing: true
    approval_required: true
    auto_approve_timeout: 15m
    
  production:
    allow_chaos_testing: false  # Only in sandbox
    approval_required: true
    auto_approve_timeout: never
```

### 7. Security Checklist

#### Pre-Deployment

- [ ] TLS certificates valid and not expiring within 30 days
- [ ] JWT signing keys rotated
- [ ] RBAC policies reviewed
- [ ] Audit logging enabled
- [ ] Rate limiting configured
- [ ] Origin whitelist updated

#### Post-Incident

- [ ] Root cause analysis completed
- [ ] Audit logs preserved
- [ ] Affected users notified
- [ ] Security patches applied
- [ ] Policy updates implemented
- [ ] Post-mortem documented

### 8. Contact Information

#### Security Team
- Email: security@example.com
- Slack: #security-ops
- PagerDuty: Live Ops Security

#### Emergency Contacts
- Security Lead: [Name] - [Phone]
- Platform Lead: [Name] - [Phone]
- On-Call: See PagerDuty schedule
