import { apiRequest } from './apiClient';
import { endpoints } from './endpoints';
import type { SystemHealth } from '../types';

export async function getSystemHealth(): Promise<SystemHealth> {
  try {
    return await apiRequest<SystemHealth>(endpoints.system.health, { timeoutMs: 3000 });
  } catch {
    return {
      status: 'unknown',
      updatedAt: new Date().toISOString(),
      services: [],
    };
  }
}

export function getCrawlerJobs() {
  return apiRequest(endpoints.crawlers.jobs, { timeoutMs: 5000 });
}

export function getFeedbackInbox() {
  return apiRequest(endpoints.feedback.list, { timeoutMs: 5000 });
}

export function getGovernancePolicies() {
  return apiRequest(endpoints.governance.policies, { timeoutMs: 5000 });
}

export function getKnowledgeBaseIndexes() {
  return apiRequest(endpoints.knowledgeBase.indexes, { timeoutMs: 5000 });
}

export function getMLOpsRegistry() {
  return apiRequest(endpoints.mlops.registry, { timeoutMs: 5000 });
}

export function getOpsHealth() {
  return apiRequest(endpoints.ops.health, { timeoutMs: 5000 });
}
