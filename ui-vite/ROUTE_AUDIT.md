# Route Audit Report

> Generated: 2026-02-14
> Scope: `/ui-vite/src`

## Summary

| Metric | Count |
|--------|-------|
| Total Pages | 14 |
| Routed Pages | 10 |
| Unrouted Pages | 4 |
| Commented Routes | 1 |

## Pages Inventory

| Page | Path | Routed | Component | Notes |
|------|------|--------|-----------|-------|
| Landing | `/` | ✅ | Landing.jsx | Entry point |
| ProfileSetup | `/profile` | ✅ | ProfileSetup.jsx | User profile |
| Assessment | `/assessment` | ✅ | Assessment.jsx | Skills assessment |
| Chat | `/chat` | ❌ | Chat.jsx | **COMMENTED OUT** - needs re-enable |
| Dashboard | `/dashboard` | ✅ | Dashboard.jsx | Results display |
| CareerDetail | `/career/:id` | ✅ | CareerDetail.jsx | Detail view |
| CareerLibrary | `/library` | ✅ | CareerLibrary.jsx | Browse careers |
| ExplainPage | `/explain` | ✅ | ExplainPage.tsx | Main explain UI |
| ExplainAudit | `/explain/audit` | ❌ | ExplainAudit.tsx | **MISSING ROUTE** - needs add |
| KBAdmin | `/admin/kb` | ✅ | KBAdmin.jsx | KB management |
| FeedbackAdmin | `/admin/feedback` | ✅ | FeedbackAdmin.tsx | Feedback dashboard |
| MLOpsAdmin | `/admin/mlops` | ✅ | MLOpsAdmin.jsx | MLOps lifecycle |
| Governance | `/admin/governance/*` | ❌ | GovernancePanel | **MISSING ROUTE** - needs add |
| Crawlers Admin | `/admin/crawlers` | ❌ | - | **PAGE NOT EXISTS** - needs create |
| Ops Dashboard | `/admin/ops` | ❌ | - | **PAGE NOT EXISTS** - needs create |

## Route Namespace Structure

### Current
```
/                    → Landing
/profile             → ProfileSetup
/assessment          → Assessment
/chat                → Chat (DISABLED)
/dashboard           → Dashboard
/career/:id          → CareerDetail
/library             → CareerLibrary
/explain             → ExplainPage
/admin/kb            → KBAdmin
/admin/feedback      → FeedbackAdmin
/admin/mlops         → MLOpsAdmin
```

### Required (to add)
```
/chat                → Chat (RE-ENABLE)
/explain/audit       → ExplainAudit
/admin/governance/*  → GovernancePanel
/admin/crawlers      → CrawlersAdmin (NEW)
/admin/ops           → OpsAdmin (NEW)
```

## Issues Found

### 1. Commented Routes
- **Location**: `App.jsx` line 34-35
- **Route**: `/chat`
- **Reason**: Comment says "not part of pipeline architecture"
- **Action**: Re-enable - Chat.jsx is fully functional

### 2. Missing Routes
| Component | Expected Path | Status |
|-----------|---------------|--------|
| GovernancePanel | `/admin/governance/*` | Page exists, no route |
| ExplainAudit | `/explain/audit` | Page exists, no route |

### 3. Missing Pages
| Required Page | Path | Status |
|---------------|------|--------|
| CrawlersAdmin | `/admin/crawlers` | Needs creation |
| OpsAdmin | `/admin/ops` | Needs creation |

### 4. Missing Services
| Service | Consumers | Status |
|---------|-----------|--------|
| crawlerApi.js | CrawlersAdmin | Needs creation |
| opsApi.js | OpsAdmin | Needs creation |

## Service → UI Binding Status

| Service | UI | Status |
|---------|-----|--------|
| api.js | Chat.jsx | ✅ Connected |
| explainApi.ts | ExplainPage.tsx | ✅ Connected |
| feedbackApi.ts | FeedbackAdmin.tsx | ✅ Connected |
| governanceApi.js | GovernancePanel | ✅ Connected |
| kbApi.js | KBAdmin.jsx | ✅ Connected |
| mlopsApi.ts | MLOpsAdmin.jsx | ✅ Connected |
| crawlerApi.js | CrawlersAdmin | ❌ Missing |
| opsApi.js | OpsAdmin | ❌ Missing |

## Header Navigation Check

Current navigation links in `Header.jsx`:
- `/` → Trang chủ ✅
- `/assessment` → Đánh giá ✅
- `/chat` → Tư vấn AI (⚠️ route disabled)
- `/library` → Thư viện nghề ✅
- `/dashboard` → Kết quả ✅

**Issue**: Header links to `/chat` but route is disabled.

## Action Items

1. [ ] Re-enable `/chat` route in App.jsx
2. [ ] Add `/explain/audit` route
3. [ ] Add `/admin/governance/*` route
4. [ ] Create `/admin/crawlers` page + crawlerApi service
5. [ ] Create `/admin/ops` page + opsApi service
6. [ ] Verify all routes work after changes
7. [ ] Run build to confirm no errors
