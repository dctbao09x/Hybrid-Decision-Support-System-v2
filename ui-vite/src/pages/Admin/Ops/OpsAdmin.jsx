// src/pages/Admin/Ops/OpsAdmin.jsx
/**
 * Ops Admin Dashboard
 * ===================
 * 
 * Operations monitoring dashboard:
 * - System Health
 * - Latency metrics
 * - SLA status
 * - Kill-switch control
 */

import { useState, useEffect, useCallback } from 'react';
import { opsApi } from '../../../services/opsApi';
import './OpsAdmin.css';

const LABELS = {
  title: 'Ops Dashboard',
  subtitle: 'System health and latency monitoring',
  health: 'System Health',
  latency: 'Latency',
  sla: 'SLA Status',
  killSwitch: 'Kill Switch',
  alerts: 'Active Alerts',
  refresh: 'Refresh',
  activate: 'Activate',
  deactivate: 'Deactivate',
};

function HealthCard({ name, status, details }) {
  const statusClass = {
    healthy: 'health-good',
    degraded: 'health-warning',
    down: 'health-critical',
  }[status] || 'health-unknown';

  return (
    <div className={`ops-health-card ${statusClass}`}>
      <div className="health-card-header">
        <span className="health-card-name">{name}</span>
        <span className={`health-card-status ${statusClass}`}>
          {status?.toUpperCase() || 'UNKNOWN'}
        </span>
      </div>
      {details && (
        <div className="health-card-details">
          {Object.entries(details).map(([key, value]) => (
            <div key={key} className="health-detail">
              <span className="health-detail-key">{key}</span>
              <span className="health-detail-value">{String(value)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MetricCard({ label, value, unit, trend }) {
  const trendClass = trend > 0 ? 'trend-up' : trend < 0 ? 'trend-down' : '';
  
  return (
    <div className="ops-metric-card">
      <div className="metric-label">{label}</div>
      <div className="metric-value">
        {value}
        {unit && <span className="metric-unit">{unit}</span>}
      </div>
      {trend !== undefined && (
        <div className={`metric-trend ${trendClass}`}>
          {trend > 0 ? '↑' : trend < 0 ? '↓' : '→'} {Math.abs(trend)}%
        </div>
      )}
    </div>
  );
}

function AlertRow({ alert }) {
  const severityClass = {
    critical: 'alert-critical',
    warning: 'alert-warning',
    info: 'alert-info',
  }[alert.severity] || 'alert-info';

  return (
    <div className={`ops-alert-row ${severityClass}`}>
      <span className="alert-severity">{alert.severity?.toUpperCase()}</span>
      <span className="alert-message">{alert.message}</span>
      <span className="alert-time">
        {new Date(alert.timestamp).toLocaleTimeString('vi-VN')}
      </span>
    </div>
  );
}

export default function OpsAdmin() {
  const [dashboard, setDashboard] = useState(null);
  const [health, setHealth] = useState([]);
  const [latency, setLatency] = useState(null);
  const [sla, setSla] = useState(null);
  const [killSwitch, setKillSwitch] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [killSwitchLoading, setKillSwitchLoading] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [dashboardData, healthData, latencyData, slaData, killSwitchData, alertsData] = 
        await Promise.allSettled([
          opsApi.getDashboard(),
          opsApi.getHealth(),
          opsApi.getLatency(),
          opsApi.getSLA(),
          opsApi.getKillSwitch(),
          opsApi.getAlerts({ limit: 10 }),
        ]);

      if (dashboardData.status === 'fulfilled') setDashboard(dashboardData.value);
      if (healthData.status === 'fulfilled') {
        const h = healthData.value;
        setHealth(h.services || h.components || []);
      }
      if (latencyData.status === 'fulfilled') setLatency(latencyData.value);
      if (slaData.status === 'fulfilled') setSla(slaData.value);
      if (killSwitchData.status === 'fulfilled') setKillSwitch(killSwitchData.value);
      if (alertsData.status === 'fulfilled') setAlerts(alertsData.value.items || []);

      // Check for any failures
      const failures = [dashboardData, healthData, latencyData, slaData, killSwitchData, alertsData]
        .filter(r => r.status === 'rejected');
      if (failures.length > 0 && failures.length === 6) {
        setError('Failed to connect to ops API');
        // Set demo data for display
        setHealth([
          { name: 'API Server', status: 'healthy', details: { uptime: '99.9%', version: '1.0.0' } },
          { name: 'Database', status: 'healthy', details: { connections: 10 } },
          { name: 'LLM Service', status: 'degraded', details: { latency: '2.1s' } },
        ]);
        setLatency({ p50: 120, p90: 350, p99: 890 });
        setSla({ compliance: 0.985, target: 0.99, violations: 2 });
        setKillSwitch({ active: false, lastActivated: null });
      }
    } catch (err) {
      setError(err.message || 'Failed to load ops data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleKillSwitch = async (activate) => {
    setKillSwitchLoading(true);
    try {
      if (activate) {
        await opsApi.activateKillSwitch('Admin UI trigger');
      } else {
        await opsApi.deactivateKillSwitch();
      }
      await fetchData();
    } catch (err) {
      setError(`Kill switch action failed: ${err.message}`);
    } finally {
      setKillSwitchLoading(false);
    }
  };

  return (
    <div className="ops-admin">
      <header className="ops-header">
        <div className="ops-header-info">
          <h1>{LABELS.title}</h1>
          <p>{LABELS.subtitle}</p>
        </div>
        <button 
          className="ops-refresh-btn" 
          onClick={fetchData}
          disabled={loading}
        >
          {LABELS.refresh}
        </button>
      </header>

      {error && (
        <div className="ops-error">
          {error}
        </div>
      )}

      <div className="ops-grid">
        {/* Health Section */}
        <section className="ops-section">
          <h2>{LABELS.health}</h2>
          <div className="ops-health-grid">
            {health.map((service, idx) => (
              <HealthCard key={idx} {...service} />
            ))}
          </div>
        </section>

        {/* Latency Section */}
        <section className="ops-section">
          <h2>{LABELS.latency}</h2>
          <div className="ops-metrics-grid">
            <MetricCard label="P50" value={latency?.p50 || '-'} unit="ms" />
            <MetricCard label="P90" value={latency?.p90 || '-'} unit="ms" />
            <MetricCard label="P99" value={latency?.p99 || '-'} unit="ms" />
          </div>
        </section>

        {/* SLA Section */}
        <section className="ops-section">
          <h2>{LABELS.sla}</h2>
          <div className="ops-sla-card">
            <div className="sla-main">
              <span className="sla-label">Compliance</span>
              <span className="sla-value">
                {sla ? `${(sla.compliance * 100).toFixed(2)}%` : '-'}
              </span>
            </div>
            <div className="sla-details">
              <div className="sla-detail">
                <span>Target</span>
                <strong>{sla ? `${(sla.target * 100).toFixed(1)}%` : '-'}</strong>
              </div>
              <div className="sla-detail">
                <span>Violations</span>
                <strong className="violations">{sla?.violations || 0}</strong>
              </div>
            </div>
          </div>
        </section>

        {/* Kill Switch Section */}
        <section className="ops-section ops-kill-switch">
          <h2>{LABELS.killSwitch}</h2>
          <div className={`kill-switch-card ${killSwitch?.active ? 'active' : 'inactive'}`}>
            <div className="kill-switch-status">
              <span className="kill-switch-label">Status</span>
              <span className={`kill-switch-value ${killSwitch?.active ? 'danger' : 'safe'}`}>
                {killSwitch?.active ? 'ACTIVE' : 'INACTIVE'}
              </span>
            </div>
            <div className="kill-switch-actions">
              {killSwitch?.active ? (
                <button
                  className="kill-switch-btn deactivate"
                  onClick={() => handleKillSwitch(false)}
                  disabled={killSwitchLoading}
                >
                  {killSwitchLoading ? '...' : LABELS.deactivate}
                </button>
              ) : (
                <button
                  className="kill-switch-btn activate"
                  onClick={() => handleKillSwitch(true)}
                  disabled={killSwitchLoading}
                >
                  {killSwitchLoading ? '...' : LABELS.activate}
                </button>
              )}
            </div>
          </div>
        </section>

        {/* Alerts Section */}
        <section className="ops-section ops-alerts-section">
          <h2>{LABELS.alerts}</h2>
          <div className="ops-alerts-list">
            {alerts.length > 0 ? (
              alerts.map((alert, idx) => (
                <AlertRow key={idx} alert={alert} />
              ))
            ) : (
              <div className="ops-alerts-empty">No active alerts</div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
