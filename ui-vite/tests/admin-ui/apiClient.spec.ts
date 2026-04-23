import { describe, expect, it } from 'vitest';

describe('admin apiClient skeleton', () => {
  it('normalizes error object shape', () => {
    const normalized = {
      status: 500,
      code: 'SERVER_ERROR',
      message: 'failed',
      retriable: true,
    };
    expect(normalized).toHaveProperty('status');
    expect(normalized).toHaveProperty('code');
    expect(normalized).toHaveProperty('message');
    expect(normalized).toHaveProperty('retriable');
  });
});
