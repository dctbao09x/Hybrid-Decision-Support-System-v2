import { useEffect, useMemo, useState } from 'react';
import { mlopsApi } from '../../../services/mlopsApi';
import { refreshAdminToken } from '../../../services/adminAuthApi';
import ModelRegistryPanel from './ModelRegistryPanel';
import './MLOpsAdmin.css';

export default function MLOpsAdmin() {
  const [models, setModels] = useState([]);
  const [runs, setRuns] = useState([]);
  const [monitor, setMonitor] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [strategy, setStrategy] = useState('canary');

  const refresh = async () => {
    setLoading(true);
    setError('');
    try {
      const [m, r, mon] = await Promise.all([mlopsApi.models(), mlopsApi.runs(), mlopsApi.monitor()]);
      setModels(m.items || []);
      setRuns(r.items || []);
      setMonitor(mon);
      if (!selectedModel && (m.items || []).length) {
        setSelectedModel(m.items[0].model_id);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to load';
      // Attempt token refresh on 401
      if (msg.includes('401') || msg.toLowerCase().includes('unauthorized')) {
        try {
          await refreshAdminToken();
          return refresh();
        } catch {
          setError('Session expired — please log in again.');
          return;
        }
      }
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => clearInterval(timer);
  }, []);

  const prodModel = useMemo(() => models.find((m) => m.status === 'prod'), [models]);

  const runAction = async (action) => {
    setLoading(true);
    setError('');
    try {
      if (action === 'train') {
        await mlopsApi.train({ trigger: 'admin_ui', source: 'feedback' });
      } else if (action === 'validate') {
        await mlopsApi.validate({ model_id: selectedModel });
      } else if (action === 'deploy') {
        await mlopsApi.deploy({ model_id: selectedModel, strategy, canary_ratio: 0.1 });
      } else if (action === 'rollback') {
        await mlopsApi.rollback({ reason: 'admin_ui' });
      }
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Action failed';
      if (msg.includes('401') || msg.toLowerCase().includes('unauthorized')) {
        try {
          await refreshAdminToken();
          return runAction(action);
        } catch {
          setError('Session expired — please log in again.');
          setLoading(false);
          return;
        }
      }
      setError(msg);
      setLoading(false);
    }
  };

  return (
    <div className="mlops-admin">
      <header className="mlops-header">
        <div>
          <h1>MLOps Lifecycle</h1>
          <p>Train → Validate → Deploy → Monitor → Rollback</p>
        </div>
        <button onClick={refresh} disabled={loading}>Refresh</button>
      </header>

      {error && <div className="mlops-error">{error}</div>}

      <section className="mlops-grid">
        <div className="panel">
          <h3>Metrics</h3>
          <div className="kv"><span>accuracy_live</span><strong>{monitor?.accuracy_live ?? '-'}</strong></div>
          <div className="kv"><span>data_drift</span><strong>{monitor?.data_drift ?? '-'}</strong></div>
          <div className="kv"><span>concept_drift</span><strong>{monitor?.concept_drift ?? '-'}</strong></div>
          <div className="kv"><span>latency</span><strong>{monitor?.latency ?? '-'}</strong></div>
          <div className="kv"><span>cost</span><strong>{monitor?.cost ?? '-'}</strong></div>
          <div className="kv"><span>auto_rollback</span><strong>{monitor?.auto_rollback ? 'triggered' : 'none'}</strong></div>
        </div>

        <div className="panel">
          <h3>Deploy</h3>
          <div className="kv"><span>Prod</span><strong>{prodModel?.version || 'none'}</strong></div>
          <label>Model</label>
          <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)}>
            <option value="">Select model</option>
            {models.map((m) => (
              <option key={m.model_id} value={m.model_id}>{m.version} ({m.status})</option>
            ))}
          </select>
          <label>Strategy</label>
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
            <option value="canary">Canary (≤10%)</option>
            <option value="blue-green">Blue-Green</option>
            <option value="shadow">Shadow</option>
          </select>
          <div className="actions">
            <button className="mlops-btn" onClick={() => runAction('train')} disabled={loading}>Train</button>
            <button className="mlops-btn" onClick={() => runAction('validate')} disabled={loading || !selectedModel}>Validate</button>
            <button className="mlops-btn" onClick={() => runAction('deploy')} disabled={loading || !selectedModel}>Deploy</button>
            <button className="mlops-btn danger" onClick={() => runAction('rollback')} disabled={loading}>Rollback</button>
          </div>
        </div>
      </section>

      <section className="panel">
        <h3>Models</h3>
        {models.length === 0 ? (
          <p style={{ color: '#94a3b8', padding: '8px 0' }}>No models registered yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Version</th>
                <th>Model ID</th>
                <th>Status</th>
                <th>Dataset Hash</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {models.map((m) => (
                <tr key={m.model_id}>
                  <td>{m.version}</td>
                  <td>{m.model_id}</td>
                  <td>{m.status}</td>
                  <td>{(m.dataset_hash || '').slice(0, 12)}</td>
                  <td>{new Date(m.created_at).toLocaleString('vi-VN')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h3>Runs</h3>
        {runs.length === 0 ? (
          <p style={{ color: '#94a3b8', padding: '8px 0' }}>No runs recorded yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Type</th>
                <th>Status</th>
                <th>Duration(s)</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id}>
                  <td>{r.run_id}</td>
                  <td>{r.type}</td>
                  <td>{r.status}</td>
                  <td>{r.duration_seconds ?? '-'}</td>
                  <td>{new Date(r.created_at).toLocaleString('vi-VN')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* ─── Governance-grade Model Registry (Prompt-12) ─── */}
      <section className="panel" style={{ marginTop: 24 }}>
        <ModelRegistryPanel />
      </section>
    </div>
  );
}
