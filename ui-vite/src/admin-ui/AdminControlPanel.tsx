import { ProtectedRoute } from './auth/ProtectedRoute';
import { AdminShell } from './layout/AdminShell';
import { AdminStoreProvider } from './store/AdminStoreProvider';
import './styles/admin-ui.css';

export default function AdminControlPanel() {
  return (
    <ProtectedRoute>
      <AdminStoreProvider>
        <AdminShell />
      </AdminStoreProvider>
    </ProtectedRoute>
  );
}
