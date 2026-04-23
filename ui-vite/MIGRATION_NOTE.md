# Frontend Refactoring Migration Note

## Summary

Refactored frontend from Chat-based flow to Explain Pipeline flow (GĐ2→GĐ6).

## Changes

### File Tree (New Structure)

```
ui-vite/src/
├── pages/
│   ├── Chat/                    # DISABLED (not removed)
│   │   └── Chat.jsx             # Chat route commented out
│   ├── Explain/                 # NEW - Main explain flow
│   │   ├── index.ts             # Module exports
│   │   ├── ExplainPage.tsx      # Main page (form + result)
│   │   ├── ExplainPage.css
│   │   ├── ExplainForm.tsx      # Input form component
│   │   ├── ExplainForm.css
│   │   ├── ExplainResult.tsx    # Result display component
│   │   └── ExplainResult.css
│   └── ExplainAudit/            # MERGED into ExplainPage
├── services/
│   └── explainApi.ts            # EXISTING - no changes needed
├── store/
│   └── explainStore.ts          # EXISTING - state management
├── types/
│   └── explain.ts               # EXISTING - type definitions
└── App.jsx                      # MODIFIED - router updated
```

### Router Changes (App.jsx)

```diff
- import Chat from './pages/Chat/Chat';
- import ExplainAudit from './pages/ExplainAudit/ExplainAudit';
+ import { ExplainPage } from './pages/Explain';

Routes:
- <Route path="/chat" element={<Chat />} />
- <Route path="/explain" element={<ExplainAudit />} />
+ <Route path="/explain" element={<ExplainPage />} />
```

### State Machine

```
IDLE → LOADING → RESULT
              → ERROR → IDLE (retry/reset)
```

### API Integration

- Endpoint: `POST /api/v1/explain`
- Request:
  ```typescript
  {
    user_id: string;
    features: {
      math_score: number;      // required
      logic_score: number;     // required
      physics_score?: number;
      interest_it?: number;
      language_score?: number;
      creativity_score?: number;
    };
    options: {
      use_llm: true;
      include_meta: true;
    };
  }
  ```

### What's Disabled

1. **Chat.jsx** - Route commented out, file preserved
2. **ExplainAudit.tsx** - Functionality merged into ExplainPage
3. **sendChatMessage API** - Not called from main flow

### What's NOT Allowed

- ❌ Mock data
- ❌ Fallback to fake responses
- ❌ Chat history state
- ❌ Free-form LLM calls
- ❌ Hardcoded URLs

### Test Coverage

Test file: `tests/ui/ExplainPage.spec.ts`

Covers:
- State machine transitions
- API integration (success/error)
- Form validation
- Result display logic
- Audit mode detection
- Error handling
- No-mock policy verification

## How to Test

```bash
# Run frontend
cd ui-vite
npm run dev

# Navigate to
http://localhost:5173/explain

# Fill form:
- Math Score: 85
- Logic Score: 78

# Click "Gửi đánh giá"
```

## Audit Mode URL

```
/explain?mode=audit&trace_id=<trace_id>
```

## Pipeline Flow

```
Frontend Form → Backend API → GĐ2 XAI → GĐ3 Rule → GĐ4 Ollama → GĐ5 Response → GĐ6 UI
```

## Breaking Changes

| Before | After |
|--------|-------|
| /chat (main flow) | /explain (main flow) |
| sendChatMessage() | explainApi.getExplanation() |
| Chat history state | Single request state machine |
| Free-form LLM | Structured explain response |

## Rollback

To rollback:
1. Revert App.jsx to restore Chat route
2. ExplainPage can coexist with Chat

---

Date: 2026-02-13
Author: GitHub Copilot
