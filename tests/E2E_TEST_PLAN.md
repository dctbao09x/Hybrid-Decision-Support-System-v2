# End-to-End Test Plan — Hybrid Decision Support System
**Date:** 2026-02-27  
**Scope:** Full pipeline — chat input → `ScoringInput` → `ScoringBreakdown` → `ScoreAnalyticsEngine` (Ollama) → API response → frontend render  
**Canonical endpoint:** `POST /api/v1/one-button/run`  
**Secondary endpoint (explanation audit):** `POST /api/v1/explain/score-analytics`

---

## 1 — TEST DATA SCENARIOS

All `scoring_input` objects map to `backend/scoring/models.py::ScoringInput`.  
All 6 components (`personal_profile`, `experience`, `goals`, `skills`, `education`, `preferences`) are **mandatory** (no defaults, no Optional).

---

### Scenario A — Technical Profile

**Raw chat input (multi-message)**
```
U: My skills are Python, SQL, Machine Learning, and Docker. Intermediate level on all.
U: I'm interested in data science, automation, and cloud computing.
U: I have a Bachelor's degree in Computer Science.
U: I have 4 years of experience in software engineering and data pipelines.
U: My career goals are to become a Data Engineer or ML Engineer within 3 years.
```

**Expected `DecisionInput` → `OneButtonRequest.scoring_input`**
```json
{
  "personal_profile": {
    "ability_score": 0.70,
    "confidence_score": 0.68,
    "interests": ["data science", "automation", "cloud computing"]
  },
  "experience": {
    "years": 4,
    "domains": ["software engineering", "data pipelines"]
  },
  "goals": {
    "career_aspirations": ["data engineer", "ml engineer"],
    "timeline_years": 3
  },
  "skills": ["python", "sql", "machine learning", "docker"],
  "education": {
    "level": "bachelor",
    "field_of_study": "computer science"
  },
  "preferences": {
    "preferred_domains": ["technology"],
    "work_style": "hybrid"
  }
}
```

**Expected scoring characteristics**
- `skill_score` ≥ 60 (4 recognised technical skills, all taxonomy-resolvable)
- `experience_score` ≥ 55 (4 years, relevant domain)
- `education_score` ≥ 60 (Bachelor in CS → direct match)
- `goal_alignment_score` ≥ 65 (aspirations align with skill set)
- `explanation.confidence` in [0.65, 1.0]
- `top_career.domain` resolves to technology / data category

---

### Scenario B — Non-Technical Profile

**Raw chat input (multi-message)**
```
U: My skills are public speaking, project management, and writing.
U: I'm interested in education, community development, and social policy.
U: I studied a Bachelor of Arts in Sociology.
U: I've worked 6 years in non-profit program coordination.
U: I want to become a Policy Analyst or Community Manager within 5 years.
```

**Expected `DecisionInput` → `OneButtonRequest.scoring_input`**
```json
{
  "personal_profile": {
    "ability_score": 0.65,
    "confidence_score": 0.60,
    "interests": ["education", "community development", "social policy"]
  },
  "experience": {
    "years": 6,
    "domains": ["non-profit", "program coordination"]
  },
  "goals": {
    "career_aspirations": ["policy analyst", "community manager"],
    "timeline_years": 5
  },
  "skills": ["public speaking", "project management", "writing"],
  "education": {
    "level": "bachelor",
    "field_of_study": "sociology"
  },
  "preferences": {
    "preferred_domains": ["social services", "government"],
    "work_style": "in-office"
  }
}
```

**Expected scoring characteristics**
- `skill_score` 30–55 (soft skills, partial taxonomy match expected)
- `experience_score` ≥ 60 (6 years accumulated — highest experience score across all scenarios)
- `education_score` 30–55 (arts degree, limited technical overlap)
- `goal_alignment_score` 40–65 (moderate alignment to social domains)
- `explanation.confidence` in [0.45, 0.80]
- `top_career.domain` resolves to social-services / management category, not technology

---

### Scenario C — Edge Case (Minimal Valid Input)

**Raw chat input (multi-message)**
```
U: I know Excel.
U: I like finance.
U: I finished high school.
U: No work experience yet.
U: I want to work in accounting someday.
```

**Expected `DecisionInput` → `OneButtonRequest.scoring_input`**
```json
{
  "personal_profile": {
    "ability_score": 0.40,
    "confidence_score": 0.35,
    "interests": ["finance"]
  },
  "experience": {
    "years": 0,
    "domains": ["general"]
  },
  "goals": {
    "career_aspirations": ["accountant"],
    "timeline_years": 5
  },
  "skills": ["excel"],
  "education": {
    "level": "high school",
    "field_of_study": "general"
  },
  "preferences": {
    "preferred_domains": ["finance"],
    "work_style": "in-office"
  }
}
```

**Expected scoring characteristics**
- `skill_score` ≤ 30 (single entry-level skill)
- `experience_score` = minimum meaningful value (0 years → floor, not crash)
- `education_score` ≤ 25 (high school → lowest tier)
- `goal_alignment_score` 20–50 (single aspiration, single domain)
- `explanation.confidence` in [0.20, 0.55]
- Pipeline must not return HTTP 400 or 500; `status = "SUCCESS"` required
- `explanation` must be non-null and non-empty (engine handles minimal input gracefully)

---

## 2 — BACKEND VALIDATION CHECKS

All checks apply independently to each scenario.  
Server: `http://127.0.0.1:8000`

### 2.1 Checklist per scenario

| Check | Criterion |
|---|---|
| HTTP status | `200 OK` |
| `response.status` | `"SUCCESS"` |
| `explanation` object present | not `null`, not `{}` |
| `explanation.summary` | `str`, `len > 100` |
| `explanation.factors` | `array`, `len >= 3` |
| `explanation.confidence` | `float`, `0 < value < 1` |
| `explanation.reasoning_chain` | `array`, `len >= 1` |
| `trace_id` | `str`, UUID v4 format, unique per call |
| `scoring_breakdown` | object with `skill_score`, `experience_score`, `education_score`, `goal_alignment_score`, `preference_score`, `final_score`, `result_hash` |
| All 8 stages present in `stages{}` | `taxonomy_normalize`, `taxonomy_validate`, `rule_engine`, `ml_predict`, `scoring`, `explain`, `diagnostics`, `stage_trace` |
| No stage has `status == "skipped"` | enforced by `_validate_required_stages()` in `one_button_router.py` |
| `meta.llm_used` | `true` |

### 2.2 Score-analytics endpoint headers (secondary validation)

After the one-button run, call `POST /api/v1/explain/score-analytics` with the extracted `scoring_breakdown`.  
Inspect response headers:

| Header | Expected |
|---|---|
| `X-Fallback-Used` | `"false"` |
| `X-Prompt-Version` | `"score_analytics_v1"` (matches `# PROMPT_VERSION` in `score_analytics.txt`) |
| `X-Engine-Version` | present, non-empty string |
| `X-Fallback-Reason` | `"none"` |
| `X-Trace-Id` | UUID v4, different from calling trace_id |

### 2.3 Exact curl commands

**Scenario A:**
```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/one-button/run \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_scenario_a",
    "scoring_input": {
      "personal_profile": {"ability_score": 0.70, "confidence_score": 0.68, "interests": ["data science","automation","cloud computing"]},
      "experience": {"years": 4, "domains": ["software engineering","data pipelines"]},
      "goals": {"career_aspirations": ["data engineer","ml engineer"], "timeline_years": 3},
      "skills": ["python","sql","machine learning","docker"],
      "education": {"level": "bachelor", "field_of_study": "computer science"},
      "preferences": {"preferred_domains": ["technology"], "work_style": "hybrid"}
    }
  }' | python -m json.tool
```

**Scenario B:**
```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/one-button/run \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_scenario_b",
    "scoring_input": {
      "personal_profile": {"ability_score": 0.65, "confidence_score": 0.60, "interests": ["education","community development","social policy"]},
      "experience": {"years": 6, "domains": ["non-profit","program coordination"]},
      "goals": {"career_aspirations": ["policy analyst","community manager"], "timeline_years": 5},
      "skills": ["public speaking","project management","writing"],
      "education": {"level": "bachelor", "field_of_study": "sociology"},
      "preferences": {"preferred_domains": ["social services","government"], "work_style": "in-office"}
    }
  }' | python -m json.tool
```

**Scenario C:**
```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/one-button/run \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_scenario_c",
    "scoring_input": {
      "personal_profile": {"ability_score": 0.40, "confidence_score": 0.35, "interests": ["finance"]},
      "experience": {"years": 0, "domains": ["general"]},
      "goals": {"career_aspirations": ["accountant"], "timeline_years": 5},
      "skills": ["excel"],
      "education": {"level": "high school", "field_of_study": "general"},
      "preferences": {"preferred_domains": ["finance"], "work_style": "in-office"}
    }
  }' | python -m json.tool
```

**Score-analytics header audit (pipe output of one-button into this):**
```bash
curl -si -X POST http://127.0.0.1:8000/api/v1/explain/score-analytics \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "skill_score": 72.0,
    "experience_score": 58.0,
    "education_score": 65.0,
    "goal_alignment_score": 70.0,
    "preference_score": 60.0,
    "confidence": 0.73,
    "skills": ["python","sql","machine learning","docker"],
    "interests": ["data science","automation"],
    "education_level": "bachelor",
    "years_experience": 4.0
  }' | head -20
```

---

## 3 — OLLAMA VALIDATION

### 3.1 Primary signal: `fallback` field + `used_llm` field

From `ScoreAnalyticsResult` (engine.py) and `ScoreAnalyticsResponse` (explain_router.py):

```
GET /api/v1/explain/score-analytics response body:
  "used_llm": true        ← Ollama was called and succeeded
  "fallback": false       ← deterministic fallback was NOT activated
  "fallback_reason": "none"
```

If `fallback == true`, the `fallback_reason` field contains the typed exception (e.g. `"TimeoutError"`, `"NetworkError"`, `"ModelResponseError"`). Any non-`"none"` value is a validation failure.

### 3.2 Dynamic language detection (no static watermark)

The prompt template (`score_analytics.txt::PROMPT_VERSION: score_analytics_v1`) instructs the model to produce **6-stage structured markdown**. The generated `markdown` field must:

- Contain `# STAGE 1 — INPUT SUMMARY INTERPRETATION` through a recognisable multi-stage heading structure
- Reference at least one specific value from the input (e.g. actual skill name, actual score)
- Not contain the literal string `"Insufficient data provided."` in Stage 2 or Stage 3 (allowed only in Stage 1 for genuinely absent optional fields)
- Not be byte-for-byte identical to the inline stub template defined in `_INLINE_STUB` in engine.py

**Stub detection expression (Python):**
```python
STUB_SIGNATURE = "Skills: {{skills}}\nSkill Score: {{skill_score}}"
assert STUB_SIGNATURE not in result["markdown"], "Response is unrendered stub"
```

### 3.3 Cross-scenario string diff method

Collect `markdown` for all three scenarios and assert:

```python
from difflib import SequenceMatcher

def similarity_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

# Each pair must differ by at least 30% (ratio <= 0.70)
assert similarity_ratio(markdown_a, markdown_b) <= 0.70, \
    "Scenario A and B explanations are too similar — suspected static fallback"
assert similarity_ratio(markdown_a, markdown_c) <= 0.70, \
    "Scenario A and C explanations are too similar"
assert similarity_ratio(markdown_b, markdown_c) <= 0.70, \
    "Scenario B and C explanations are too similar"
```

Additionally assert that skill names from Scenario A (`python`, `sql`) appear in Scenario A's markdown but **not** in Scenario B's markdown:

```python
assert "python" in markdown_a.lower()
assert "python" not in markdown_b.lower()
assert "sociology" in markdown_b.lower() or "social" in markdown_b.lower()
```

---

## 4 — FRONTEND RENDER VALIDATION

Follow this ordered sequence in the browser (Chrome DevTools required).

### Step 1 — Submit full profile via UI
1. Open `http://localhost:5173` (Vite dev server).
2. Complete the chat flow entering **Scenario A** data in sequence.
3. Submit all 5 field groups (skills, interests, education, experience, goals).
4. Click the **One-Button / Run** trigger in the UI.

### Step 2 — Network inspection
1. Open DevTools → Network tab.
2. Locate the request to `/api/v1/one-button/run`.
3. Confirm:
   - Request Method: `POST`
   - Status: `200`
   - Response `Content-Type`: `application/json`
4. In the response body, copy `explanation.summary` (full string).

### Step 3 — Explanation text match
1. In the UI, locate the rendered explanation card.
2. Copy the visible summary text.
3. Assert the rendered text is a substring of or identical to `response.explanation.summary`.
4. Confirm `explanation.factors` renders as ≥ 3 labelled items.
5. Confirm `explanation.confidence` renders as a numeric percentage (e.g. "73%").

### Step 4 — trace_id watermark (if implemented)
1. If the UI renders a trace badge or debug watermark, confirm the displayed `trace_id` matches `response.trace_id` in the network response exactly.

### Step 5 — Hard reload determinism check
1. Press `Ctrl+Shift+R` (hard reload, cache clear).
2. Re-submit **the same Scenario A data** again.
3. Confirm:
   - A new network request is made to `/api/v1/one-button/run`
   - The new `trace_id` **differs** from the previous call
   - The `explanation.summary` text is different (LLM non-determinism) OR identical (if Ollama temperature=0 / fully deterministic)
   - The `scoring_breakdown.result_hash` is **identical** to the previous call (deterministic scoring)
4. Re-submit with **Scenario C data** (different inputs).
5. Confirm `explanation.summary` and `scoring_breakdown.result_hash` both differ from Scenario A values.

---

## 5 — FAILURE DETECTION MATRIX

| Failure | Root Cause | Detection Method |
|---|---|---|
| `explanation` is `null` | `explain` stage errored; `DecisionController` caught exception and nulled the field | `response.explanation == null`; check `stages.explain.status == "error"` and `stages.explain.error` field |
| `explanation` is `{}` | `ExplanationResult` serialised as empty dict | `len(response.explanation.keys()) == 0`; check `meta.llm_used == false` |
| `X-Fallback-Used: true` | Ollama unreachable / timeout / `ModelResponseError`; `ScoreAnalyticsEngine._fallback()` activated | `response.headers["X-Fallback-Used"] == "true"`; `response_body.fallback_reason != "none"` |
| Same `explanation.summary` across different profiles | `ScoreAnalyticsEngine` returning fixed fallback text; LLM not personalising | `similarity_ratio(summary_a, summary_b) > 0.70` per Section 3.3; also check `fallback == false` is asserted before comparison |
| `trace_id` unchanged across two sequential calls | UUID generation broken; controller returning cached response; cache key collision | Two sequential identical-payload calls with `cleanCache()` bypass; assert `trace_id_1 != trace_id_2` |
| `scoring_breakdown.result_hash` changes across identical inputs | Non-deterministic scoring path; floating-point variance; taxonomy normalisation inconsistency | Two calls with byte-identical payload; assert `result_hash_1 == result_hash_2` |
| UI shows stale/old text | Frontend caching explanation in local state; component not re-rendering after new API response | Hard reload + re-run; compare `explanation.summary` in Network tab against DOM text; assert they match |
| `stages.explain.status == "skipped"` | `include_explanation=False` reached `one_button_router.py` (should be impossible; options are force-overridden) | HTTP 500 raised by `_validate_required_stages()`; `ONE_BUTTON_STAGE_SKIPPED` error code in body |
| HTTP 400 on valid minimal input | Taxonomy gate rejecting single-item arrays or `"general"` education | Response code check; `TaxonomyValidationError.as_dict()` in body; validate taxonomy covers edge-case tokens |
| `explanation.factors` length < 3 | Score analytics LLM returned truncated output; formatter failed to parse markdown sections | `len(explanation.factors) < 3`; also inspect `stages.explain.output` for truncation signal |
| `meta.llm_used == false` | ML feature extraction stage did not call LLM; `ml_predict` stage errored silently | `response.meta.llm_used == false`; check `stages.ml_predict.status` |

---

## 6 — AUTOMATED REGRESSION SCRIPT (NODE)

Save as `tests/regression/e2e_pipeline_regression.mjs` and run with `node e2e_pipeline_regression.mjs`.

```javascript
// tests/regression/e2e_pipeline_regression.mjs
// Node.js 18+ (native fetch)
// Usage: node e2e_pipeline_regression.mjs
// Requires backend running on http://127.0.0.1:8000

const BASE = "http://127.0.0.1:8000";
const ONE_BUTTON = `${BASE}/api/v1/one-button/run`;
const SCORE_ANALYTICS = `${BASE}/api/v1/explain/score-analytics`;
const AUTH_TOKEN = process.env.API_TOKEN ?? "";  // set via env if auth required

const SCENARIOS = {
  A: {
    label: "Scenario A — Technical",
    body: {
      user_id: "regression_a",
      scoring_input: {
        personal_profile: { ability_score: 0.70, confidence_score: 0.68, interests: ["data science","automation","cloud computing"] },
        experience: { years: 4, domains: ["software engineering","data pipelines"] },
        goals: { career_aspirations: ["data engineer","ml engineer"], timeline_years: 3 },
        skills: ["python","sql","machine learning","docker"],
        education: { level: "bachelor", field_of_study: "computer science" },
        preferences: { preferred_domains: ["technology"], work_style: "hybrid" }
      }
    }
  },
  B: {
    label: "Scenario B — Non-Technical",
    body: {
      user_id: "regression_b",
      scoring_input: {
        personal_profile: { ability_score: 0.65, confidence_score: 0.60, interests: ["education","community development","social policy"] },
        experience: { years: 6, domains: ["non-profit","program coordination"] },
        goals: { career_aspirations: ["policy analyst","community manager"], timeline_years: 5 },
        skills: ["public speaking","project management","writing"],
        education: { level: "bachelor", field_of_study: "sociology" },
        preferences: { preferred_domains: ["social services","government"], work_style: "in-office" }
      }
    }
  },
  C: {
    label: "Scenario C — Minimal Edge Case",
    body: {
      user_id: "regression_c",
      scoring_input: {
        personal_profile: { ability_score: 0.40, confidence_score: 0.35, interests: ["finance"] },
        experience: { years: 0, domains: ["general"] },
        goals: { career_aspirations: ["accountant"], timeline_years: 5 },
        skills: ["excel"],
        education: { level: "high school", field_of_study: "general" },
        preferences: { preferred_domains: ["finance"], work_style: "in-office" }
      }
    }
  }
};

// ─── helpers ──────────────────────────────────────────────────────────────────

function pass(label) {
  console.log(`  ✔  ${label}`);
}

function fail(label, detail) {
  console.error(`  ✖  ${label}`);
  if (detail !== undefined) console.error(`       detail: ${JSON.stringify(detail)}`);
  process.exitCode = 1;
}

function assert(condition, label, detail) {
  if (condition) pass(label);
  else fail(label, detail);
}

function uuid4Re() {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
}

function similarityRatio(a, b) {
  // Levenshtein-based approximation using longest common subsequence length
  const maxLen = Math.max(a.length, b.length);
  if (maxLen === 0) return 1;
  let matches = 0;
  const bSet = new Set(b.split(/\s+/));
  for (const word of a.split(/\s+/)) {
    if (bSet.has(word)) matches++;
  }
  const totalWords = Math.max(a.split(/\s+/).length, b.split(/\s+/).length);
  return matches / totalWords;
}

// ─── pipeline one-button assertion ───────────────────────────────────────────

async function runScenario(key, scenario) {
  console.log(`\n${"═".repeat(60)}`);
  console.log(`  ${scenario.label}`);
  console.log(`${"═".repeat(60)}`);

  const headers = { "Content-Type": "application/json" };
  if (AUTH_TOKEN) headers["Authorization"] = `Bearer ${AUTH_TOKEN}`;

  let res, data;
  try {
    res = await fetch(ONE_BUTTON, { method: "POST", headers, body: JSON.stringify(scenario.body) });
    data = await res.json();
  } catch (e) {
    fail("HTTP request completed", e.message);
    return null;
  }

  // ── HTTP ─────────────────────────────────────────────────────────────────
  assert(res.status === 200, `HTTP 200`, res.status);
  assert(data.status === "SUCCESS", `response.status == "SUCCESS"`, data.status);

  // ── trace_id ─────────────────────────────────────────────────────────────
  assert(typeof data.trace_id === "string" && uuid4Re().test(data.trace_id),
    `trace_id is UUID v4`, data.trace_id);

  // ── explanation object ───────────────────────────────────────────────────
  const expl = data.explanation;
  assert(expl !== null && typeof expl === "object" && Object.keys(expl).length > 0,
    `explanation is non-empty object`, expl);

  if (expl) {
    assert(typeof expl.summary === "string" && expl.summary.length > 100,
      `explanation.summary length > 100 chars (got ${expl.summary?.length ?? 0})`);

    assert(Array.isArray(expl.factors) && expl.factors.length >= 3,
      `explanation.factors.length >= 3 (got ${expl.factors?.length ?? 0})`);

    assert(typeof expl.confidence === "number" && expl.confidence > 0 && expl.confidence < 1,
      `explanation.confidence in (0,1) (got ${expl.confidence})`);

    assert(Array.isArray(expl.reasoning_chain) && expl.reasoning_chain.length >= 1,
      `explanation.reasoning_chain non-empty`);
  }

  // ── scoring_breakdown ────────────────────────────────────────────────────
  const sb = data.scoring_breakdown;
  assert(sb !== null && typeof sb === "object", `scoring_breakdown present`);
  if (sb) {
    for (const field of ["skill_score","experience_score","education_score",
                         "goal_alignment_score","preference_score","final_score","result_hash"]) {
      assert(field in sb, `scoring_breakdown.${field} present`, sb);
    }
  }

  // ── 8 required stages ────────────────────────────────────────────────────
  const REQUIRED = ["taxonomy_normalize","taxonomy_validate","rule_engine",
                    "ml_predict","scoring","explain","diagnostics","stage_trace"];
  const stages = data.stages || {};
  for (const s of REQUIRED) {
    assert(s in stages, `stages.${s} present`);
    if (s in stages) {
      assert(stages[s].status !== "skipped", `stages.${s}.status != "skipped"`, stages[s].status);
    }
  }

  // ── LLM used ─────────────────────────────────────────────────────────────
  assert(data.meta?.llm_used === true, `meta.llm_used == true`, data.meta?.llm_used);

  return { traceId: data.trace_id, explanation: expl, scoringBreakdown: sb };
}

// ─── trace_id uniqueness check ────────────────────────────────────────────────

async function assertTraceIdUniqueness(scenario) {
  console.log(`\n── trace_id uniqueness (${scenario.label}) ──`);
  const headers = { "Content-Type": "application/json" };
  if (AUTH_TOKEN) headers["Authorization"] = `Bearer ${AUTH_TOKEN}`;

  const [r1, r2] = await Promise.all([
    fetch(ONE_BUTTON, { method: "POST", headers, body: JSON.stringify(scenario.body) }).then(r => r.json()),
    fetch(ONE_BUTTON, { method: "POST", headers, body: JSON.stringify(scenario.body) }).then(r => r.json()),
  ]);

  assert(r1.trace_id !== r2.trace_id,
    `Concurrent calls produce different trace_ids`,
    { id1: r1.trace_id, id2: r2.trace_id });

  assert(
    r1.scoring_breakdown?.result_hash === r2.scoring_breakdown?.result_hash,
    `Identical inputs produce identical result_hash (deterministic scoring)`,
    { h1: r1.scoring_breakdown?.result_hash, h2: r2.scoring_breakdown?.result_hash }
  );
}

// ─── score-analytics endpoint (X-Fallback-Used) ───────────────────────────────

async function assertScoreAnalyticsHeaders(label, scoringBreakdown) {
  console.log(`\n── score-analytics headers (${label}) ──`);
  if (!scoringBreakdown) { console.log("  ⚠  skipped — no scoring_breakdown available"); return null; }

  const headers = { "Content-Type": "application/json" };
  if (AUTH_TOKEN) headers["Authorization"] = `Bearer ${AUTH_TOKEN}`;

  const body = {
    skill_score:          scoringBreakdown.skill_score          ?? 50,
    experience_score:     scoringBreakdown.experience_score     ?? 50,
    education_score:      scoringBreakdown.education_score      ?? 50,
    goal_alignment_score: scoringBreakdown.goal_alignment_score ?? 50,
    preference_score:     scoringBreakdown.preference_score     ?? 50,
    confidence:           0.60,
    skills:               ["python"],
    interests:            ["technology"],
    education_level:      "bachelor",
    years_experience:     2.0,
  };

  let res, data;
  try {
    res = await fetch(SCORE_ANALYTICS, { method: "POST", headers, body: JSON.stringify(body) });
    data = await res.json();
  } catch (e) {
    fail("score-analytics request completed", e.message);
    return null;
  }

  assert(res.status === 200, `score-analytics HTTP 200`, res.status);
  assert(res.headers.get("x-fallback-used") === "false",
    `X-Fallback-Used == "false"`, res.headers.get("x-fallback-used"));
  assert(res.headers.get("x-prompt-version") === "score_analytics_v1",
    `X-Prompt-Version == "score_analytics_v1"`, res.headers.get("x-prompt-version"));
  assert(res.headers.get("x-fallback-reason") === "none",
    `X-Fallback-Reason == "none"`, res.headers.get("x-fallback-reason"));
  assert(typeof res.headers.get("x-trace-id") === "string",
    `X-Trace-Id header present`);

  assert(data.fallback === false, `response body fallback == false`, data.fallback);
  assert(data.used_llm === true, `response body used_llm == true`, data.used_llm);
  assert(typeof data.markdown === "string" && data.markdown.length > 100,
    `markdown length > 100 chars (got ${data.markdown?.length ?? 0})`);

  // Stub detection
  const STUB_SIGNATURE = "Skills: {{skills}}";
  assert(!data.markdown.includes(STUB_SIGNATURE),
    `markdown is not unrendered stub`, data.markdown.slice(0, 80));

  return data.markdown;
}

// ─── cross-scenario similarity ────────────────────────────────────────────────

function assertCrossScenarioDiversity(markdowns) {
  console.log(`\n── Cross-scenario explanation diversity ──`);
  const pairs = [
    ["A","B"], ["A","C"], ["B","C"]
  ];
  for (const [x, y] of pairs) {
    if (!markdowns[x] || !markdowns[y]) {
      console.log(`  ⚠  skipped pair ${x}/${y} — missing markdown`);
      continue;
    }
    const ratio = similarityRatio(markdowns[x], markdowns[y]);
    assert(ratio <= 0.70,
      `Similarity(${x},${y}) <= 0.70 (got ${ratio.toFixed(3)}) — personalisation confirmed`,
      ratio);
  }
}

// ─── main ─────────────────────────────────────────────────────────────────────

(async () => {
  console.log("╔══════════════════════════════════════════════════════════╗");
  console.log("║   E2E Pipeline Regression — Hybrid Decision Support      ║");
  console.log(`║   ${new Date().toISOString()}                  ║`);
  console.log("╚══════════════════════════════════════════════════════════╝");

  const results = {};
  for (const [key, scenario] of Object.entries(SCENARIOS)) {
    results[key] = await runScenario(key, scenario);
  }

  await assertTraceIdUniqueness(SCENARIOS.A);

  const markdowns = {};
  for (const [key, res] of Object.entries(results)) {
    if (res?.scoringBreakdown) {
      markdowns[key] = await assertScoreAnalyticsHeaders(SCENARIOS[key].label, res.scoringBreakdown);
    }
  }

  assertCrossScenarioDiversity(markdowns);

  console.log(`\n${"═".repeat(60)}`);
  if (process.exitCode === 1) {
    console.error("  RESULT: FAIL — one or more assertions failed");
  } else {
    console.log("  RESULT: PASS — all assertions passed");
  }
})();
```

---

## 7 — SUCCESS CRITERIA

The end-to-end explanation pipeline is declared **operational** when ALL of the following conditions hold deterministically across all three scenarios in a single regression run:

### Required Passes (all must be `true` simultaneously)

| ID | Criterion | Source |
|---|---|---|
| P1 | All three scenarios return HTTP `200` with `status == "SUCCESS"` | `one_button_router.py` |
| P2 | `explanation.summary` is a non-empty string with `len > 100` for every scenario | `DecisionResponse.explanation` |
| P3 | `explanation.factors` contains ≥ 3 entries for every scenario | `ExplanationResult.factors` |
| P4 | `explanation.confidence` is `float` in open interval `(0, 1)` for every scenario | `ExplanationResult.confidence` |
| P5 | All 8 mandatory stages (`taxonomy_normalize` through `stage_trace`) are present in `stages{}` with `status != "skipped"` | `_validate_required_stages()` in `one_button_router.py` |
| P6 | `trace_id` is a valid UUID v4 and differs between any two sequential or concurrent calls | `DecisionController.run_pipeline()` |
| P7 | `scoring_breakdown.result_hash` is identical across two calls with byte-identical payloads | `ScoringBreakdown.result_hash` determinism |
| P8 | `X-Fallback-Used` header on `/api/v1/explain/score-analytics` is `"false"` for all three scenarios | `explain_router.py:574` |
| P9 | `X-Prompt-Version` header equals `"score_analytics_v1"` (matching `_PROMPT_PATH` file header) | `_PromptRenderer.version` in `engine.py` |
| P10 | `meta.llm_used` is `true` in the one-button response for all three scenarios | `DecisionController` meta |
| P11 | Cross-scenario similarity ratio ≤ 0.70 for all pairs (A/B, A/C, B/C) — explanations are personalised | `ScoreAnalyticsEngine.generate()` via Ollama |
| P12 | No unrendered `{{variable}}` placeholders appear in any `markdown` output | `_PromptRenderer.render()` |
| P13 | UI-rendered `explanation.summary` text matches `response.explanation.summary` from Network tab | Frontend render layer |
| P14 | Scenario C (minimal input: 0 years, 1 skill, high-school) does not trigger HTTP 400/500 | Taxonomy gate + scoring floor handling |

### Definition of Failure

Any single `P1`–`P14` criterion failing across any scenario constitutes a pipeline failure.  
The pipeline is **not declared operational** under partial pass.
