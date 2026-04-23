# Demo Runbook - Academic Defense

## Version: 1.0.0
## Date: 2026-02-13

---

## 1. Pre-Demo Checklist

### 1.1 System Requirements

| Component | Required | Check Command |
|-----------|----------|---------------|
| Python | 3.10+ | `python --version` |
| Node.js | 18+ | `node --version` |
| Ollama | Running | `netstat -ano \| findstr 11434` |
| Ports | 8000, 5173, 11434 | `netstat -ano \| findstr "8000\|5173"` |

### 1.2 Verify Ollama

```powershell
# Check Ollama is running
netstat -ano | findstr 11434

# Expected output:
# TCP    127.0.0.1:11434    0.0.0.0:0    LISTENING    <PID>

# Test Ollama directly
curl http://localhost:11434/api/version
```

---

## 2. Startup Procedure

### 2.1 Start Backend

```powershell
# Navigate to project root
cd "F:\Hybrid Decision Support System"

# Start backend server
python -m uvicorn backend.run_api:app --host 0.0.0.0 --port 8000
```

**Expected Output:**
```
INFO | Explain API registered: /api/v1/explain
INFO | HDSS Backend started
INFO | OpsHub ready (metrics + 4 health checks + recovery)
INFO | Uvicorn running on http://0.0.0.0:8000
```

### 2.2 Start Frontend

```powershell
# Open new terminal
cd "F:\Hybrid Decision Support System\ui-vite"

# Install dependencies (if needed)
npm install

# Start dev server
npm run dev
```

**Expected Output:**
```
VITE v5.x.x ready
➜ Local:   http://localhost:5173/
```

---

## 3. Demo Test Cases

### Test Case 1: Health Check

**Purpose:** Verify system is ready

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health/full" -Method GET | ConvertTo-Json -Depth 3
```

**Expected Response:**
```json
{
  "status": "healthy",
  "uptime_seconds": ...,
  "components": {
    "disk_space": { "status": "healthy" },
    "memory": { "status": "healthy" },
    "data_dir": { "status": "healthy" },
    "scoring_engine": { "status": "healthy" }
  }
}
```

### Test Case 2: Full Pipeline (Explain API)

**Purpose:** Demonstrate complete GĐ1-GĐ6 pipeline

```powershell
$body = @{
  user_id = "demo_user"
  features = @{
    math_score = 90
    logic_score = 85
    physics_score = 80
    interest_it = 75
  }
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/api/v1/explain" -Method POST -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 4
```

**Expected Response:**
```json
{
  "api_version": "v1",
  "trace_id": "uuid-here",
  "career": "Data Scientist",
  "confidence": 0.93,
  "reasons": [
    "Điểm Toán vượt ngưỡng yêu cầu (shap)",
    "Logic score cao (coef)"
  ],
  "explain_text": "...",
  "llm_text": "Bạn phù hợp với nghề...",
  "used_llm": true,
  "meta": {
    "model_version": "active",
    "xai_version": "1.0.0"
  }
}
```

### Test Case 3: Frontend UI

**Purpose:** Show user-facing interface

1. Open browser: `http://localhost:5173/explain`
2. Fill form:
   - Math Score: 90
   - Logic Score: 85
3. Click "Gửi đánh giá"
4. View result card with:
   - Career recommendation
   - Confidence percentage
   - Explanation text
   - Trace ID

### Test Case 4: Metrics Dashboard

**Purpose:** Show observability

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/ops/status" -Method GET | ConvertTo-Json -Depth 3
```

**Shows:**
- Supervisor status
- SLA compliance
- Alert summary
- Bottleneck analysis
- Metrics snapshot

---

## 4. Expected Output Screenshots

### 4.1 Backend Logs

```
INFO | Request started POST /api/v1/explain
INFO | Stage3 config: enabled=True, strict=True
INFO | Stage4 config: enabled=True, model=llama3.2:1b
INFO | ML model loaded: version=active
INFO | XAI SHAP TreeExplainer initialized
INFO | 127.0.0.1 - "POST /api/v1/explain HTTP/1.1" 200 OK
```

### 4.2 Frontend Result

```
┌─────────────────────────────────────────────┐
│  🎯 Data Scientist                          │
│                                             │
│  Độ tin cậy: 93%  [████████████░░░]        │
│                                             │
│  🤖 Ollama LLM                              │
│                                             │
│  Bạn phù hợp với nghề Data Scientist vì:   │
│  - Điểm toán học vượt quá yêu cầu          │
│  - Kỹ năng logic mạnh                      │
│                                             │
│  Trace ID: abc1-2345-...                   │
└─────────────────────────────────────────────┘
```

---

## 5. Recovery Procedures

### 5.1 Backend Won't Start

```powershell
# Check if port is in use
netstat -ano | findstr 8000

# Kill existing process if needed
Stop-Process -Id <PID> -Force

# Restart
python -m uvicorn backend.run_api:app --host 0.0.0.0 --port 8000
```

### 5.2 Ollama Not Responding

```powershell
# Check Ollama status
Get-Process ollama

# If not running, start Ollama
ollama serve

# Verify model is available
ollama list
# Should show: llama3.2:1b
```

### 5.3 LLM Timeout (E504)

If explain API returns E504:
1. Ollama may need to load model (first request is slow)
2. Retry after 30 seconds
3. Check Ollama logs
4. Fallback: Response will include `used_llm: false` with Stage 3 output

### 5.4 Frontend Build Error

```powershell
# Clear cache and reinstall
cd ui-vite
Remove-Item -Recurse -Force node_modules
npm install
npm run dev
```

---

## 6. Demo Flow Script

### Recommended Order (15-20 min)

1. **Introduction** (2 min)
   - Show architecture diagram
   - Explain 6-stage pipeline

2. **Backend Demo** (5 min)
   - Start backend (show logs)
   - Run health check
   - Show metrics

3. **API Demo** (5 min)
   - Run explain API
   - Show trace_id
   - Show llm_text

4. **Frontend Demo** (5 min)
   - Open UI
   - Fill form
   - Show result card
   - Show audit mode

5. **Q&A** (3 min)
   - Show ops dashboard
   - Explain stability layer

---

## 7. Backup Demo Options

If live demo fails:

### Option A: Pre-recorded Output

Use saved JSON responses from `outputs/` folder:
- `cv_results.json`
- `stability_report.json`
- `drift_report.json`

### Option B: Screenshots

Prepared screenshots in `final_release/FIGURES/`:
- Architecture diagram
- Frontend result
- Metrics dashboard

### Option C: Code Walkthrough

Show key files:
- `backend/main_controller.py` (lines 1-100)
- `backend/evaluation/service.py`
- `ui-vite/src/pages/Explain/ExplainPage.tsx`

---

## 8. Post-Demo Cleanup

```powershell
# Stop backend (Ctrl+C in terminal)

# Stop frontend (Ctrl+C in terminal)

# Optional: Clear session data
Remove-Item -Recurse -Force backend/data/sessions/*
```

---

## 9. Contact Information

For technical issues during demo:
- Check `backend/data/logs/` for error logs
- Check browser console for frontend errors
- Report issues with trace_id for debugging
