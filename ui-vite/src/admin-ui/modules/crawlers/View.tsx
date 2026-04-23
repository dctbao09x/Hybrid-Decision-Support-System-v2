import { ModuleWorkspace } from '../../shared/ModuleWorkspace';
import type { CrawlerJob, CrawlerLog } from './service';

interface CrawlersViewProps {
  jobs: CrawlerJob[];
  logs: CrawlerLog[];
  selectedSite: string;
  isLoading: boolean;
  error: string;
  isScheduleOpen: boolean;
  onRefresh: () => void;
  onSelectSite: (site: string) => void;
  onRun: () => void;
  onStop: () => void;
  onScheduleOpen: (open: boolean) => void;
  onDismissError: () => void;
}

function freshnessLabel(updatedAt: string) {
  const ageMs = Date.now() - new Date(updatedAt).getTime();
  const ageMinutes = Math.floor(ageMs / 60000);
  if (Number.isNaN(ageMinutes) || ageMinutes < 0) return 'unknown';
  if (ageMinutes <= 15) return 'fresh';
  if (ageMinutes <= 60) return 'aging';
  return 'stale';
}

export function CrawlersView({
  jobs,
  logs,
  selectedSite,
  isLoading,
  error,
  isScheduleOpen,
  onRefresh,
  onSelectSite,
  onRun,
  onStop,
  onScheduleOpen,
  onDismissError,
}: CrawlersViewProps) {
  const selectedJob = jobs.find((item) => item.id === selectedSite);

  return (
    <ModuleWorkspace title="Crawlers Panel" subtitle="Live job status, run/stop control, logs and freshness checks">
      <div className="admin-grid-cards">
        <article className="admin-card" data-testid="crawler-jobs-card">
          <h3>Job List</h3>
          <button type="button" className="admin-nav-link" onClick={onRefresh} disabled={isLoading}>Refresh</button>
          {jobs.length === 0 && <p>No crawler jobs detected.</p>}
          {jobs.map((job) => (
            <div key={job.id} style={{ marginTop: 8 }}>
              <label>
                <input
                  type="radio"
                  name="crawler-site"
                  value={job.id}
                  checked={selectedSite === job.id}
                  onChange={() => onSelectSite(job.id)}
                />{' '}
                {job.id} — {job.status}
              </label>
              <div>Freshness: {freshnessLabel(job.updatedAt)}</div>
              {job.status.toLowerCase().includes('error') && (
                <div role="alert">Failure detected for {job.id}</div>
              )}
            </div>
          ))}
        </article>

        <article className="admin-card" data-testid="crawler-actions-card">
          <h3>Run / Stop</h3>
          <p>Selected job: {selectedSite || 'none'}</p>
          <button type="button" className="admin-nav-link" onClick={onRun} disabled={!selectedSite}>Run</button>{' '}
          <button type="button" className="admin-nav-link" onClick={onStop} disabled={!selectedSite}>Stop</button>{' '}
          <button type="button" className="admin-nav-link" onClick={() => onScheduleOpen(true)} disabled={!selectedSite}>Schedule</button>
        </article>

        <article className="admin-card" data-testid="crawler-logs-card">
          <h3>Live Logs Viewer</h3>
          <p>{selectedJob ? `Streaming logs for ${selectedJob.id}` : 'Select a crawler to view logs.'}</p>
          <div style={{ maxHeight: 180, overflowY: 'auto' }}>
            {logs.length === 0 ? (
              <p>No logs available.</p>
            ) : (
              logs.slice(-25).map((item, idx) => (
                <div key={`${item.timestamp}-${idx}`}>[{new Date(item.timestamp).toLocaleTimeString()}] {item.line}</div>
              ))
            )}
          </div>
        </article>
      </div>

      {error && (
        <div className="admin-context-help" role="alert" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>{error}</span>
          <button type="button" className="admin-nav-link" style={{ marginLeft: 12 }} onClick={onDismissError}>✕</button>
        </div>
      )}

      {isScheduleOpen && (
        <div className="admin-context-help" data-testid="crawler-schedule-modal">
          <h3>Schedule Crawler</h3>
          <p>Scheduled crawling is not yet available. Use <strong>Run</strong> and <strong>Stop</strong> for manual control.</p>
          <button type="button" className="admin-nav-link" onClick={() => onScheduleOpen(false)}>Close</button>
        </div>
      )}
    </ModuleWorkspace>
  );
}
