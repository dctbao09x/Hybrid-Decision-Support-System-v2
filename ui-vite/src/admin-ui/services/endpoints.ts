const ADMIN_PREFIX = '/api/admin';
const API_V1_PREFIX = '/api/v1';

export const endpoints = {
  auth: {
    login: `${ADMIN_PREFIX}/login`,
    refresh: `${ADMIN_PREFIX}/refresh`,
    logout: `${ADMIN_PREFIX}/logout`,
  },
  health: {
    live: `${API_V1_PREFIX}/health/live`,
    ready: `${API_V1_PREFIX}/health/ready`,
    startup: `${API_V1_PREFIX}/health/startup`,
    full: `${API_V1_PREFIX}/health/full`,
  },
  resilience: {
    bulkheads: `${API_V1_PREFIX}/resilience/bulkheads`,
    timeouts: `${API_V1_PREFIX}/resilience/timeouts`,
  },
  system: {
    health: `${ADMIN_PREFIX}/ops/status`,
  },
  crawlers: {
    jobs: `${ADMIN_PREFIX}/crawlers/jobs`,
    schedules: `${ADMIN_PREFIX}/crawlers/schedules`,
    logs: `${ADMIN_PREFIX}/crawlers/logs`,
  },
  feedback: {
    list: `${ADMIN_PREFIX}/feedback`,
    priority: `${ADMIN_PREFIX}/feedback/priority`,
    summary: `${ADMIN_PREFIX}/feedback/summary`,
  },
  governance: {
    policies: `${ADMIN_PREFIX}/governance/policies`,
    approvals: `${ADMIN_PREFIX}/governance/approvals`,
  },
  knowledgeBase: {
    indexes: `${ADMIN_PREFIX}/kb/indexes`,
    documents: `${ADMIN_PREFIX}/kb/documents`,
  },
  mlops: {
    registry: `${ADMIN_PREFIX}/mlops/models`,
    training: `${ADMIN_PREFIX}/mlops/training`,
    drift: `${ADMIN_PREFIX}/mlops/drift`,
  },
  ops: {
    health: `${ADMIN_PREFIX}/ops/health`,
    queues: `${ADMIN_PREFIX}/ops/queues`,
    costs: `${ADMIN_PREFIX}/ops/costs`,
  },
  settings: {
    profile: `${ADMIN_PREFIX}/settings/profile`,
    preferences: `${ADMIN_PREFIX}/settings/preferences`,
  },
} as const;
