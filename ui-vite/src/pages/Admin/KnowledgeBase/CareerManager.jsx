// src/pages/Admin/KnowledgeBase/CareerManager.jsx
/**
 * Career CRUD Manager with versioning support
 */

import { useState, useEffect, useCallback } from 'react';
import styles from './KBAdmin.module.css';
import * as kbApi from '../../../services/kbApi';

export default function CareerManager({ showToast }) {
  const [careers, setCareers] = useState([]);
  const [domains, setDomains] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [domainFilter, setDomainFilter] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [editItem, setEditItem] = useState(null);
  const [historyModal, setHistoryModal] = useState(null);
  const [history, setHistory] = useState([]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [careersData, domainsData] = await Promise.all([
        kbApi.listCareers({ search, domain_id: domainFilter || undefined, limit: 100 }),
        kbApi.listDomains({ limit: 100 }),
      ]);
      setCareers(careersData || []);
      setDomains(domainsData || []);
    } catch (err) {
      showToast(err.message, true);
    } finally {
      setLoading(false);
    }
  }, [search, domainFilter, showToast]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleCreate = () => {
    setEditItem(null);
    setShowModal(true);
  };

  const handleEdit = (career) => {
    setEditItem(career);
    setShowModal(true);
  };

  const handleDelete = async (career) => {
    if (!confirm(`Delete "${career.name}"?`)) return;
    try {
      await kbApi.deleteCareer(career.id);
      showToast('Career deleted');
      loadData();
    } catch (err) {
      showToast(err.message, true);
    }
  };

  const handleSave = async (data) => {
    try {
      if (editItem) {
        await kbApi.updateCareer(editItem.id, data);
        showToast('Career updated');
      } else {
        await kbApi.createCareer(data);
        showToast('Career created');
      }
      setShowModal(false);
      loadData();
    } catch (err) {
      showToast(err.message, true);
    }
  };

  const handleViewHistory = async (career) => {
    try {
      const historyData = await kbApi.getEntityHistory('career', career.id);
      setHistory(historyData || []);
      setHistoryModal(career);
    } catch (err) {
      showToast(err.message, true);
    }
  };

  const handleRollback = async (career, version) => {
    if (!confirm(`Rollback to version ${version}?`)) return;
    try {
      await kbApi.rollbackEntity('career', career.id, version);
      showToast('Rollback successful');
      setHistoryModal(null);
      loadData();
    } catch (err) {
      showToast(err.message, true);
    }
  };

  if (loading) {
    return (
      <div className={styles['kb-loading']}>
        <div className={styles['kb-spinner']} />
      </div>
    );
  }

  return (
    <div>
      <div className={styles['kb-toolbar']}>
        <div className={styles['kb-search']}>
          <input
            type="text"
            placeholder="Search careers..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className={styles['kb-filters']}>
          <select
            className={styles['kb-filter-select']}
            value={domainFilter}
            onChange={(e) => setDomainFilter(e.target.value)}
          >
            <option value="">All Domains</option>
            {domains.map(d => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
        </div>
        <button className={`${styles['kb-btn']} ${styles['kb-btn-primary']}`} onClick={handleCreate}>
          + Add Career
        </button>
      </div>

      {careers.length === 0 ? (
        <div className={styles['kb-empty']}>
          <div className={styles['kb-empty-icon']}>💼</div>
          <p>No careers found</p>
        </div>
      ) : (
        <table className={styles['kb-table']}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Domain</th>
              <th>Level</th>
              <th>Status</th>
              <th>Version</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {careers.map(career => (
              <tr key={career.id}>
                <td>
                  <strong>{career.name}</strong>
                  {career.code && <span className={styles['kb-version-badge']}> ({career.code})</span>}
                </td>
                <td>{career.domain?.name || '-'}</td>
                <td>{career.level || '-'}</td>
                <td>
                  <span className={`${styles['kb-badge']} ${career.is_active ? styles['kb-badge-success'] : styles['kb-badge-error']}`}>
                    {career.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td>v{career.version || 1}</td>
                <td className={styles['kb-table-actions']}>
                  <button className={`${styles['kb-btn']} ${styles['kb-btn-secondary']} ${styles['kb-btn-sm']}`} onClick={() => handleEdit(career)}>Edit</button>
                  <button className={`${styles['kb-btn']} ${styles['kb-btn-secondary']} ${styles['kb-btn-sm']}`} onClick={() => handleViewHistory(career)}>History</button>
                  <button className={`${styles['kb-btn']} ${styles['kb-btn-danger']} ${styles['kb-btn-sm']}`} onClick={() => handleDelete(career)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showModal && (
        <CareerFormModal
          item={editItem}
          domains={domains}
          onSave={handleSave}
          onClose={() => setShowModal(false)}
        />
      )}

      {historyModal && (
        <HistoryModal
          entity={historyModal}
          entityType="career"
          history={history}
          onRollback={(v) => handleRollback(historyModal, v)}
          onClose={() => setHistoryModal(null)}
        />
      )}
    </div>
  );
}

function CareerFormModal({ item, domains, onSave, onClose }) {
  const [form, setForm] = useState({
    name: item?.name || '',
    code: item?.code || '',
    domain_id: item?.domain_id || (domains[0]?.id || ''),
    level: item?.level || '',
    description: item?.description || '',
    education_min: item?.education_min || '',
    ai_relevance: item?.ai_relevance ?? 0.5,
    competition: item?.competition ?? 0.5,
    growth_rate: item?.growth_rate ?? 0.5,
    salary_range_min: item?.salary_range_min || '',
    salary_range_max: item?.salary_range_max || '',
  });

  const handleChange = (e) => {
    const { name, value, type } = e.target;
    setForm(prev => ({
      ...prev,
      [name]: type === 'number' ? (value === '' ? '' : parseFloat(value)) : value,
    }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const payload = { ...form };
    if (!payload.code) delete payload.code;
    if (!payload.level) delete payload.level;
    if (!payload.salary_range_min) delete payload.salary_range_min;
    if (!payload.salary_range_max) delete payload.salary_range_max;
    payload.domain_id = parseInt(payload.domain_id, 10);
    onSave(payload);
  };

  return (
    <div className={styles['kb-modal-overlay']} onClick={onClose}>
      <div className={styles['kb-modal']} onClick={e => e.stopPropagation()}>
        <div className={styles['kb-modal-header']}>
          <h2>{item ? 'Edit Career' : 'Create Career'}</h2>
          <button className={styles['kb-modal-close']} onClick={onClose}>&times;</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className={styles['kb-modal-body']}>
            <div className={styles['kb-form-row']}>
              <div className={styles['kb-form-group']}>
                <label>Name *</label>
                <input name="name" value={form.name} onChange={handleChange} required />
              </div>
              <div className={styles['kb-form-group']}>
                <label>Code</label>
                <input name="code" value={form.code} onChange={handleChange} placeholder="auto-generated" />
              </div>
            </div>
            <div className={styles['kb-form-row']}>
              <div className={styles['kb-form-group']}>
                <label>Domain *</label>
                <select name="domain_id" value={form.domain_id} onChange={handleChange} required>
                  {domains.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </div>
              <div className={styles['kb-form-group']}>
                <label>Level</label>
                <select name="level" value={form.level} onChange={handleChange}>
                  <option value="">--</option>
                  <option value="entry">Entry</option>
                  <option value="mid">Mid</option>
                  <option value="senior">Senior</option>
                  <option value="lead">Lead</option>
                </select>
              </div>
            </div>
            <div className={styles['kb-form-group']}>
              <label>Description</label>
              <textarea name="description" value={form.description} onChange={handleChange} />
            </div>
            <div className={styles['kb-form-row']}>
              <div className={styles['kb-form-group']}>
                <label>Education Min</label>
                <input name="education_min" value={form.education_min} onChange={handleChange} />
              </div>
              <div className={styles['kb-form-group']}>
                <label>AI Relevance (0-1)</label>
                <input type="number" name="ai_relevance" value={form.ai_relevance} onChange={handleChange} min="0" max="1" step="0.1" />
              </div>
            </div>
            <div className={styles['kb-form-row']}>
              <div className={styles['kb-form-group']}>
                <label>Competition (0-1)</label>
                <input type="number" name="competition" value={form.competition} onChange={handleChange} min="0" max="1" step="0.1" />
              </div>
              <div className={styles['kb-form-group']}>
                <label>Growth Rate (0-1)</label>
                <input type="number" name="growth_rate" value={form.growth_rate} onChange={handleChange} min="0" max="1" step="0.1" />
              </div>
            </div>
            <div className={styles['kb-form-row']}>
              <div className={styles['kb-form-group']}>
                <label>Salary Min</label>
                <input type="number" name="salary_range_min" value={form.salary_range_min} onChange={handleChange} />
              </div>
              <div className={styles['kb-form-group']}>
                <label>Salary Max</label>
                <input type="number" name="salary_range_max" value={form.salary_range_max} onChange={handleChange} />
              </div>
            </div>
          </div>
          <div className={styles['kb-modal-footer']}>
            <button type="button" className={`${styles['kb-btn']} ${styles['kb-btn-secondary']}`} onClick={onClose}>Cancel</button>
            <button type="submit" className={`${styles['kb-btn']} ${styles['kb-btn-primary']}`}>Save</button>
          </div>
        </form>
      </div>
    </div>
  );
}

function HistoryModal({ entity, entityType, history, onRollback, onClose }) {
  return (
    <div className={styles['kb-modal-overlay']} onClick={onClose}>
      <div className={styles['kb-modal']} onClick={e => e.stopPropagation()}>
        <div className={styles['kb-modal-header']}>
          <h2>History: {entity.name}</h2>
          <button className={styles['kb-modal-close']} onClick={onClose}>&times;</button>
        </div>
        <div className={styles['kb-modal-body']}>
          {history.length === 0 ? (
            <p>No history available</p>
          ) : (
            <ul className={styles['kb-history-list']}>
              {history.map(h => (
                <li key={h.id} className={styles['kb-history-item']}>
                  <div className={styles['kb-history-header']}>
                    <span className={styles['kb-history-action']}>{h.action}</span>
                    <span className={styles['kb-history-time']}>{new Date(h.timestamp).toLocaleString()}</span>
                  </div>
                  <div className={styles['kb-history-user']}>by {h.user || 'system'}</div>
                  {h.version_before && (
                    <div className={styles['kb-version-badge']}>v{h.version_before} → v{h.version_after}</div>
                  )}
                  {h.diff && Object.keys(h.diff).length > 0 && (
                    <div className={styles['kb-diff']}>
                      {Object.entries(h.diff).map(([field, change]) => (
                        <div key={field}>
                          <strong>{field}:</strong>{' '}
                          <span className={styles['kb-diff-old']}>{JSON.stringify(change.old)}</span>{' → '}
                          <span className={styles['kb-diff-new']}>{JSON.stringify(change.new)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {h.version_before && h.action !== 'create' && (
                    <button
                      className={`${styles['kb-btn']} ${styles['kb-btn-secondary']} ${styles['kb-btn-sm']}`}
                      style={{ marginTop: '0.5rem' }}
                      onClick={() => onRollback(h.version_before)}
                    >
                      Rollback to v{h.version_before}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className={styles['kb-modal-footer']}>
          <button className={`${styles['kb-btn']} ${styles['kb-btn-secondary']}`} onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
