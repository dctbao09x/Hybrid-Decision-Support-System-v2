import { ContextHelp } from '../../shared/ContextHelp';
import { ModuleWorkspace } from '../../shared/ModuleWorkspace';

export function CrawlersWorkspace() {
  return (
    <ModuleWorkspace title="Crawlers Panel" subtitle="Manage crawler jobs, schedule and freshness">
      <div className="admin-grid-cards">
        <article className="admin-card"><h3>Job List</h3><p>Active and queued crawler jobs.</p></article>
        <article className="admin-card"><h3>Schedule</h3><p>Cron-based crawl schedules.</p></article>
        <article className="admin-card"><h3>Run / Stop</h3><p>Control crawler execution state.</p></article>
        <article className="admin-card"><h3>Logs</h3><p>Centralized crawler execution logs.</p></article>
        <article className="admin-card"><h3>Failure Alert</h3><p>Escalation for failed jobs.</p></article>
        <article className="admin-card"><h3>Data Freshness</h3><p>Freshness SLA and aging indicators.</p></article>
      </div>
      <ContextHelp title="Crawler Shortcuts" content="Use Alt+R to run selected job, Alt+S to stop." />
    </ModuleWorkspace>
  );
}
