import { describe, expect, it } from 'vitest';
import { hasAllPermissions } from '../../src/admin-ui/auth/permissions';
import { isFeatureEnabled } from '../../src/admin-ui/services/featureFlags';
import { normalizeCrawlerStatus } from '../../src/admin-ui/modules/crawlers/service';

describe('admin module recovery', () => {
  it('supports OR permissions for legacy-to-module migration', () => {
    expect(hasAllPermissions(['feedback:view'], ['crawlers:view|feedback:view'])).toBe(true);
    expect(hasAllPermissions(['crawlers:view'], ['crawlers:view|feedback:view'])).toBe(true);
    expect(hasAllPermissions(['feedback:view'], ['mlops:view|feedback:modify'])).toBe(false);
  });

  it('keeps core feature flags enabled by default', () => {
    expect(isFeatureEnabled('crawlers')).toBe(true);
    expect(isFeatureEnabled('ops')).toBe(true);
    expect(isFeatureEnabled('mlops')).toBe(true);
    expect(isFeatureEnabled('governance')).toBe(true);
    expect(isFeatureEnabled('knowledgebase')).toBe(true);
  });

  it('normalizes crawler status map into UI jobs list', () => {
    const jobs = normalizeCrawlerStatus({
      rapidapi: { status: 'running', updated_at: '2026-01-01T00:00:00Z' },
      adzuna: { status: 'stopped' },
    });

    expect(jobs).toHaveLength(2);
    expect(jobs[0]).toMatchObject({ id: 'rapidapi', status: 'running' });
    expect(jobs[1]).toMatchObject({ id: 'adzuna', status: 'stopped' });
  });
});
