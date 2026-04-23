/**
 * AdminFeedback.tsx
 * Admin Feedback Dashboard
 * 
 * Displays:
 * - Feedback statistics (total, rate, processing, approved, training samples)
 * - Filters (status, source, date range)
 * - Paginated feedback list
 * - Export CSV
 * - Realtime refresh polling
 */

import { useState } from 'react';
import { useFeedback } from './useFeedback';
import './FeedbackAdmin.css';

interface StatCard {
  label: string;
  value: number | string;
  icon: string;
  className?: string;
}

export function AdminFeedback() {
  const {
    rows,
    stats,
    loading,
    error,
    page,
    total,
    filters,
    reload,
    setFilters,
    setPage,
    exportCsv,
  } = useFeedback();

  const [exporting, setExporting] = useState(false);

  // Stats cards
  const statCards: StatCard[] = [
    {
      label: 'Total Feedback',
      value: stats?.total_feedback ?? 0,
      icon: '📊',
      className: 'stats-card-blue',
    },
    {
      label: 'Feedback Rate',
      value: ((stats?.feedback_rate ?? 0) * 100).toFixed(1) + '%',
      icon: '📈',
      className: 'stats-card-green',
    },
    {
      label: 'Processing',
      value: stats?.processing_count ?? 0,
      icon: '⏳',
      className: 'stats-card-amber',
    },
    {
      label: 'Approved',
      value: stats?.approved_count ?? 0,
      icon: '✓',
      className: 'stats-card-green',
    },
    {
      label: 'Training Samples',
      value: stats?.used_for_training_count ?? 0,
      icon: '🎓',
      className: 'stats-card-blue',
    },
  ];

  // Source badge color
  const getSourceColor = (source: string) => {
    switch (source?.toLowerCase()) {
      case 'analyze':
        return 'source-analyze';
      case 'recommend':
        return 'source-recommend';
      case 'chat':
        return 'source-chat';
      default:
        return '';
    }
  };

  // Status badge color
  const getStatusColor = (status: string) => {
    switch (status?.toLowerCase()) {
      case 'pending':
        return 'status-amber';
      case 'approved':
        return 'status-green';
      case 'rejected':
        return 'status-red';
      case 'flagged':
        return 'status-red';
      default:
        return 'status-gray';
    }
  };

  // Handle export
  const handleExport = async () => {
    setExporting(true);
    try {
      await exportCsv();
      // Toast should be shown by useFeedback hook
    } catch (err) {
      console.error('Export failed:', err);
    } finally {
      setExporting(false);
    }
  };

  // Handle filter change (debounced in hook)
  const handleFilterChange = (key: string, value: string | boolean | number | undefined) => {
    setFilters({ ...filters, [key]: value });
    setPage(0); // Reset to first page
  };

  // Paginate
  const pageCount = Math.ceil(total / 50);

  return (
    <div className="feedback-admin-panel">
      {/* Header & Actions */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>Feedback Dashboard</h2>
        <div className="feedback-header-actions">
          <button onClick={() => reload()} disabled={loading} title="Refresh data">
            🔄 Refresh
          </button>
          <button onClick={handleExport} disabled={exporting} title="Export CSV">
            📥 Export
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="feedback-cards-grid">
        {statCards.map((card) => (
          <div
            key={card.label}
            className={`stats-card ${card.className || ''}`}
            style={{ padding: '16px', borderRadius: '8px', background: '#fff', border: '1px solid #e2e8f0' }}
          >
            <div className="feedback-metric-card">
              <span style={{ fontSize: '20px' }}>{card.icon}</span>
              <p className="feedback-card-label">{card.label}</p>
              <p className="feedback-card-value">{card.value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="filters-section">
        <div className="feedback-filter-bar" style={{ width: '100%' }}>
          <label>
            Status
            <select
              value={filters.status || ''}
              onChange={(e) => handleFilterChange('status', e.target.value)}
            >
              <option value="">All</option>
              <option value="pending">Pending</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
            </select>
          </label>

          <label>
            Source
            <select
              value={filters.source || ''}
              onChange={(e) => handleFilterChange('source', e.target.value)}
            >
              <option value="">All</option>
              <option value="analyze">Analyze</option>
              <option value="recommend">Recommend</option>
              <option value="chat">Chat</option>
            </select>
          </label>

          <label>
            From Date
            <input
              type="date"
              value={filters.from || ''}
              onChange={(e) => handleFilterChange('from', e.target.value)}
            />
          </label>

          <label>
            To Date
            <input
              type="date"
              value={filters.to || ''}
              onChange={(e) => handleFilterChange('to', e.target.value)}
            />
          </label>
        </div>
        
        {/* RETRAIN-GRADE FILTERS (2026-02-20) */}
        <div className="feedback-filter-bar feedback-filter-bar-retrain" style={{ width: '100%', marginTop: '12px' }}>
          <label>
            Career
            <input
              type="text"
              placeholder="Filter by career ID..."
              value={filters.career_id || ''}
              onChange={(e) => handleFilterChange('career_id', e.target.value)}
              style={{ width: '160px' }}
            />
          </label>

          <label>
            Model Version
            <input
              type="text"
              placeholder="e.g., simgr_v2.1"
              value={filters.model_version || ''}
              onChange={(e) => handleFilterChange('model_version', e.target.value)}
              style={{ width: '140px' }}
            />
          </label>

          <label>
            Accept/Reject
            <select
              value={filters.explicit_accept === undefined ? '' : filters.explicit_accept ? 'true' : 'false'}
              onChange={(e) => {
                const val = e.target.value;
                handleFilterChange('explicit_accept', val === '' ? undefined : val === 'true');
              }}
            >
              <option value="">All</option>
              <option value="true">Accepted (rating ≥ 4)</option>
              <option value="false">Rejected (rating ≤ 2)</option>
            </select>
          </label>

          <label>
            Min Confidence
            <input
              type="number"
              min="0"
              max="1"
              step="0.1"
              placeholder="0.0"
              value={filters.min_confidence ?? ''}
              onChange={(e) => handleFilterChange('min_confidence', e.target.value ? parseFloat(e.target.value) : undefined)}
              style={{ width: '80px' }}
            />
          </label>

          <label>
            Max Confidence
            <input
              type="number"
              min="0"
              max="1"
              step="0.1"
              placeholder="1.0"
              value={filters.max_confidence ?? ''}
              onChange={(e) => handleFilterChange('max_confidence', e.target.value ? parseFloat(e.target.value) : undefined)}
              style={{ width: '80px' }}
            />
          </label>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="feedback-error">
          <span style={{ color: 'red' }}>⚠️ {error}</span>
          <button onClick={() => reload()}>Retry</button>
        </div>
      )}

      {/* Loading State */}
      {loading && !rows.length && (
        <div style={{ padding: '24px' }}>
          <div className="feedback-skeleton-line" style={{ marginBottom: '8px' }} />
          <div className="feedback-skeleton-line" style={{ marginBottom: '8px' }} />
          <div className="feedback-skeleton-line" />
        </div>
      )}

      {/* Table */}
      {!loading && rows.length === 0 ? (
        <div className="feedback-empty">
          <p>No feedback found</p>
        </div>
      ) : (
        <div className="feedback-table-card">
          <div className="feedback-table-wrap">
            <table className="feedback-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>User</th>
                  <th>Content</th>
                  <th>Status</th>
                  <th>Source</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.feedback_id}>
                    <td>
                      <code style={{ fontSize: '12px' }}>{row.feedback_id.slice(0, 8)}</code>
                    </td>
                    <td>{row.user_id || '-'}</td>
                    <td className="feedback-content-cell">
                      <span
                        title={row.content || undefined}
                        style={{
                          display: 'block',
                          maxWidth: '260px',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                          cursor: row.content ? 'help' : 'default',
                        }}
                      >
                        {row.content || <span style={{ color: '#666', fontStyle: 'italic' }}>—</span>}
                      </span>
                    </td>
                    <td>
                      <span className={`status-badge ${getStatusColor(row.status)}`}>
                        {row.status}
                      </span>
                    </td>
                    <td>
                      <span className={`source-badge ${getSourceColor(row.source)}`}>
                        {row.source}
                      </span>
                    </td>
                    <td className="td-time" style={{ fontSize: '12px' }}>
                      {new Date(row.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="feedback-pagination">
            <button
              disabled={page === 0}
              onClick={() => setPage(page - 1)}
            >
              ← Prev
            </button>
            <span>Page {page + 1} of {pageCount} ({total} total)</span>
            <button
              disabled={page >= pageCount - 1}
              onClick={() => setPage(page + 1)}
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
