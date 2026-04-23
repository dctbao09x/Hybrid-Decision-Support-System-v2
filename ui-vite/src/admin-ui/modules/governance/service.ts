import { apiRequest } from '../../services/apiClient';

export interface GovernanceHealth {
  status: string;
  timestamp: string;
}

export async function loadGovernanceDashboard(): Promise<Record<string, unknown>> {
  return apiRequest<Record<string, unknown>>('/api/v1/governance/dashboard');
}
