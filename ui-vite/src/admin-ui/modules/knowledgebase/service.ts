import { apiRequest } from '../../services/apiClient';

export interface KBHealth {
  status: string;
  timestamp: string;
}

export async function loadKBHealth(): Promise<KBHealth> {
  try {
    // Use domains?limit=1 as a lightweight probe — avoids fetching the full
    // education-levels payload and prevents deduplication-cancel false alarms.
    await apiRequest<Record<string, unknown>>('/api/v1/kb/domains?limit=1', { timeoutMs: 3000 });
    return {
      status: 'ok',
      timestamp: new Date().toISOString(),
    };
  } catch {
    return {
      status: 'unknown',
      timestamp: new Date().toISOString(),
    };
  }
}
