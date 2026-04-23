// src/pages/Admin/KnowledgeBase/SkillManager.jsx
/**
 * Skill CRUD Manager with versioning support
 */

import { useState, useEffect, useCallback } from 'react';
import styles from './KBAdmin.module.css';
import * as kbApi from '../../../services/kbApi';

const SKILL_CATEGORIES = [
  { value: 'technical', label: 'Technical' },
  { value: 'soft', label: 'Soft' },
  { value: 'domain', label: 'Domain' },
  { value: 'tool', label: 'Tool' },
  { value: 'language', label: 'Language' },
];

export default function SkillManager({ showToast }) {
  const [skills, setSkills] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [editItem, setEditItem] = useState(null);
  const [historyModal, setHistoryModal] = useState(null);
  const [history, setHistory] = useState([]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const data = await kbApi.listSkills({
        category: categoryFilter || undefined,
        limit: 200,
      });
      // Client-side search filter
      const filtered = search
        ? data.filter(s => s.name.toLowerCase().includes(search.toLowerCase()))
        : data;
      setSkills(filtered || []);
    } catch (err) {
      showToast(err.message, true);
    } finally {
      setLoading(false);
    }
  }, [search, categoryFilter, showToast]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleCreate = () => {
    setEditItem(null);
    setShowModal(true);
  };

  const handleEdit = (skill) => {
    setEditItem(skill);
    setShowModal(true);
  };

  const handleDelete = async (skill) => {
    if (!confirm(`Delete "${skill.name}"?`)) return;
    try {
      await kbApi.deleteSkill(skill.id);
      showToast('Skill deleted');
      loadData();
    } catch (err) {
      showToast(err.message, true);
    }
  };

  const handleSave = async (data) => {
    try {
      if (editItem) {
        await kbApi.updateSkill(editItem.id, data);
        showToast('Skill updated');
      } else {
        await kbApi.createSkill(data);
        showToast('Skill created');
      }
      setShowModal(false);
      loadData();
    } catch (err) {
      showToast(err.message, true);
    }
  };

  const handleViewHistory = async (skill) => {
    try {
      const historyData = await kbApi.getEntityHistory('skill', skill.id);
      setHistory(historyData || []);
      setHistoryModal(skill);
    } catch (err) {
      showToast(err.message, true);
    }
  };

  const handleRollback = async (skill, version) => {
    if (!confirm(`Rollback to version ${version}?`)) return;
    try {
      await kbApi.rollbackEntity('skill', skill.id, version);
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
            placeholder="Search skills..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className={styles['kb-filters']}>
          <select
            className={styles['kb-filter-select']}
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
          >
            <option value="">All Categories</option>
            {SKILL_CATEGORIES.map(c => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </div>
        <button className={`${styles['kb-btn']} ${styles['kb-btn-primary']}`} onClick={handleCreate}>
          + Add Skill
        </button>
      </div>

      {skills.length === 0 ? (
        <div className={styles['kb-empty']}>
          <div className={styles['kb-empty-icon']}>🛠️</div>
          <p>No skills found</p>
        </div>
      ) : (
        <table className={styles['kb-table']}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Category</th>
              <th>Status</th>
              <th>Version</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {skills.map(skill => (
              <tr key={skill.id}>
                <td>
                  <strong>{skill.name}</strong>
                  {skill.code && <span className={styles['kb-version-badge']}> ({skill.code})</span>}
                </td>
                <td>
                  <span className={`${styles['kb-badge']} ${styles['kb-badge-neutral']}`}>
                    {skill.category}
                  </span>
                </td>
                <td>
                  <span className={`${styles['kb-badge']} ${skill.is_active ? styles['kb-badge-success'] : styles['kb-badge-error']}`}>
                    {skill.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td>v{skill.version || 1}</td>
                <td className={styles['kb-table-actions']}>
                  <button className={`${styles['kb-btn']} ${styles['kb-btn-secondary']} ${styles['kb-btn-sm']}`} onClick={() => handleEdit(skill)}>Edit</button>
                  <button className={`${styles['kb-btn']} ${styles['kb-btn-secondary']} ${styles['kb-btn-sm']}`} onClick={() => handleViewHistory(skill)}>History</button>
                  <button className={`${styles['kb-btn']} ${styles['kb-btn-danger']} ${styles['kb-btn-sm']}`} onClick={() => handleDelete(skill)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showModal && (
        <SkillFormModal
          item={editItem}
          onSave={handleSave}
          onClose={() => setShowModal(false)}
        />
      )}

      {historyModal && (
        <HistoryModal
          entity={historyModal}
          entityType="skill"
          history={history}
          onRollback={(v) => handleRollback(historyModal, v)}
          onClose={() => setHistoryModal(null)}
        />
      )}
    </div>
  );
}

function SkillFormModal({ item, onSave, onClose }) {
  const [form, setForm] = useState({
    name: item?.name || '',
    code: item?.code || '',
    category: item?.category || 'technical',
    description: item?.description || '',
  });

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm(prev => ({ ...prev, [name]: value }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const payload = { ...form };
    if (!payload.code) delete payload.code;
    onSave(payload);
  };

  return (
    <div className={styles['kb-modal-overlay']} onClick={onClose}>
      <div className={styles['kb-modal']} onClick={e => e.stopPropagation()}>
        <div className={styles['kb-modal-header']}>
          <h2>{item ? 'Edit Skill' : 'Create Skill'}</h2>
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
            <div className={styles['kb-form-group']}>
              <label>Category</label>
              <select name="category" value={form.category} onChange={handleChange}>
                {SKILL_CATEGORIES.map(c => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            </div>
            <div className={styles['kb-form-group']}>
              <label>Description</label>
              <textarea name="description" value={form.description} onChange={handleChange} />
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
