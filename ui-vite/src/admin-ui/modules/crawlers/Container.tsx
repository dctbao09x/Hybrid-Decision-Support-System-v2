import { isFeatureEnabled } from '../../services/featureFlags';
import { CrawlersView } from './View';
import { useCrawlersModule } from './hooks';

export function CrawlersContainer() {
  const enabled = isFeatureEnabled('crawlers');
  const {
    state,
    selectedLogs,
    refreshJobs,
    runSelectedCrawler,
    stopSelectedCrawler,
    setSelectedSite,
    setScheduleOpen,
    dismissError,
  } = useCrawlersModule();

  if (!enabled) {
    return (
      <section className="admin-module-workspace">
        <header className="admin-module-header">
          <h1>Crawlers</h1>
          <p>Manage crawler jobs, schedule and freshness</p>
        </header>
        <div className="admin-module-body">
          <div className="admin-card" style={{ borderColor: 'rgba(239,68,68,0.25)' }}>
            <h3 style={{ color: '#fca5a5' }}>Crawlers Unavailable</h3>
            <p>The crawlers route is not registered on the backend. Check the server startup logs.</p>
          </div>
        </div>
      </section>
    );
  }

  return (
    <CrawlersView
      jobs={state.jobs}
      logs={selectedLogs}
      selectedSite={state.selectedSite}
      isLoading={state.isLoading}
      error={state.error}
      isScheduleOpen={state.isScheduleOpen}
      onRefresh={() => void refreshJobs()}
      onSelectSite={setSelectedSite}
      onRun={() => void runSelectedCrawler()}
      onStop={() => void stopSelectedCrawler()}
      onScheduleOpen={setScheduleOpen}
      onDismissError={dismissError}
    />
  );
}
