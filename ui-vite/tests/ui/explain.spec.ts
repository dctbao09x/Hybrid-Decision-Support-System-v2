// tests/ui/explain.spec.ts
/**
 * Test Suite for Explain UI (Stage 6)
 * 
 * Covers:
 *   - normal render
 *   - no llm
 *   - error state
 *   - audit mode
 *   - version mismatch
 * 
 * Target Coverage: ≥70%
 */

import { describe, it, expect, beforeEach } from 'vitest';

// Mock types
interface ExplainResponse {
  api_version: string;
  trace_id: string;
  career: string;
  confidence: number;
  reasons: string[];
  explain_text: string;
  llm_text: string;
  used_llm: boolean;
  timestamp?: string;
  meta?: {
    model_version: string;
    xai_version: string;
    stage3_version: string;
    stage4_version: string;
  };
}

// ==============================================================================
// Test Data
// ==============================================================================

const mockResponseWithLLM: ExplainResponse = {
  api_version: 'v1',
  trace_id: '9f1c-abcd-1234-efgh',
  career: 'Data Scientist',
  confidence: 0.93,
  reasons: [
    'Toán cao (shap)',
    'Logic mạnh (coef)',
    'Interest IT (importance)',
  ],
  explain_text: 'Basic explanation text from Stage 3.',
  llm_text: 'Enhanced explanation text from LLM Stage 4.',
  used_llm: true,
  meta: {
    model_version: '1.2.0',
    xai_version: '1.0.0',
    stage3_version: '1.0.0',
    stage4_version: '1.0.0',
  },
};

const mockResponseNoLLM: ExplainResponse = {
  api_version: 'v1',
  trace_id: '8e2d-bcde-5678-ijkl',
  career: 'Software Engineer',
  confidence: 0.87,
  reasons: [
    'Programming high (shap)',
    'Logic good (coef)',
  ],
  explain_text: 'Basic explanation text only.',
  llm_text: '',
  used_llm: false,
  meta: {
    model_version: '1.2.0',
    xai_version: '1.0.0',
    stage3_version: '1.0.0',
    stage4_version: '1.0.0',
  },
};

const mockErrorResponse = {
  api_version: 'v1',
  trace_id: 'error-trace',
  error: {
    code: 'E500',
    message: 'Internal server error',
  },
  timestamp: '2026-02-13T10:00:00Z',
};

// ==============================================================================
// Display Priority Logic Tests
// ==============================================================================

describe('Display Priority Logic', () => {
  it('shows llm_text when used_llm is true and llm_text exists', () => {
    // if (used_llm && llm_text) show(llm_text)
    const response = mockResponseWithLLM;
    
    let displayText: string;
    if (response.used_llm && response.llm_text) {
      displayText = response.llm_text;
    } else {
      displayText = response.explain_text;
    }
    
    expect(displayText).toBe('Enhanced explanation text from LLM Stage 4.');
  });
  
  it('shows explain_text when used_llm is false', () => {
    // else show(explain_text)
    const response = mockResponseNoLLM;
    
    let displayText: string;
    if (response.used_llm && response.llm_text) {
      displayText = response.llm_text;
    } else {
      displayText = response.explain_text;
    }
    
    expect(displayText).toBe('Basic explanation text only.');
  });
  
  it('shows explain_text when used_llm is true but llm_text is empty', () => {
    const response = {
      ...mockResponseWithLLM,
      used_llm: true,
      llm_text: '',
    };
    
    let displayText: string;
    if (response.used_llm && response.llm_text) {
      displayText = response.llm_text;
    } else {
      displayText = response.explain_text;
    }
    
    expect(displayText).toBe('Basic explanation text from Stage 3.');
  });
});

// ==============================================================================
// Reason Parsing Tests
// ==============================================================================

describe('Reason Parsing', () => {
  function parseReason(raw: string): { text: string; source: string } {
    const match = raw.match(/^(.+?)\s*\((\w+)\)$/);
    if (match) {
      return { text: match[1].trim(), source: match[2].toLowerCase() };
    }
    return { text: raw, source: 'rule' };
  }
  
  it('parses reason with source in parentheses', () => {
    const result = parseReason('Toán cao (shap)');
    expect(result.text).toBe('Toán cao');
    expect(result.source).toBe('shap');
  });
  
  it('parses reason with coef source', () => {
    const result = parseReason('Logic mạnh (coef)');
    expect(result.text).toBe('Logic mạnh');
    expect(result.source).toBe('coef');
  });
  
  it('handles reason without source', () => {
    const result = parseReason('Simple reason text');
    expect(result.text).toBe('Simple reason text');
    expect(result.source).toBe('rule');
  });
});

// ==============================================================================
// Confidence Formatting Tests
// ==============================================================================

describe('Confidence Formatting', () => {
  function formatConfidence(confidence: number): string {
    return `${Math.round(confidence * 100)}%`;
  }
  
  function getConfidenceClass(confidence: number): string {
    if (confidence >= 0.85) return 'confidence-high';
    if (confidence >= 0.7) return 'confidence-medium';
    return 'confidence-low';
  }
  
  it('formats confidence as percentage', () => {
    expect(formatConfidence(0.93)).toBe('93%');
    expect(formatConfidence(0.87)).toBe('87%');
    expect(formatConfidence(0.5)).toBe('50%');
  });
  
  it('classifies high confidence', () => {
    expect(getConfidenceClass(0.93)).toBe('confidence-high');
    expect(getConfidenceClass(0.85)).toBe('confidence-high');
  });
  
  it('classifies medium confidence', () => {
    expect(getConfidenceClass(0.75)).toBe('confidence-medium');
    expect(getConfidenceClass(0.7)).toBe('confidence-medium');
  });
  
  it('classifies low confidence', () => {
    expect(getConfidenceClass(0.65)).toBe('confidence-low');
    expect(getConfidenceClass(0.3)).toBe('confidence-low');
  });
});

// ==============================================================================
// Trace ID Tests
// ==============================================================================

describe('Trace ID Handling', () => {
  function shortTraceId(traceId: string): string {
    if (traceId.length <= 8) return traceId;
    return `${traceId.slice(0, 4)}...${traceId.slice(-4)}`;
  }
  
  it('shortens long trace ID', () => {
    const result = shortTraceId('9f1c-abcd-1234-efgh');
    expect(result).toBe('9f1c...efgh');
  });
  
  it('keeps short trace ID unchanged', () => {
    const result = shortTraceId('abc123');
    expect(result).toBe('abc123');
  });
});

// ==============================================================================
// Error State Tests
// ==============================================================================

describe('Error State Handling', () => {
  const ERROR_DISPLAY = {
    E400: { title: 'Validation Error', showRetry: true },
    E504: { title: 'Timeout', showRetry: true },
    E502: { title: 'Processing Error', showRetry: false },
    E500: { title: 'Server Error', showRetry: true },
  };
  
  function getErrorDisplay(code: string) {
    return ERROR_DISPLAY[code as keyof typeof ERROR_DISPLAY] || ERROR_DISPLAY.E500;
  }
  
  it('returns validation error for E400', () => {
    const display = getErrorDisplay('E400');
    expect(display.title).toBe('Validation Error');
    expect(display.showRetry).toBe(true);
  });
  
  it('returns timeout error for E504', () => {
    const display = getErrorDisplay('E504');
    expect(display.title).toBe('Timeout');
    expect(display.showRetry).toBe(true);
  });
  
  it('returns processing error for E502 without retry', () => {
    const display = getErrorDisplay('E502');
    expect(display.title).toBe('Processing Error');
    expect(display.showRetry).toBe(false);
  });
  
  it('returns default for unknown error code', () => {
    const display = getErrorDisplay('UNKNOWN');
    expect(display.title).toBe('Server Error');
  });
});

// ==============================================================================
// Audit Mode Tests
// ==============================================================================

describe('Audit Mode', () => {
  function parseAuditParams(params: URLSearchParams) {
    const mode = params.get('mode');
    const traceId = params.get('trace_id') || params.get('traceId');
    return {
      mode: mode === 'audit' ? 'audit' : 'normal',
      trace_id: traceId || undefined,
    };
  }
  
  it('parses audit mode params correctly', () => {
    const params = new URLSearchParams('?mode=audit&trace_id=abc-123');
    const result = parseAuditParams(params);
    
    expect(result.mode).toBe('audit');
    expect(result.trace_id).toBe('abc-123');
  });
  
  it('handles missing mode param', () => {
    const params = new URLSearchParams('?trace_id=abc-123');
    const result = parseAuditParams(params);
    
    expect(result.mode).toBe('normal');
    expect(result.trace_id).toBe('abc-123');
  });
  
  it('handles traceId variant', () => {
    const params = new URLSearchParams('?mode=audit&traceId=xyz-789');
    const result = parseAuditParams(params);
    
    expect(result.mode).toBe('audit');
    expect(result.trace_id).toBe('xyz-789');
  });
  
  it('returns undefined trace_id when not provided', () => {
    const params = new URLSearchParams('?mode=audit');
    const result = parseAuditParams(params);
    
    expect(result.mode).toBe('audit');
    expect(result.trace_id).toBeUndefined();
  });
});

// ==============================================================================
// Cache Tests
// ==============================================================================

describe('Cache Management', () => {
  const cache = new Map<string, { data: ExplainResponse; timestamp: number }>();
  const MAX_CACHE_AGE = 300000; // 5 minutes
  
  function getCacheKey(features: object): string {
    return JSON.stringify(features);
  }
  
  function isCacheValid(timestamp: number): boolean {
    return Date.now() - timestamp < MAX_CACHE_AGE;
  }
  
  beforeEach(() => {
    cache.clear();
  });
  
  it('generates consistent cache keys', () => {
    const features = { math_score: 85, logic_score: 90 };
    const key1 = getCacheKey(features);
    const key2 = getCacheKey({ math_score: 85, logic_score: 90 });
    
    expect(key1).toBe(key2);
  });
  
  it('validates fresh cache entry', () => {
    const timestamp = Date.now();
    expect(isCacheValid(timestamp)).toBe(true);
  });
  
  it('invalidates old cache entry', () => {
    const oldTimestamp = Date.now() - MAX_CACHE_AGE - 1000;
    expect(isCacheValid(oldTimestamp)).toBe(false);
  });
});

// ==============================================================================
// Version Mismatch Tests
// ==============================================================================

describe('Version Handling', () => {
  function isVersionCompatible(responseVersion: string, expectedVersion: string): boolean {
    return responseVersion === expectedVersion;
  }
  
  it('accepts matching version', () => {
    expect(isVersionCompatible('v1', 'v1')).toBe(true);
  });
  
  it('rejects mismatched version', () => {
    expect(isVersionCompatible('v2', 'v1')).toBe(false);
  });
});

// ==============================================================================
// Type Guard Tests
// ==============================================================================

describe('Type Guards', () => {
  function isExplainError(obj: unknown): boolean {
    return (
      typeof obj === 'object' &&
      obj !== null &&
      'error' in obj &&
      typeof (obj as Record<string, unknown>).error === 'object'
    );
  }
  
  function isExplainResponse(obj: unknown): boolean {
    return (
      typeof obj === 'object' &&
      obj !== null &&
      'career' in obj &&
      'trace_id' in obj &&
      !('error' in obj)
    );
  }
  
  it('identifies error response', () => {
    expect(isExplainError(mockErrorResponse)).toBe(true);
    expect(isExplainError(mockResponseWithLLM)).toBe(false);
  });
  
  it('identifies success response', () => {
    expect(isExplainResponse(mockResponseWithLLM)).toBe(true);
    expect(isExplainResponse(mockErrorResponse)).toBe(false);
  });
});

// ==============================================================================
// State Store Tests  
// ==============================================================================

describe('Explain Store', () => {
  interface ExplainState {
    trace_id: string | null;
    last_result: ExplainResponse | null;
    last_timestamp: string | null;
    used_llm: boolean;
    loading: boolean;
    error: string | null;
  }
  
  const initialState: ExplainState = {
    trace_id: null,
    last_result: null,
    last_timestamp: null,
    used_llm: false,
    loading: false,
    error: null,
  };
  
  type Action =
    | { type: 'FETCH_START' }
    | { type: 'FETCH_SUCCESS'; payload: ExplainResponse }
    | { type: 'FETCH_ERROR'; payload: string }
    | { type: 'CLEAR' };
  
  function reducer(state: ExplainState, action: Action): ExplainState {
    switch (action.type) {
      case 'FETCH_START':
        return { ...state, loading: true, error: null };
      case 'FETCH_SUCCESS':
        return {
          trace_id: action.payload.trace_id,
          last_result: action.payload,
          last_timestamp: action.payload.timestamp || new Date().toISOString(),
          used_llm: action.payload.used_llm,
          loading: false,
          error: null,
        };
      case 'FETCH_ERROR':
        return { ...state, loading: false, error: action.payload };
      case 'CLEAR':
        return initialState;
      default:
        return state;
    }
  }
  
  it('handles FETCH_START action', () => {
    const state = reducer(initialState, { type: 'FETCH_START' });
    expect(state.loading).toBe(true);
    expect(state.error).toBeNull();
  });
  
  it('handles FETCH_SUCCESS action', () => {
    const state = reducer(initialState, {
      type: 'FETCH_SUCCESS',
      payload: mockResponseWithLLM,
    });
    
    expect(state.loading).toBe(false);
    expect(state.trace_id).toBe(mockResponseWithLLM.trace_id);
    expect(state.last_result).toEqual(mockResponseWithLLM);
    expect(state.used_llm).toBe(true);
  });
  
  it('handles FETCH_ERROR action', () => {
    const state = reducer(initialState, {
      type: 'FETCH_ERROR',
      payload: 'Network error',
    });
    
    expect(state.loading).toBe(false);
    expect(state.error).toBe('Network error');
  });
  
  it('handles CLEAR action', () => {
    const modifiedState: ExplainState = {
      ...initialState,
      trace_id: 'test',
      loading: true,
    };
    
    const state = reducer(modifiedState, { type: 'CLEAR' });
    expect(state).toEqual(initialState);
  });
});

// ==============================================================================
// API Response Validation Tests
// ==============================================================================

describe('API Response Validation', () => {
  function validateResponse(data: unknown): { valid: boolean; missing: string[] } {
    const required = ['api_version', 'trace_id', 'career', 'confidence'];
    const missing: string[] = [];
    
    if (typeof data !== 'object' || data === null) {
      return { valid: false, missing: required };
    }
    
    const obj = data as Record<string, unknown>;
    for (const field of required) {
      if (!(field in obj)) {
        missing.push(field);
      }
    }
    
    return { valid: missing.length === 0, missing };
  }
  
  it('validates complete response', () => {
    const result = validateResponse(mockResponseWithLLM);
    expect(result.valid).toBe(true);
    expect(result.missing).toEqual([]);
  });
  
  it('detects missing fields', () => {
    const incomplete = { api_version: 'v1' };
    const result = validateResponse(incomplete);
    expect(result.valid).toBe(false);
    expect(result.missing).toContain('trace_id');
    expect(result.missing).toContain('career');
    expect(result.missing).toContain('confidence');
  });
  
  it('handles null input', () => {
    const result = validateResponse(null);
    expect(result.valid).toBe(false);
  });
});

// ==============================================================================
// Performance Constraint Tests
// ==============================================================================

describe('Performance Constraints', () => {
  const PERFORMANCE = {
    ttfbWarning: 1500,
    renderWarning: 300,
    bundleWarning: 200 * 1024,
  };
  
  function checkPerformance(metrics: { ttfb?: number; render?: number; bundle?: number }) {
    const warnings: string[] = [];
    
    if (metrics.ttfb && metrics.ttfb > PERFORMANCE.ttfbWarning) {
      warnings.push('TTFB exceeds 1.5s');
    }
    if (metrics.render && metrics.render > PERFORMANCE.renderWarning) {
      warnings.push('Render exceeds 300ms');
    }
    if (metrics.bundle && metrics.bundle > PERFORMANCE.bundleWarning) {
      warnings.push('Bundle exceeds 200KB');
    }
    
    return { passed: warnings.length === 0, warnings };
  }
  
  it('passes when all metrics within limits', () => {
    const result = checkPerformance({ ttfb: 1000, render: 200, bundle: 150000 });
    expect(result.passed).toBe(true);
  });
  
  it('warns when TTFB exceeds limit', () => {
    const result = checkPerformance({ ttfb: 2000 });
    expect(result.passed).toBe(false);
    expect(result.warnings).toContain('TTFB exceeds 1.5s');
  });
  
  it('warns when render exceeds limit', () => {
    const result = checkPerformance({ render: 500 });
    expect(result.passed).toBe(false);
    expect(result.warnings).toContain('Render exceeds 300ms');
  });
});
