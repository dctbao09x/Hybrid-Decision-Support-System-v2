// src/pages/Admin/Crawlers/CrawlersAdmin.jsx
/**
 * Crawlers Admin Panel
 * ====================
 * 
 * Manage crawler instances:
 * - List crawlers
 * - Start/Stop
 * - View status
 * - View metrics
 */

import { useState, useEffect, useCallback } from 'react';
import { crawlerApi } from '../../../services/crawlerApi';
import './CrawlersAdmin.css';

const LABELS = {
  title: 'Crawler Management',
  subtitle: 'Monitor and control data crawlers',
  status: 'Status',
  actions: 'Actions',
  start: 'Start',
  stop: 'Stop',
  running: 'Running',
  stopped: 'Stopped',
  error: 'Error',
  lastRun: 'Last Run',
  itemsCrawled: 'Items Crawled',
  refresh: 'Refresh',
};

function StatusBadge({ status }) {
  const statusClass = {
    running: 'status-running',
    stopped: 'status-stopped',
    error: 'status-error',
    pending: 'status-pending',
  }[status] || 'status-unknown';

  return (
    <span className={`crawler-status-badge ${statusClass}`}>
      {status?.toUpperCase() || 'UNKNOWN'}
    </span>
  );
}

export default function CrawlersAdmin() {
  const [crawlers, setCrawlers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionLoading, setActionLoading] = useState({});

  const fetchCrawlers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await crawlerApi.listCrawlers();
      setCrawlers(data.items || data.crawlers || []);
    } catch (err) {
      setError(err.message || 'Failed to load crawlers');
      // Fallback to demo data if API not available
      setCrawlers([
        { id: 'rapidapi', name: 'RapidAPI Jobs', status: 'stopped', lastRun: null, itemsCrawled: 0 },
        { id: 'adzuna', name: 'Adzuna Jobs', status: 'stopped', lastRun: null, itemsCrawled: 0 },
        { id: 'custom', name: 'Custom Crawler', status: 'stopped', lastRun: null, itemsCrawled: 0 },
      ]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCrawlers();
    const interval = setInterval(fetchCrawlers, 30000);
    return () => clearInterval(interval);
  }, [fetchCrawlers]);

  const handleStart = async (crawlerId) => {
    setActionLoading(prev => ({ ...prev, [crawlerId]: true }));
    try {
      await crawlerApi.startCrawler(crawlerId);
      await fetchCrawlers();
    } catch (err) {
      setError(`Failed to start ${crawlerId}: ${err.message}`);
    } finally {
      setActionLoading(prev => ({ ...prev, [crawlerId]: false }));
    }
  };

  const handleStop = async (crawlerId) => {
    setActionLoading(prev => ({ ...prev, [crawlerId]: true }));
    try {
      await crawlerApi.stopCrawler(crawlerId);
      await fetchCrawlers();
    } catch (err) {
      setError(`Failed to stop ${crawlerId}: ${err.message}`);
    } finally {
      setActionLoading(prev => ({ ...prev, [crawlerId]: false }));
    }
  };

  const formatDateTime = (dateStr) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString('vi-VN');
  };

  return (
    <div className="crawlers-admin">
      <header className="crawlers-header">
        <div className="crawlers-header-info">
          <h1>{LABELS.title}</h1>
          <p>{LABELS.subtitle}</p>
        </div>
        <button 
          className="crawlers-refresh-btn" 
          onClick={fetchCrawlers}
          disabled={loading}
        >
          {LABELS.refresh}
        </button>
      </header>

      {error && (
        <div className="crawlers-error">
          {error}
        </div>
      )}

      {loading && crawlers.length === 0 ? (
        <div className="crawlers-loading">Loading crawlers...</div>
      ) : (
        <div className="crawlers-table-container">
          <table className="crawlers-table">
            <thead>
              <tr>
                <th>Crawler</th>
                <th>{LABELS.status}</th>
                <th>{LABELS.lastRun}</th>
                <th>{LABELS.itemsCrawled}</th>
                <th>{LABELS.actions}</th>
              </tr>
            </thead>
            <tbody>
              {crawlers.map(crawler => (
                <tr key={crawler.id}>
                  <td>
                    <div className="crawler-name">
                      <strong>{crawler.name || crawler.id}</strong>
                      <span className="crawler-id">{crawler.id}</span>
                    </div>
                  </td>
                  <td>
                    <StatusBadge status={crawler.status} />
                  </td>
                  <td>{formatDateTime(crawler.lastRun || crawler.last_run)}</td>
                  <td>{crawler.itemsCrawled || crawler.items_crawled || 0}</td>
                  <td>
                    <div className="crawler-actions">
                      {crawler.status === 'running' ? (
                        <button
                          className="crawler-btn crawler-btn-stop"
                          onClick={() => handleStop(crawler.id)}
                          disabled={actionLoading[crawler.id]}
                        >
                          {actionLoading[crawler.id] ? '...' : LABELS.stop}
                        </button>
                      ) : (
                        <button
                          className="crawler-btn crawler-btn-start"
                          onClick={() => handleStart(crawler.id)}
                          disabled={actionLoading[crawler.id]}
                        >
                          {actionLoading[crawler.id] ? '...' : LABELS.start}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {crawlers.length === 0 && !loading && (
        <div className="crawlers-empty">
          No crawlers configured
        </div>
      )}
    </div>
  );
}
