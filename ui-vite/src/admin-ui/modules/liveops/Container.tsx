/**
 * LiveOps Container
 * =================
 * 
 * Main container component for the Live Operations module.
 * Mounts LiveDashboard and CommandControlPanel within the ModuleWorkspace layout.
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ModuleWorkspace } from '../../shared/ModuleWorkspace';
import { LiveDashboard } from './widgets';
import { CommandControlPanel } from './CommandControlPanel';

type TabKey = 'dashboard' | 'commands';

export function LiveOpsContainer() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<TabKey>('dashboard');

  const handleNavigate = (path: string) => {
    navigate(path);
  };

  return (
    <ModuleWorkspace 
      title="Live Operations" 
      subtitle="Real-time monitoring and command control panel"
    >
      {/* Tab Navigation */}
      <div className="admin-tabs mb-6">
        <button
          type="button"
          className={`admin-tab ${activeTab === 'dashboard' ? 'active' : ''}`}
          onClick={() => setActiveTab('dashboard')}
        >
          Dashboard
        </button>
        <button
          type="button"
          className={`admin-tab ${activeTab === 'commands' ? 'active' : ''}`}
          onClick={() => setActiveTab('commands')}
        >
          Command Control
        </button>
      </div>

      {/* Tab Content */}
      <div className="admin-tab-content">
        {activeTab === 'dashboard' && (
          <LiveDashboard onNavigate={handleNavigate} />
        )}
        {activeTab === 'commands' && (
          <CommandControlPanel />
        )}
      </div>
    </ModuleWorkspace>
  );
}

export default LiveOpsContainer;
