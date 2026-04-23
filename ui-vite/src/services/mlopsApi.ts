// src/services/mlopsApi.ts
/**
 * MLOps API (Admin Only)
 * Used by Admin MLOps panel
 */

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');
const MLOPS_BASE = `${API_BASE_URL}/api/v1/mlops`;

/** Governance-grade ML registry endpoint base (Prompt-12) */
const ML_REGISTRY_BASE = `${API_BASE_URL}/api/v1/ml`;

// Lazily import adminSession to avoid circular deps at module scope
let _getAdminSession: () => { accessToken: string; csrfToken: string } = () => ({ accessToken: '', csrfToken: '' });
import('../utils/adminSession').then((m) => {
  _getAdminSession = m.getAdminSession as () => { accessToken: string; csrfToken: string };
});

const SAFE_HTTP_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

// ═══════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════

export interface ModelVersion {
  version: string;
  status: 'training' | 'staged' | 'production' | 'archived';
  created_at: string;
  metrics: Record<string, number>;
}

export interface TrainingJob {
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  started_at: string;
  completed_at?: string;
  progress: number;
  metrics?: Record<string, number>;
}

export interface DeploymentStatus {
  current_version: string;
  staged_version?: string;
  last_deployed: string;
  health: 'healthy' | 'degraded' | 'unhealthy';
}

// ═══════════════════════════════════════════════════════════════════
// HELPER FUNCTIONS
// ═══════════════════════════════════════════════════════════════════

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase();
  const { accessToken, csrfToken } = _getAdminSession();

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> ?? {}),
  };

  if (accessToken) {
    headers['Authorization'] = `Bearer ${accessToken}`;
  }

  // Send CSRF token for every mutating request
  if (!SAFE_HTTP_METHODS.has(method) && csrfToken) {
    headers['X-CSRF-Token'] = csrfToken;
  }

  const response = await fetch(url, {
    ...options,
    credentials: 'include',
    headers,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

// ═══════════════════════════════════════════════════════════════════
// MLOPS API EXPORT
// ═══════════════════════════════════════════════════════════════════

export const mlopsApi = {
  // Legacy compatibility aliases used by existing Admin MLOps page
  models: (): Promise<Record<string, unknown>> => request(`${MLOPS_BASE}/models`),
  runs: (): Promise<Record<string, unknown>> => request(`${MLOPS_BASE}/runs`),
  monitor: (): Promise<Record<string, unknown>> => request(`${MLOPS_BASE}/monitor`),
  train: (payload: Record<string, unknown>): Promise<Record<string, unknown>> =>
    request(`${MLOPS_BASE}/train`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  validate: (payload: Record<string, unknown>): Promise<Record<string, unknown>> =>
    request(`${MLOPS_BASE}/validate`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  deploy: (payload: Record<string, unknown>): Promise<Record<string, unknown>> =>
    request(`${MLOPS_BASE}/deploy`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  rollback: (payload: Record<string, unknown>): Promise<Record<string, unknown>> =>
    request(`${MLOPS_BASE}/rollback`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // Models
  listModels: (): Promise<ModelVersion[]> => 
    request(`${MLOPS_BASE}/models`),
  
  getModel: (version: string): Promise<ModelVersion> => 
    request(`${MLOPS_BASE}/models/${version}`),
  
  // Training
  startTraining: (config: Record<string, unknown>): Promise<TrainingJob> => 
    request(`${MLOPS_BASE}/train`, {
      method: 'POST',
      body: JSON.stringify(config),
    }),
  
  getTrainingStatus: (jobId: string): Promise<TrainingJob> => 
    request(`${MLOPS_BASE}/train/${jobId}/status`),
  
  cancelTraining: (jobId: string): Promise<{ status: string }> => 
    request(`${MLOPS_BASE}/train/${jobId}/cancel`, {
      method: 'POST',
    }),
  
  getTrainingHistory: (): Promise<TrainingJob[]> => 
    request(`${MLOPS_BASE}/train/history`),
  
  // Deployment
  getDeploymentStatus: (): Promise<DeploymentStatus> => 
    request(`${MLOPS_BASE}/deploy/status`),
  
  stageModel: (version: string): Promise<{ status: string }> => 
    request(`${MLOPS_BASE}/deploy/stage`, {
      method: 'POST',
      body: JSON.stringify({ version }),
    }),
  
  promoteModel: (version: string): Promise<{ status: string }> => 
    request(`${MLOPS_BASE}/deploy/promote`, {
      method: 'POST',
      body: JSON.stringify({ version }),
    }),
  
  rollbackModel: (targetVersion: string): Promise<{ status: string }> => 
    request(`${MLOPS_BASE}/deploy/rollback`, {
      method: 'POST',
      body: JSON.stringify({ target_version: targetVersion }),
    }),
  
  // Evaluation
  getEvaluation: (version: string): Promise<{ metrics: Record<string, number>; baseline_comparison: Record<string, number> }> => 
    request(`${MLOPS_BASE}/models/${version}/evaluation`),
  
  runEvaluation: (version: string, testSet?: string): Promise<{ job_id: string }> => 
    request(`${MLOPS_BASE}/models/${version}/evaluate`, {
      method: 'POST',
      body: JSON.stringify({ test_set: testSet }),
    }),
  
  // Metrics
  getMetrics: (): Promise<Record<string, unknown>> => 
    request(`${MLOPS_BASE}/metrics`),
  
  getModelMetrics: (version: string): Promise<Record<string, number>> => 
    request(`${MLOPS_BASE}/models/${version}/metrics`),
};

export default mlopsApi;

// ═══════════════════════════════════════════════════════════════════
// ML REGISTRY API  (Prompt-12 — governance-grade /api/v1/ml endpoints)
// ═══════════════════════════════════════════════════════════════════

export interface ModelRegistryRecord {
  version: string;
  status: 'pending' | 'training' | 'staged' | 'production' | 'archived';
  accuracy:  number | null;
  precision: number | null;
  recall:    number | null;
  f1:        number | null;
  created_at:      string;
  trained_at:      string | null;
  retrain_trigger: string | null;
  notes: string | null;
  event_id: string;
}

export interface RegistryListResponse {
  count: number;
  models: ModelRegistryRecord[];
}

export interface RetrainJobRecord {
  job_id:       string;
  status:       'pending' | 'running' | 'completed' | 'failed';
  triggered_by: string;
  started_at:   string;
  completed_at: string | null;
  error:        string | null;
  metrics:      Record<string, number | null> | null;
}

export interface RetrainJobsResponse {
  count: number;
  jobs:  RetrainJobRecord[];
}

export interface RetrainRequest {
  triggered_by: string;
  dry_run?: boolean;
}

export interface RetrainResponse {
  job_id:       string;
  status:       string;
  triggered_by: string;
  started_at:   string;
  message:      string;
  dry_run?:     boolean;
}

export interface EvalMetricsResponse {
  model_version:                string;
  sample_size:                  number;
  labelled_size:                number;
  rolling_accuracy:             number | null;
  rolling_precision:            number | null;
  rolling_recall:               number | null;
  rolling_f1:                   number | null;
  calibration_error:            number | null;
  ece:                          number | null;
  model_performance_confidence: number | null;
  explanation_confidence_mean:  number | null;
  active_alert_count:           number;
  timestamp:                    string;
  source:                       'live' | 'log' | 'empty';
}

/** Governed ML registry API — uses /api/v1/ml/* */
export const mlRegistryApi = {
  listModels: (): Promise<RegistryListResponse> =>
    request<RegistryListResponse>(`${ML_REGISTRY_BASE}/models`),

  triggerRetrain: (body: RetrainRequest = { triggered_by: 'manual' }): Promise<RetrainResponse> =>
    request<RetrainResponse>(`${ML_REGISTRY_BASE}/retrain`, {
      method: 'POST',
      body:   JSON.stringify(body),
    }),

  checkRetrain: (): Promise<RetrainResponse> =>
    request<RetrainResponse>(`${ML_REGISTRY_BASE}/retrain`, {
      method: 'POST',
      body:   JSON.stringify({ triggered_by: 'manual', dry_run: true }),
    }),

  listJobs: (limit = 20): Promise<RetrainJobsResponse> =>
    request<RetrainJobsResponse>(`${ML_REGISTRY_BASE}/retrain/jobs?limit=${limit}`),

  getEval: (): Promise<EvalMetricsResponse> =>
    request<EvalMetricsResponse>(`${ML_REGISTRY_BASE}/eval`),
};
