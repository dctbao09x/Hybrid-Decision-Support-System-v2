import { apiRequest } from '../../services/apiClient';

export interface MLOpsHealth {
  status: string;
  timestamp: string;
}

export async function loadMLOpsHealth(): Promise<MLOpsHealth> {
  try {
    return await apiRequest<MLOpsHealth>('/api/v1/mlops/health', { timeoutMs: 3000 });
  } catch {
    return {
      status: 'unknown',
      timestamp: new Date().toISOString(),
    };
  }
}
