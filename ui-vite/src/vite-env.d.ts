/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_ADMIN_REQUEST_TIMEOUT_MS: string;
  readonly VITE_EXPLAIN_API_VERSION: string;
  readonly VITE_EXPLAIN_SHOW_META: string;
  readonly VITE_EXPLAIN_ENABLE_DETAIL: string;
  readonly VITE_EXPLAIN_TIMEOUT_MS: string;
  readonly VITE_EXPLAIN_ENABLE_CACHE: string;
  readonly VITE_EXPLAIN_MAX_CACHE_AGE: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
