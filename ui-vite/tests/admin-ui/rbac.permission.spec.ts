import { describe, expect, it } from 'vitest';
import { hasAllPermissions } from '../../src/admin-ui/auth/permissions';

describe('RBAC permission matrix', () => {
  it('allows user with all required permissions', () => {
    expect(hasAllPermissions(['feedback:view', 'feedback:modify'], ['feedback:view'])).toBe(true);
  });

  it('denies user when one permission is missing', () => {
    expect(hasAllPermissions(['feedback:view'], ['feedback:view', 'feedback:modify'])).toBe(false);
  });
});
