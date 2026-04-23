import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../src/utils/adminSession', () => ({
  getAdminSession: () => ({
    accessToken: 'token',
    refreshToken: 'refresh',
    csrfToken: 'csrf',
    admin: { adminId: 'admin' },
  }),
  clearAdminSession: vi.fn(),
  saveAdminSession: vi.fn(),
}));

describe('admin apiClient reliability', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
  });

  it('returns timeout-shaped error when request exceeds deadline', async () => {
    global.fetch = vi.fn(async () => {
      throw Object.assign(new Error('timeout'), { status: 504, code: 'SERVER_ERROR', retriable: false });
    }) as unknown as typeof fetch;

    const { apiRequest } = await import('../../src/admin-ui/services/apiClient');
    await expect(apiRequest('/api/admin/feedback')).rejects.toMatchObject({ status: 504 });
  }, 15000);

  it('deduplicates same pending key by aborting older request', async () => {
    const signals: AbortSignal[] = [];

    global.fetch = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      signals.push(init?.signal as AbortSignal);
      return new Promise<Response>((resolve) => {
        const onAbort = () => {
          resolve(
            new Response(JSON.stringify({ detail: 'aborted' }), {
              status: 499,
              headers: { 'content-type': 'application/json' },
            }),
          );
        };

        init?.signal?.addEventListener('abort', onAbort, { once: true });

        window.setTimeout(() => {
          init?.signal?.removeEventListener('abort', onAbort);
          resolve(
            new Response(JSON.stringify({ ok: true }), {
              status: 200,
              headers: { 'content-type': 'application/json' },
            }),
          );
        }, 10);
      });
    }) as unknown as typeof fetch;

    const { apiRequest } = await import('../../src/admin-ui/services/apiClient');

    const first = apiRequest('/api/admin/feedback');
    const second = apiRequest('/api/admin/feedback');

    await Promise.allSettled([first, second]);

    expect(signals.length).toBeGreaterThanOrEqual(2);
    expect(signals[0]?.aborted).toBe(true);
  }, 15000);

  it('caps retries at 2', async () => {
    global.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ detail: 'server error' }), {
        status: 500,
        headers: { 'content-type': 'application/json' },
      })) as unknown as typeof fetch;

    const { apiRequest } = await import('../../src/admin-ui/services/apiClient');

    await expect(apiRequest('/api/admin/feedback')).rejects.toMatchObject({ status: 500 });
    expect(global.fetch).toHaveBeenCalledTimes(3);
  }, 15000);

  it('opens circuit breaker after repeated failures', async () => {
    global.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ detail: 'server error' }), {
        status: 500,
        headers: { 'content-type': 'application/json' },
      })) as unknown as typeof fetch;

    const { apiRequest } = await import('../../src/admin-ui/services/apiClient');

    for (let index = 0; index < 3; index += 1) {
      await expect(apiRequest(`/api/admin/feedback?page=${index}`)).rejects.toMatchObject({ status: expect.any(Number) });
    }

    await expect(apiRequest('/api/admin/feedback')).rejects.toMatchObject({ status: 503 });
  }, 15000);
});
