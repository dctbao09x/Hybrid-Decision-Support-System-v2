import { Navigate, Route, Routes } from 'react-router-dom';
import { RBACGuard } from '../auth/RBACGuard';
import { CrawlersContainer } from '../modules/crawlers/Container';
import { DashboardWorkspace } from '../dashboard/DashboardWorkspace';
import { FeedbackWorkspace } from '../modules/feedback/FeedbackWorkspace';
import { GovernanceContainer } from '../modules/governance/Container';
import { KnowledgeBaseContainer } from '../modules/knowledgebase/Container';
import { LiveOpsContainer } from '../modules/liveops/Container';
import { MLOpsContainer } from '../modules/mlops/Container';
import { OpsContainer } from '../modules/ops/Container';
import { SettingsWorkspace } from '../modules/settings/SettingsWorkspace';

export function ModuleRouter() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/admin/dashboard" replace />} />
      <Route path="/dashboard" element={<DashboardWorkspace />} />
      <Route
        path="/crawlers"
        element={<RBACGuard required={['crawlers:view|feedback:view']}><CrawlersContainer /></RBACGuard>}
      />
      <Route
        path="/feedback"
        element={<RBACGuard required={['feedback:view']}><FeedbackWorkspace /></RBACGuard>}
      />
      <Route
        path="/governance"
        element={<RBACGuard required={['governance:view|feedback:modify']}><GovernanceContainer /></RBACGuard>}
      />
      <Route
        path="/kb"
        element={<RBACGuard required={['kb:view|feedback:view']}><KnowledgeBaseContainer /></RBACGuard>}
      />
      <Route
        path="/liveops"
        element={<RBACGuard required={['ops:view|feedback:view']}><LiveOpsContainer /></RBACGuard>}
      />
      <Route
        path="/mlops"
        element={<RBACGuard required={['mlops:view|feedback:modify']}><MLOpsContainer /></RBACGuard>}
      />
      <Route
        path="/ops"
        element={<RBACGuard required={['ops:view|feedback:view']}><OpsContainer /></RBACGuard>}
      />
      <Route path="/settings" element={<SettingsWorkspace />} />
      <Route path="*" element={<Navigate to="/admin/dashboard" replace />} />
    </Routes>
  );
}
