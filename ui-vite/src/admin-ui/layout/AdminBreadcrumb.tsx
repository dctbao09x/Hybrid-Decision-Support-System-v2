import { useLocation } from 'react-router-dom';

export function AdminBreadcrumb() {
  const location = useLocation();
  const segments = location.pathname.split('/').filter(Boolean);

  return (
    <div className="admin-breadcrumb">
      {segments.map((segment, index) => (
        <span key={`${segment}-${index}`}>
          {index > 0 ? ' / ' : ''}
          {segment}
        </span>
      ))}
    </div>
  );
}
