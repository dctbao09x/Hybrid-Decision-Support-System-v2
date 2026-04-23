import { NavLink } from 'react-router-dom';
import { moduleRoutes } from '../router/moduleConfig';

interface AdminSidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  onLogout: () => void;
}

export function AdminSidebar({ collapsed, onToggle, onLogout }: AdminSidebarProps) {
  return (
    <aside className={`admin-sidebar ${collapsed ? 'collapsed' : ''}`}>
      <button type="button" className="admin-sidebar-toggle" onClick={onToggle}>
        {collapsed ? '▶' : '◀'}
      </button>

      <nav>
        {moduleRoutes.map((item) => (
          <NavLink key={item.key} to={item.path} className="admin-nav-link">
            {item.label}
          </NavLink>
        ))}
        <button type="button" className="admin-nav-link admin-logout" onClick={onLogout}>Logout</button>
      </nav>
    </aside>
  );
}
