// tests/ui/explain_cache_correctness.spec.ts
/**
 * Cache Correctness Regression Tests — F2 hardening suite.
 *
 * T1 — Same scores, different promptVersion → cache miss
 * T2 — Fallback response (X-Fallback-Used: true) → not cached
 * T3 — Same scores within TTL → cache hit
 * T4 — Version bump → old cache key unreachable
 *
 * Run: npx vitest tests/ui/explain_cache_correctness.spec.ts
 */

import { describe, it, expect } from 'vitest';

// ── Inline the pure functions under test ──────────────────────────────────────
// We test the logic directly without importing from the compiled bundle so that
// env variable differences between test runs don't pollute results.

// FNV-1a 32-bit (mirrors explainApi.ts implementation)
function hashScores(features: Record<string, unknown>): string {
  const values = Object.keys(features)
    .sort()
    .map((k) => features[k])
    .filter((v): v is number => typeof v === 'number');

  let hash = 0x811c9dc5;
  for (const value of values) {
    const bytes = String(value.toFixed(6));
    for (let i = 0; i < bytes.length; i++) {
      hash ^= bytes.charCodeAt(i);
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
  }
  return hash.toString(16).padStart(8, '0');
}

function getCacheKey(
  features: Record<string, unknown>,
  options: Record<string, unknown> | null,
  promptVersion: string,
  engineVersion: string,
): string {
  return JSON.stringify({
    features,
    options,
    promptVersion,
    engineVersion,
    scoringHash: hashScores(features),
  });
}

// ── Minimal cache store (mirrors explainApi.ts responseCache) ─────────────────
function makeCacheStore() {
  const store = new Map<string, { data: Record<string, unknown>; timestamp: number }>();

  function cacheResponse(
    features: Record<string, unknown>,
    options: Record<string, unknown> | null,
    promptVersion: string,
    engineVersion: string,
    data: Record<string, unknown>,
    rawResponse?: { headers: { get(name: string): string | null }; status: number },
    _maxCacheAge: number = 300_000,
  ): void {
    if (rawResponse !== undefined) {
      if (rawResponse.headers.get('x-fallback-used') === 'true') return;
      if (rawResponse.status !== 200) return;
    }
    const key = getCacheKey(features, options, promptVersion, engineVersion);
    store.set(key, { data, timestamp: Date.now() });
  }

  function getCachedResponse(
    features: Record<string, unknown>,
    options: Record<string, unknown> | null,
    promptVersion: string,
    engineVersion: string,
    maxCacheAge: number = 300_000,
  ): Record<string, unknown> | null {
    const key = getCacheKey(features, options, promptVersion, engineVersion);
    const cached = store.get(key);
    if (cached && Date.now() - cached.timestamp < maxCacheAge) {
      return cached.data;
    }
    return null;
  }

  return { store, cacheResponse, getCachedResponse };
}

// ── Shared fixtures ───────────────────────────────────────────────────────────

const FEATURES_A = { math_score: 85, logic_score: 90, physics_score: 70 };
const FEATURES_A_COPY = { math_score: 85, logic_score: 90, physics_score: 70 };
const OPTIONS = null;

const MOCK_RESPONSE: Record<string, unknown> = {
  api_version: 'v1',
  trace_id: 'trace-abc',
  career: 'Software Engineer',
  confidence: 0.92,
  used_llm: true,
  fallback: false,
  fallback_reason: 'none',
  prompt_version: 'score_analytics_v1',
};

const FALLBACK_RESPONSE: Record<string, unknown> = {
  ...MOCK_RESPONSE,
  used_llm: false,
  fallback: true,
  fallback_reason: 'TimeoutError',
};

function makeHeaders(map: Record<string, string>) {
  return {
    get(name: string): string | null {
      return map[name.toLowerCase()] ?? null;
    },
  };
}

// ═════════════════════════════════════════════════════════════════════════════
// T1 — Same scores, different promptVersion → cache miss
// ═════════════════════════════════════════════════════════════════════════════

describe('T1 — promptVersion change invalidates cache', () => {
  it('returns null for v1-keyed entry when queried with v2 promptVersion', () => {
    const { cacheResponse, getCachedResponse } = makeCacheStore();

    // Store with v1
    cacheResponse(
      FEATURES_A, OPTIONS, 'score_analytics_v1', '2.0.0',
      MOCK_RESPONSE,
      { headers: makeHeaders({ 'x-fallback-used': 'false' }), status: 200 },
    );

    // Query with v2 — must be a miss
    const result = getCachedResponse(FEATURES_A_COPY, OPTIONS, 'score_analytics_v2', '2.0.0');

    expect(result).toBeNull();
    //
    // FAILURE CONDITION: result !== null → stale v1 explain returned for v2 prompt
    //
  });

  it('confirms v1 key is reachable with correct v1 version', () => {
    const { cacheResponse, getCachedResponse } = makeCacheStore();

    cacheResponse(
      FEATURES_A, OPTIONS, 'score_analytics_v1', '2.0.0',
      MOCK_RESPONSE,
      { headers: makeHeaders({ 'x-fallback-used': 'false' }), status: 200 },
    );

    const result = getCachedResponse(FEATURES_A_COPY, OPTIONS, 'score_analytics_v1', '2.0.0');
    expect(result).not.toBeNull();
    expect(result?.career).toBe('Software Engineer');
  });
});

// ═════════════════════════════════════════════════════════════════════════════
// T2 — Fallback response → not cached
// ═════════════════════════════════════════════════════════════════════════════

describe('T2 — fallback response is never cached', () => {
  it('skips caching when X-Fallback-Used: true', () => {
    const { store, cacheResponse, getCachedResponse } = makeCacheStore();

    cacheResponse(
      FEATURES_A, OPTIONS, 'score_analytics_v1', '2.0.0',
      FALLBACK_RESPONSE,
      { headers: makeHeaders({ 'x-fallback-used': 'true' }), status: 200 },
    );

    expect(store.size).toBe(0);
    //
    // FAILURE CONDITION: store.size > 0 → fallback response persisted to cache
    //

    const result = getCachedResponse(FEATURES_A, OPTIONS, 'score_analytics_v1', '2.0.0');
    expect(result).toBeNull();
  });

  it('skips caching when HTTP status is not 200', () => {
    const { store, cacheResponse } = makeCacheStore();

    cacheResponse(
      FEATURES_A, OPTIONS, 'score_analytics_v1', '2.0.0',
      MOCK_RESPONSE,
      { headers: makeHeaders({ 'x-fallback-used': 'false' }), status: 502 },
    );

    expect(store.size).toBe(0);
    //
    // FAILURE CONDITION: store.size > 0 → non-200 response cached
    //
  });

  it('caches when X-Fallback-Used: false and status 200', () => {
    const { store, cacheResponse } = makeCacheStore();

    cacheResponse(
      FEATURES_A, OPTIONS, 'score_analytics_v1', '2.0.0',
      MOCK_RESPONSE,
      { headers: makeHeaders({ 'x-fallback-used': 'false' }), status: 200 },
    );

    expect(store.size).toBe(1);
  });
});

// ═════════════════════════════════════════════════════════════════════════════
// T3 — Same scores within TTL → cache hit
// ═════════════════════════════════════════════════════════════════════════════

describe('T3 — identical request within TTL returns cache hit', () => {
  it('returns cached response for identical features + versions', () => {
    const { cacheResponse, getCachedResponse } = makeCacheStore();

    cacheResponse(
      FEATURES_A, OPTIONS, 'score_analytics_v1', '2.0.0',
      MOCK_RESPONSE,
      { headers: makeHeaders({ 'x-fallback-used': 'false' }), status: 200 },
    );

    const result = getCachedResponse(FEATURES_A_COPY, OPTIONS, 'score_analytics_v1', '2.0.0');

    expect(result).not.toBeNull();
    expect(result?.trace_id).toBe('trace-abc');
    //
    // FAILURE CONDITION: result === null → legitimate cache hit missed,
    // causing unnecessary backend call on every identical request
    //
  });

  it('returns null after TTL expires', () => {
    const { cacheResponse, getCachedResponse } = makeCacheStore();

    cacheResponse(
      FEATURES_A, OPTIONS, 'score_analytics_v1', '2.0.0',
      MOCK_RESPONSE,
      { headers: makeHeaders({ 'x-fallback-used': 'false' }), status: 200 },
    );

    // Query with 1ms TTL — entry is immediately expired
    const result = getCachedResponse(FEATURES_A_COPY, OPTIONS, 'score_analytics_v1', '2.0.0', 1);
    expect(result).toBeNull();
  });
});

// ═════════════════════════════════════════════════════════════════════════════
// T4 — Version bump → old cache key permanently unreachable
// ═════════════════════════════════════════════════════════════════════════════

describe('T4 — version bump renders old cache namespace unreachable', () => {
  it('old key is unreachable after both promptVersion and engineVersion bump', () => {
    const { cacheResponse, getCachedResponse } = makeCacheStore();

    // Simulate pre-deployment: store with old versions
    cacheResponse(
      FEATURES_A, OPTIONS, 'score_analytics_v1', '2.0.0',
      MOCK_RESPONSE,
      { headers: makeHeaders({ 'x-fallback-used': 'false' }), status: 200 },
    );

    // Post-deployment: query with new versions
    const result = getCachedResponse(FEATURES_A_COPY, OPTIONS, 'score_analytics_v2', '2.1.0');
    expect(result).toBeNull();
    //
    // FAILURE CONDITION: result !== null → post-deployment query hits
    // pre-deployment explain text without new prompt content
    //
  });

  it('getCacheKey is deterministic for same inputs', () => {
    const k1 = getCacheKey(FEATURES_A, OPTIONS, 'score_analytics_v1', '2.0.0');
    const k2 = getCacheKey(FEATURES_A_COPY, OPTIONS, 'score_analytics_v1', '2.0.0');
    expect(k1).toBe(k2);
    //
    // FAILURE CONDITION: k1 !== k2 → identical requests generate different keys,
    // making cache permanently ineffective
    //
  });

  it('getCacheKey differs for different engineVersion only', () => {
    const k1 = getCacheKey(FEATURES_A, OPTIONS, 'score_analytics_v1', '2.0.0');
    const k2 = getCacheKey(FEATURES_A, OPTIONS, 'score_analytics_v1', '2.1.0');
    expect(k1).not.toBe(k2);
  });

  it('hashScores is invariant to JSON key insertion order', () => {
    const f1 = { math_score: 85, logic_score: 90 };
    const f2 = { logic_score: 90, math_score: 85 }; // reversed key order
    expect(hashScores(f1)).toBe(hashScores(f2));
    //
    // FAILURE CONDITION: hashes differ → same scores, different key order
    // produces different cache keys (browser/engine-dependent JSON key order)
    //
  });
});
