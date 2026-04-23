import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { ModuleRouteDef } from '../types';

interface GlobalSearchProps {
  open: boolean;
  onClose: () => void;
  routes: ModuleRouteDef[];
}

export function GlobalSearch({ open, onClose, routes }: GlobalSearchProps) {
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState('');

  const filtered = useMemo(
    () => routes.filter((item) => item.label.toLowerCase().includes(keyword.toLowerCase())),
    [keyword, routes],
  );

  if (!open) return null;

  return (
    <div className="admin-search-overlay" role="dialog" aria-modal="true">
      <div className="admin-search-modal">
        <input
          autoFocus
          placeholder="Search module..."
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
        />
        <div className="admin-search-results">
          {filtered.map((item) => (
            <button
              type="button"
              key={item.key}
              onClick={() => {
                navigate(item.path);
                onClose();
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
        <button type="button" onClick={onClose}>Close</button>
      </div>
    </div>
  );
}
