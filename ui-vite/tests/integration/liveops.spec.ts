import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiRequestMock = vi.fn();

vi.mock('../../src/admin-ui/services/apiClient', () => ({
  apiRequest: (...args: unknown[]) => apiRequestMock(...args),
}));

describe('liveops service integration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.setItem('admin_info', JSON.stringify({ adminId: 'adm-test' }));
    localStorage.setItem('admin_access_token', 'token');
    localStorage.setItem('admin_csrf_token', 'csrf');

    const subtle = {
      importKey: vi.fn(async () => ({ key: 'k' })),
      sign: vi.fn(async () => new Uint8Array([1, 2, 3, 4]).buffer),
    } as unknown as SubtleCrypto;

    Object.defineProperty(globalThis, 'crypto', {
      value: { subtle },
      configurable: true,
    });
  });

  it('calls widget endpoint for health', async () => {
    apiRequestMock.mockResolvedValueOnce({ status: 'healthy', overallStatus: 'healthy', services: [], uptime: 0, lastUpdate: 'now' });
    const service = await import('../../src/admin-ui/modules/liveops/service');

    await service.getSystemHealth();

    expect(apiRequestMock).toHaveBeenCalledWith('/api/v1/live/widget/health');
  });

  it('submits signed kill crawler command', async () => {
    apiRequestMock.mockResolvedValueOnce({
      status: 'ok',
      data: { command_id: 'cmd-1', state: 'queued' },
      meta: {},
    });

    const service = await import('../../src/admin-ui/modules/liveops/service');
    const response = await service.killCrawler('site-a');

    expect(apiRequestMock).toHaveBeenCalledTimes(1);
    const [path, req] = apiRequestMock.mock.calls[0];
    expect(path).toBe('/api/v1/live/crawler/kill');
    expect(req.method).toBe('POST');
    expect(req.body.nonce).toBeTruthy();
    expect(req.body.timestamp).toBeTypeOf('number');
    expect(req.body.signature).toBeTruthy();
    expect(response.data.commandId).toBe('cmd-1');
  });
});
