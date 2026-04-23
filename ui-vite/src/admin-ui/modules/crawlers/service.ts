import { apiRequest } from '../../services/apiClient';

export interface CrawlerJob {
  id: string;
  status: string;
  updatedAt: string;
}

export interface CrawlerLog {
  site: string;
  line: string;
  timestamp: string;
}

function toTimestamp(value: unknown): string {
  if (typeof value === 'string' && value.trim()) return value;
  return new Date().toISOString();
}

export function normalizeCrawlerStatus(payload: unknown): CrawlerJob[] {
  if (!payload || typeof payload !== 'object') return [];
  const entries = Object.entries(payload as Record<string, unknown>);

  return entries.map(([id, value]) => {
    const details = (value && typeof value === 'object') ? value as Record<string, unknown> : {};
    const status = typeof details.status === 'string' ? details.status : 'unknown';
    const updatedAt = toTimestamp(details.updated_at || details.updatedAt || details.last_updated);

    return {
      id,
      status,
      updatedAt,
    };
  });
}

export async function loadCrawlerJobs(): Promise<CrawlerJob[]> {
  const payload = await apiRequest('/api/v1/crawlers/status');
  return normalizeCrawlerStatus(payload);
}

export async function runCrawler(site: string): Promise<void> {
  await apiRequest(`/api/v1/crawlers/start/${site}`, { method: 'POST' });
}

export async function stopCrawler(site: string): Promise<void> {
  await apiRequest(`/api/v1/crawlers/stop/${site}`, { method: 'POST' });
}

export async function loadCrawlerLogs(site: string): Promise<CrawlerLog[]> {
  try {
    const url = site
      ? `/api/v1/crawlers/logs?site=${encodeURIComponent(site)}&lines=50`
      : '/api/v1/crawlers/logs?lines=50';
    const payload = await apiRequest(url);
    if (!Array.isArray(payload)) return [];
    return payload
      .map((item) => {
        if (!item || typeof item !== 'object') return null;
        const value = item as Record<string, unknown>;
        return {
          site: typeof value.site === 'string' ? value.site : site,
          line: typeof value.line === 'string' ? value.line : '',
          timestamp: toTimestamp(value.timestamp),
        };
      })
      .filter((item): item is CrawlerLog => Boolean(item && item.line));
  } catch {
    return [];
  }
}
