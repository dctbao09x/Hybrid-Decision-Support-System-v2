# LIVEOPS_ARCHITECTURE.md
## GIAI ĐOẠN C.1 — Live Ops Integration Layer Architecture

```mermaid
flowchart TB
    subgraph UI["Admin UI Layer"]
        direction TB
        Dashboard["LiveDashboard"]
        CCP["CommandControlPanel"]
        Widgets["Dashboard Widgets"]
        
        Dashboard --> Widgets
        Dashboard --> CCP
    end
    
    subgraph Channel["Realtime Channel"]
        direction TB
        WS["WebSocket"]
        SSE["Server-Sent Events"]
        Poll["Polling Fallback"]
        LC["LiveChannel Client"]
        
        LC --> WS
        LC --> SSE
        LC --> Poll
    end
    
    subgraph API["API Gateway"]
        direction TB
        Router["liveops_router.py"]
        ConnMgr["ConnectionManager"]
        
        Router --> ConnMgr
    end
    
    subgraph Engine["Command Engine"]
        direction TB
        CE["CommandEngine"]
        Validator["Validator"]
        Dispatcher["Dispatcher"]
        Executor["Executor"]
        Audit["AuditLogger"]
        Notifier["Notifier"]
        
        CE --> Validator
        Validator --> Dispatcher
        Dispatcher --> Executor
        Executor --> Audit
        Executor --> Notifier
    end
    
    subgraph Governance["Safety & Governance"]
        direction TB
        SPE["SafetyPolicyEngine"]
        AW["ApprovalWorkflow"]
        RBAC["RBAC"]
        
        SPE --> RBAC
        AW --> SPE
    end
    
    subgraph Recovery["Failure Recovery"]
        direction TB
        FH["FailureHandler"]
        Incident["IncidentReport"]
        
        FH --> Incident
    end
    
    subgraph Testing["Testing & Simulation"]
        direction TB
        Sandbox["OpsSandbox"]
        Chaos["ChaosEngine"]
        Sim["CommandSimulator"]
    end
    
    subgraph Backend["Backend Services"]
        direction TB
        Crawlers["Crawlers"]
        MLOps["MLOps"]
        KB["Knowledge Base"]
        Pipeline["Data Pipeline"]
    end
    
    UI --> Channel
    Channel --> API
    API --> Engine
    Engine --> Governance
    Engine --> Recovery
    Engine --> Backend
    Testing --> Engine
```

## Data Flow

```mermaid
sequenceDiagram
    participant Admin as Admin UI
    participant LC as LiveChannel
    participant API as API Gateway
    participant CE as CommandEngine
    participant Val as Validator
    participant Disp as Dispatcher
    participant Exec as Executor
    participant Gov as Governance
    participant Audit as AuditLogger
    participant Backend as Backend Service
    
    Admin->>LC: Subscribe to module
    LC->>API: WS Connect
    API-->>LC: Connection ACK
    
    Admin->>LC: Execute Command
    LC->>API: POST /api/v1/live/{command}
    API->>CE: Submit command
    
    CE->>Val: Validate
    Val->>Val: Check idempotency
    Val->>Val: Check rate limit
    Val-->>CE: Validation result
    
    CE->>Gov: Check policy
    Gov->>Gov: Evaluate rules
    Gov-->>CE: Policy decision
    
    alt Approval Required
        CE->>Gov: Request approval
        Gov-->>Admin: Approval request
        Admin->>Gov: Approve
        Gov-->>CE: Approved
    end
    
    CE->>Disp: Queue command
    Disp->>Disp: Priority queue
    Disp->>Exec: Execute
    
    Exec->>Backend: Call service
    Backend-->>Exec: Result
    
    Exec->>Audit: Log result
    
    CE-->>API: Command result
    API-->>LC: Push via WS
    LC-->>Admin: Update UI
```

## Command State Machine

```mermaid
stateDiagram-v2
    [*] --> PENDING: Submit
    PENDING --> VALIDATING: Process
    VALIDATING --> REJECTED: Validation failed
    VALIDATING --> AWAITING_APPROVAL: Approval required
    VALIDATING --> QUEUED: Validation passed
    AWAITING_APPROVAL --> QUEUED: Approved
    AWAITING_APPROVAL --> REJECTED: Denied
    QUEUED --> RUNNING: Execute
    RUNNING --> DONE: Success
    RUNNING --> FAILED: Error
    FAILED --> RECOVERING: Auto recovery
    RECOVERING --> DONE: Recovery success
    RECOVERING --> ROLLED_BACK: Rollback executed
    ROLLED_BACK --> [*]
    DONE --> [*]
    REJECTED --> [*]
```

## Module Structure

```
backend/ops/
├── command_engine/
│   ├── __init__.py
│   ├── models.py        # Command, CommandState, CommandResult
│   ├── validator.py     # CommandValidator - idempotency, rate limiting
│   ├── dispatcher.py    # CommandDispatcher - priority queue, circuit breaker
│   ├── executor.py      # CommandExecutor - retry, timeout, rollback
│   ├── audit.py         # CommandAudit - JSONL logging
│   ├── notifier.py      # CommandNotifier - multi-channel notifications
│   └── engine.py        # CommandEngine - main orchestrator
│
├── governance/
│   ├── __init__.py
│   ├── safety_policy.py    # SafetyPolicyEngine - policy evaluation
│   └── approval_workflow.py # ApprovalWorkflow - multi-approver support
│
├── recovery/
│   ├── __init__.py
│   └── failure_handler.py  # FailureHandler - recovery, compensation
│
└── testing/
    ├── __init__.py
    ├── sandbox.py      # OpsSandbox - isolated testing
    ├── chaos.py        # ChaosEngine - chaos testing
    └── simulator.py    # CommandSimulator - dry-run

backend/api/routers/
└── liveops_router.py   # All LiveOps API endpoints

ui-vite/src/admin-ui/
├── interface/
│   └── liveChannel.ts  # WebSocket/SSE/Polling client
│
└── modules/liveops/
    ├── index.ts
    ├── types.ts        # TypeScript types
    ├── service.ts      # API service functions
    ├── useLiveChannel.ts # React hook
    ├── widgets.tsx     # Dashboard widgets
    └── CommandControlPanel.tsx
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| WS | `/api/v1/live/ws` | WebSocket realtime channel |
| GET | `/api/v1/live/sse` | Server-Sent Events stream |
| GET | `/api/v1/live/poll` | Polling fallback |
| POST | `/api/v1/live/crawler/kill` | Kill crawler |
| POST | `/api/v1/live/job/pause` | Pause job |
| POST | `/api/v1/live/job/resume` | Resume job |
| POST | `/api/v1/live/kb/rollback` | Rollback KB |
| POST | `/api/v1/live/mlops/freeze` | Freeze model |
| POST | `/api/v1/live/mlops/retrain` | Retrain model |
| POST | `/api/v1/live/simulate` | Simulate command |
| GET | `/api/v1/live/commands/{id}` | Get command status |
| POST | `/api/v1/live/commands/{id}/cancel` | Cancel command |
| GET | `/api/v1/live/commands` | List commands |
| POST | `/api/v1/live/commands/{id}/approve` | Approve command |
| GET | `/api/v1/live/widget/{type}` | Get widget data |

## Safety Policies

| Policy | Command Types | Requirements |
|--------|--------------|--------------|
| prod_crawler_kill | crawler_kill | role=admin, scope=production → approval required |
| model_freeze | mlops_freeze | role=admin → approval required |
| kb_rollback | kb_rollback | role=admin, scope=production → approval + extra data protection |
| dev_job_controls | job_pause, job_resume | scope=development → no approval |
| viewer_restrictions | all | role=viewer → read-only operations only |

## Technology Stack

- **Backend**: FastAPI, Pydantic, asyncio
- **Frontend**: React, TypeScript, Vite
- **Realtime**: WebSocket, SSE, Polling fallback
- **Auth**: JWT, RBAC
- **Audit**: JSONL file logging with rotation
- **Notifications**: WebSocket push, email, webhook, Slack
