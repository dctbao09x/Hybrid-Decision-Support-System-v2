// src/config/explain.ts
/**
 * Configuration for Explain UI (Stage 6)
 * 
 * All config values can be overridden via environment variables.
 * No hardcoded URLs - use VITE_* env vars.
 */

import type { ExplainConfig } from '../types/explain';

/**
 * Main explain configuration.
 * Loaded from environment variables with fallback defaults.
 */
export const EXPLAIN: ExplainConfig = {
  // UI display options
  showMeta: import.meta.env.VITE_EXPLAIN_SHOW_META !== 'false',
  enableDetail: import.meta.env.VITE_EXPLAIN_ENABLE_DETAIL !== 'false',

  // API settings
  apiVersion: import.meta.env.VITE_EXPLAIN_API_VERSION || 'v1',
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? '',
  timeoutMs: Number(import.meta.env.VITE_EXPLAIN_TIMEOUT_MS) || 30000,  // 30s for slow LLM

  // Cache settings
  enableCache: import.meta.env.VITE_EXPLAIN_ENABLE_CACHE !== 'false',
  maxCacheAge: Number(import.meta.env.VITE_EXPLAIN_MAX_CACHE_AGE) || 300000, // 5 minutes

  // Version identifiers — MUST be bumped on every prompt/engine change.
  // These are baked into the cache key at build time, guaranteeing
  // zero-stale cache entries after every deployment.
  promptVersion: import.meta.env.VITE_PROMPT_VERSION || 'score_analytics_v1',
  engineVersion: import.meta.env.VITE_ENGINE_VERSION || '2.0.0',
};

/**
 * API endpoints configuration.
 */
export const ENDPOINTS = {
  explain: `/api/${EXPLAIN.apiVersion}/explain`,
  health: `/api/${EXPLAIN.apiVersion}/health`,
} as const;

/**
 * Error code display mapping.
 */
export const ERROR_DISPLAY = {
  E400: {
    title: 'Dữ liệu không hợp lệ',
    message: 'Vui lòng kiểm tra lại thông tin đầu vào.',
    showRetry: true,
  },
  E504: {
    title: 'Hết thời gian chờ',
    message: 'Hệ thống đang xử lý quá lâu. Vui lòng thử lại sau.',
    showRetry: true,
  },
  E502: {
    title: 'Lỗi xử lý',
    message: 'Không thể hoàn tất phân tích. Đang sử dụng kết quả cơ bản.',
    showRetry: false,
  },
  E500: {
    title: 'Lỗi hệ thống',
    message: 'Đã xảy ra lỗi. Vui lòng thử lại sau.',
    showRetry: true,
  },
} as const;

/**
 * Reason source display mapping.
 */
export const SOURCE_LABELS: Record<string, string> = {
  shap: 'SHAP Analysis',
  coef: 'Model Coefficient',
  perm: 'Permutation Importance',
  importance: 'Feature Importance',
  rule: 'Domain Rule',
  model: 'ML Model',
  fallback: 'Basic Analysis',
};

/**
 * UI text labels (Vietnamese).
 */
export const LABELS = {
  career: 'Nghề phù hợp',
  confidence: 'Độ tin cậy',
  analysis: 'Phân tích',
  reasons: 'Cơ sở lý luận',
  trace: 'Mã truy vết',
  loading: 'Đang phân tích...',
  error: 'Có lỗi xảy ra',
  retry: 'Thử lại',
  expand: 'Xem chi tiết',
  collapse: 'Thu gọn',
  audit_mode: 'Chế độ kiểm tra',
  no_data: 'Chưa có dữ liệu',
  llm_badge: 'AI Enhanced',
  basic_badge: 'Basic',
} as const;

/**
 * Performance thresholds (for monitoring).
 */
export const PERFORMANCE = {
  ttfbWarning: 1500, // 1.5s
  renderWarning: 300, // 300ms
  bundleWarning: 200 * 1024, // 200KB
} as const;

export default EXPLAIN;
