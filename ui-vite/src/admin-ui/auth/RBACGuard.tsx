import { Link } from 'react-router-dom';
import { useAdminStore } from '../store/AdminStoreProvider';
import { hasAllPermissions } from './permissions';

interface RBACGuardProps {
  required: string[];
  children: React.ReactNode;
}

export function RBACGuard({ required, children }: RBACGuardProps) {
  const { permissionState } = useAdminStore();
  const allowed = hasAllPermissions(permissionState.permissions, required);
  const missing = required.filter((permission) => {
    const alternatives = permission.split('|').map((item) => item.trim()).filter(Boolean);
    return !alternatives.some((candidate) => permissionState.permissions.includes(candidate));
  });

  if (!allowed) {
    return (
      <section className="admin-card" data-testid="rbac-denied-panel">
        <h3>Access denied</h3>
        <p>Missing required permissions for this module.</p>
        <p>
          <strong>Required:</strong> {required.join(', ') || 'none'}
        </p>
        <p>
          <strong>Missing:</strong> {missing.join(', ') || 'none'}
        </p>
        <p>
          <strong>Current:</strong> {permissionState.permissions.join(', ') || 'none'}
        </p>
        <Link to="/admin/dashboard" className="admin-nav-link">Back to dashboard</Link>
      </section>
    );
  }

  return <>{children}</>;
}
