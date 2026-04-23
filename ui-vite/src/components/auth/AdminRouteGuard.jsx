import { Navigate, useLocation } from 'react-router-dom';
import { isAdminAuthenticated } from '../../utils/adminSession';

export default function AdminRouteGuard({ children }) {
  const location = useLocation();

  if (!isAdminAuthenticated()) {
    return <Navigate to="/admin/login" replace state={{ from: location.pathname }} />;
  }

  return children;
}
