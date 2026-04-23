// tests/regression/e2e_pipeline_regression.mjs
// Node.js 18+ (native fetch required)
//
// Usage:
//   node tests/regression/e2e_pipeline_regression.mjs
//
// Environment:
//   API_TOKEN  — Bearer token if auth middleware is active (omit if not required)
//   BASE_URL   — override base URL (default: http://127.0.0.1:8000)
//
// Exit codes:
//   0 — all assertions passed
//   1 — one or more assertions failed

const BASE            = (process.env.BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const ONE_BUTTON      = `${BASE}/api/v1/decision/run`;      // real registered endpoint
const SCORE_ANALYTICS = `${BASE}/api/v1/explain/score-analytics`;
const AUTH_TOKEN      = process.env.API_TOKEN ?? "";

// ─────────────────────────────────────────────────────────────────────────────
// Scenarios — mapped to backend/scoring/models.py::ScoringInput
// ─────────────────────────────────────────────────────────────────────────────

// options must be explicitly set so include_explanation=true activates the
// explanation stage (defaults to true in DecisionOptions, but only fires when
// options object is present in the request).
const FORCED_OPTIONS = { include_explanation: true, include_market_data: true };

const SCENARIOS = {
  A: {
    label: "Scenario A — Technical Profile",
    expectedSkills: ["python", "sql"],
    body: {
      user_id: "regression_a",
      options: FORCED_OPTIONS,
      scoring_input: {
        personal_profile: {
          ability_score:    0.70,
          confidence_score: 0.68,
          interests: ["data science", "automation", "cloud computing"]
        },
        experience: { years: 4, domains: ["software engineering", "data pipelines"] },
        goals: { career_aspirations: ["data engineer", "ml engineer"], timeline_years: 3 },
        skills: ["python", "sql", "machine learning", "docker"],
        education: { level: "bachelor", field_of_study: "computer science" },
        preferences: { preferred_domains: ["technology"], work_style: "hybrid" }
      }
    }
  },
  B: {
    label: "Scenario B — Non-Technical Profile",
    expectedSkills: ["sociology", "social"],
    body: {
      user_id: "regression_b",
      options: FORCED_OPTIONS,
      scoring_input: {
        personal_profile: {
          ability_score:    0.65,
          confidence_score: 0.60,
          interests: ["education", "community development", "social policy"]
        },
        experience: { years: 6, domains: ["non-profit", "program coordination"] },
        goals: { career_aspirations: ["policy analyst", "community manager"], timeline_years: 5 },
        skills: ["public speaking", "project management", "writing"],
        education: { level: "bachelor", field_of_study: "sociology" },
        preferences: { preferred_domains: ["social services", "government"], work_style: "in-office" }
      }
    }
  },
  C: {
    label: "Scenario C — Minimal Edge Case",
    expectedSkills: ["excel", "finance"],
    body: {
      user_id: "regression_c",
      options: FORCED_OPTIONS,
      scoring_input: {
        personal_profile: {
          ability_score:    0.40,
          confidence_score: 0.35,
          interests: ["finance"]
        },
        experience: { years: 0, domains: ["general"] },
        goals: { career_aspirations: ["accountant"], timeline_years: 5 },
        skills: ["excel"],
        education: { level: "high school", field_of_study: "general" },
        preferences: { preferred_domains: ["finance"], work_style: "in-office" }
      }
    }
  }
};

// Real stage names from DecisionController.stages_completed[]
const REQUIRED_STAGES = [
  "input_normalize", "feature_extraction", "kb_alignment", "merge",
  "simgr_scoring", "drift_check", "rule_engine", "market_data", "explanation"
];

// Real scoring_breakdown fields confirmed from live probe
const SCORING_BREAKDOWN_FIELDS = [
  "skill_score", "experience_score", "education_score",
  "goal_alignment_score", "preference_score", "final_score", "result_hash"
];

// trace_id format from DecisionController: "dec-XXXXXXXXXXXX" (12 hex chars)
const TRACE_ID_RE = /^dec-[0-9a-f]{12}$/i;
const STUB_SIGNATURE = "Skills: {{skills}}";

// ─────────────────────────────────────────────────────────────────────────────
// Assertion helpers
// ─────────────────────────────────────────────────────────────────────────────

let _failures = 0;

function pass(label) {
  console.log(`    \x1b[32m✔\x1b[0m  ${label}`);
}

function fail(label, detail) {
  console.error(`    \x1b[31m✖\x1b[0m  ${label}`);
  if (detail !== undefined) {
    const d = typeof detail === "object" ? JSON.stringify(detail) : String(detail);
    console.error(`         detail: ${d.slice(0, 200)}`);
  }
  _failures++;
}

function assert(condition, label, detail) {
  if (condition) pass(label);
  else fail(label, detail);
}

/**
 * Word-overlap similarity in [0,1].
 * Lower = more different = better for diversity assertion.
 */
function similarityRatio(a, b) {
  const wordsA = a.toLowerCase().split(/\s+/).filter(Boolean);
  const wordsB = new Set(b.toLowerCase().split(/\s+/).filter(Boolean));
  if (wordsA.length === 0 && wordsB.size === 0) return 1;
  let common = 0;
  for (const w of wordsA) if (wordsB.has(w)) common++;
  return common / Math.max(wordsA.length, wordsB.size);
}

// ─────────────────────────────────────────────────────────────────────────────
// HTTP helpers
// ─────────────────────────────────────────────────────────────────────────────

function buildHeaders() {
  const h = { "Content-Type": "application/json" };
  if (AUTH_TOKEN) h["Authorization"] = `Bearer ${AUTH_TOKEN}`;
  return h;
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method:  "POST",
    headers: buildHeaders(),
    body:    JSON.stringify(body)
  });
  const data = await res.json();
  return { res, data };
}

// ─────────────────────────────────────────────────────────────────────────────
// One-button scenario runner
// ─────────────────────────────────────────────────────────────────────────────

async function runOneButtonScenario(key, scenario) {
  console.log(`\n  ${"─".repeat(56)}`);
  console.log(`  ${scenario.label}`);
  console.log(`  ${"─".repeat(56)}`);

  let res, data;
  try {
    ({ res, data } = await postJSON(ONE_BUTTON, scenario.body));
  } catch (err) {
    fail("Network request to /api/v1/one-button/run", err.message);
    return null;
  }

  // HTTP + pipeline status
  assert(res.status === 200, `HTTP 200 (got ${res.status})`);
  assert(data.status === "SUCCESS", `response.status == "SUCCESS"`, data.status);

  // trace_id — format: dec-XXXXXXXXXXXX
  assert(
    typeof data.trace_id === "string" && TRACE_ID_RE.test(data.trace_id),
    `trace_id matches dec-XXXXXXXXXXXX format`, data.trace_id
  );

  // explanation
  const expl = data.explanation;
  const explPresent = expl !== null && typeof expl === "object" && Object.keys(expl).length > 0;
  assert(explPresent, "explanation is non-empty object", expl);

  if (explPresent) {
    assert(
      typeof expl.summary === "string" && expl.summary.length >= 100,
      `explanation.summary length >= 100 (got ${expl.summary?.length ?? 0})`
    );
    assert(
      Array.isArray(expl.factors) && expl.factors.length >= 3,
      `explanation.factors.length >= 3 (got ${expl.factors?.length ?? 0})`
    );
    assert(
      typeof expl.confidence === "number" && expl.confidence > 0 && expl.confidence < 1,
      `explanation.confidence in (0,1) (got ${expl.confidence})`
    );
    assert(
      Array.isArray(expl.reasoning_chain) && expl.reasoning_chain.length >= 1,
      "explanation.reasoning_chain non-empty"
    );
  }

  // scoring_breakdown
  const sb = data.scoring_breakdown;
  assert(sb !== null && typeof sb === "object", "scoring_breakdown present");
  if (sb) {
    for (const field of SCORING_BREAKDOWN_FIELDS) {
      assert(field in sb, `scoring_breakdown.${field} present`);
    }
  }

  // Pipeline stages — validated via meta.stages_completed[] array
  const completed = Array.isArray(data.meta?.stages_completed) ? data.meta.stages_completed : [];
  for (const s of REQUIRED_STAGES) {
    assert(completed.includes(s), `meta.stages_completed includes "${s}"`);
  }

  // LLM used flag (true when feature_extraction called Ollama)
  assert(data.meta?.llm_used === true, "meta.llm_used == true", data.meta?.llm_used);

  return {
    traceId:         data.trace_id,
    explanation:     expl,
    scoringBreakdown: sb
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// trace_id uniqueness + scoring determinism
// ─────────────────────────────────────────────────────────────────────────────

async function assertTraceUniquenessAndDeterminism(scenario) {
  console.log(`\n  ── trace_id uniqueness + deterministic hash (${scenario.label}) ──`);

  let r1, r2;
  try {
    // Sequential calls — avoids server race condition on trace_id generation
    ({ data: r1 } = await postJSON(ONE_BUTTON, scenario.body));
    ({ data: r2 } = await postJSON(ONE_BUTTON, scenario.body));
  } catch (err) {
    fail("Sequential pipeline calls", err.message);
    return;
  }

  assert(
    r1.trace_id !== r2.trace_id,
    "Sequential identical-payload calls produce different trace_ids",
    { id1: r1.trace_id, id2: r2.trace_id }
  );

  assert(
    r1.scoring_breakdown?.result_hash === r2.scoring_breakdown?.result_hash,
    "Identical payloads produce identical result_hash (deterministic scorer)",
    { h1: r1.scoring_breakdown?.result_hash, h2: r2.scoring_breakdown?.result_hash }
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// score-analytics endpoint — header validation
// ─────────────────────────────────────────────────────────────────────────────

async function assertScoreAnalyticsHeaders(label, sb) {
  console.log(`\n  ── score-analytics headers (${label}) ──`);
  if (!sb) {
    console.log("    ⚠  skipped — no scoring_breakdown available");
    return null;
  }

  const body = {
    skill_score:          sb.skill_score          ?? 50,
    experience_score:     sb.experience_score     ?? 50,
    education_score:      sb.education_score      ?? 50,
    goal_alignment_score: sb.goal_alignment_score ?? 50,
    preference_score:     sb.preference_score     ?? 50,
    confidence:           0.65,
    skills:               ["python"],
    interests:            ["technology"],
    education_level:      "bachelor",
    years_experience:     2.0
  };

  let res, data;
  try {
    ({ res, data } = await postJSON(SCORE_ANALYTICS, body));
  } catch (err) {
    fail("Network request to /api/v1/explain/score-analytics", err.message);
    return null;
  }

  // 422 means the endpoint has a FastAPI Response-injection schema conflict.
  // Treat as a known infrastructure issue: report but do not crash the runner.
  if (res.status === 422) {
    fail(
      `score-analytics HTTP 200 (got ${res.status}) — endpoint has Response injection conflict`,
      "See explain_router.py: 'response: Response' parameter not resolved as FastAPI dependency"
    );
    return null;
  }

  assert(res.status === 200, `score-analytics HTTP 200 (got ${res.status})`);

  // ── Required diagnostic headers (always present regardless of LLM path) ──
  assert(
    res.headers.get("x-prompt-version") === "score_analytics_v1",
    `X-Prompt-Version == "score_analytics_v1" (prompt file header)`,
    res.headers.get("x-prompt-version")
  );
  assert(
    typeof res.headers.get("x-trace-id") === "string" && res.headers.get("x-trace-id").length > 0,
    "X-Trace-Id header present"
  );
  assert(
    typeof res.headers.get("x-engine-version") === "string",
    "X-Engine-Version header present"
  );

  // Fallback is a valid outcome (LLM may be slow/unavailable in CI);
  // we record mode for informational purposes only.
  const usedLlm  = data.used_llm === true;
  const fallback = data.fallback  === true;
  const fallbackReason = res.headers.get("x-fallback-reason") ?? "unknown";
  if (fallback) {
    console.log(`    ℹ  fallback active (${fallbackReason}) — deterministic content`);
  } else {
    console.log(`    ℹ  LLM path used — X-Fallback-Used: ${res.headers.get("x-fallback-used")}`);
  }
  // Internal consistency: used_llm and fallback must be complementary
  assert(
    usedLlm !== fallback,
    `used_llm (${usedLlm}) XOR fallback (${fallback}) — mutually exclusive`,
    { usedLlm, fallback }
  );

  // Response body — markdown must be present and rendered
  assert(
    typeof data.markdown === "string" && data.markdown.length > 100,
    `markdown length > 100 chars (got ${data.markdown?.length ?? 0})`
  );

  // Stub detection — rendered template must not contain raw placeholder tokens
  if (data.markdown) {
    assert(
      !data.markdown.includes(STUB_SIGNATURE),
      "markdown does not contain unrendered {{skills}} placeholder"
    );
  }

  return { markdown: data.markdown, usedLlm };
}

// ─────────────────────────────────────────────────────────────────────────────
// Cross-scenario diversity
// ─────────────────────────────────────────────────────────────────────────────

function assertCrossScenarioDiversity(results) {
  console.log(`\n  ── Cross-scenario explanation diversity ──`);

  const pairs = [["A","B"], ["A","C"], ["B","C"]];
  for (const [x, y] of pairs) {
    const rx = results[x], ry = results[y];
    if (!rx?.markdown || !ry?.markdown) {
      console.log(`    ⚠  skipped pair ${x}/${y} — markdown unavailable`);
      continue;
    }
    // Diversity only meaningful when LLM produced personalised content;
    // the deterministic fallback template is intentionally identical across scenarios.
    if (!rx.usedLlm || !ry.usedLlm) {
      console.log(`    ⚠  skipped pair ${x}/${y} — fallback active, template output is invariant`);
      continue;
    }
    const ratio = similarityRatio(rx.markdown, ry.markdown);
    assert(
      ratio <= 0.70,
      `Similarity(${x},${y}) = ${ratio.toFixed(3)} <= 0.70 — content personalised`,
      ratio
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────────────────────────────────────

(async () => {
  const startMs = Date.now();
  console.log("╔══════════════════════════════════════════════════════════╗");
  console.log("║   E2E Pipeline Regression — Hybrid Decision Support      ║");
  console.log(`║   ${new Date().toISOString()}              ║`);
  console.log(`║   Target: ${BASE.padEnd(45)} ║`);
  console.log("╚══════════════════════════════════════════════════════════╝");

  // 1. Run all three scenarios through one-button
  const scenarioResults = {};
  for (const [key, scenario] of Object.entries(SCENARIOS)) {
    scenarioResults[key] = await runOneButtonScenario(key, scenario);
  }

  // 2. trace_id uniqueness + hash determinism on Scenario A
  await assertTraceUniquenessAndDeterminism(SCENARIOS.A);

  // 3. score-analytics header validation per scenario
  const analyticsResults = {};
  for (const [key, res] of Object.entries(scenarioResults)) {
    analyticsResults[key] = await assertScoreAnalyticsHeaders(
      SCENARIOS[key].label,
      res?.scoringBreakdown ?? null
    );
  }

  // 4. Cross-scenario diversity (only when LLM produced personalised content)
  assertCrossScenarioDiversity(analyticsResults);

  // ── Summary ─────────────────────────────────────────────────────────────
  const elapsed = ((Date.now() - startMs) / 1000).toFixed(1);
  console.log(`\n${"═".repeat(60)}`);
  console.log(`  Duration : ${elapsed}s`);
  if (_failures > 0) {
    console.error(`  \x1b[31mRESULT  : FAIL — ${_failures} assertion(s) failed\x1b[0m`);
    process.exit(1);
  } else {
    console.log(`  \x1b[32mRESULT  : PASS — all assertions passed\x1b[0m`);
    process.exit(0);
  }
})();
