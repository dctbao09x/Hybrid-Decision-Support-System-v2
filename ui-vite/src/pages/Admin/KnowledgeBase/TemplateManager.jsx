// src/pages/Admin/KnowledgeBase/TemplateManager.jsx
/**
 * Template CRUD Manager
 */

import { useState, useEffect, useCallback } from 'react';
import styles from './KBAdmin.module.css';
import * as kbApi from '../../../services/kbApi';

const TEMPLATE_TYPES = [
  { value: 'prompt', label: 'Prompt' },
  { value: 'report', label: 'Report' },
  { value: 'email', label: 'Email' },
  { value: 'scoring', label: 'Scoring' },
  { value: 'custom', label: 'Custom' },
];

export default function TemplateManager({ showToast }) {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [editItem, setEditItem] = useState(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const data = await kbApi.listTemplates({
        type: typeFilter || undefined,
        limit: 100,
      });
      setTemplates(data || []);
    } catch (err) {
      showToast(err.message, true);
    } finally {
      setLoading(false);
    }
  }, [typeFilter, showToast]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleCreate = () => {
    setEditItem(null);
    setShowModal(true);
  };

  const handleEdit = (tmpl) => {
    setEditItem(tmpl);
    setShowModal(true);
  };

  const handleDelete = async (tmpl) => {
    if (!confirm(`Delete template "${tmpl.code}"?`)) return;
    try {
      await kbApi.deleteTemplate(tmpl.id);
      showToast('Template deleted');
      loadData();
    } catch (err) {
      showToast(err.message, true);
    }
  };

  const handleSave = async (data) => {
    try {
      if (editItem) {
        await kbApi.updateTemplate(editItem.id, data);
        showToast('Template updated');
      } else {
        await kbApi.createTemplate(data);
        showToast('Template created');
      }
      setShowModal(false);
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
        <div className={styles['kb-filters']}>
          <select
            className={styles['kb-filter-select']}
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
          >
            <option value="">All Types</option>
            {TEMPLATE_TYPES.map(t => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>
        <button className={`${styles['kb-btn']} ${styles['kb-btn-primary']}`} onClick={handleCreate}>
          + Add Template
        </button>
      </div>

      {templates.length === 0 ? (
        <div className={styles['kb-empty']}>
          <div className={styles['kb-empty-icon']}>📄</div>
          <p>No templates found</p>
        </div>
      ) : (
        <table className={styles['kb-table']}>
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Type</th>
              <th>Variables</th>
              <th>Version</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {templates.map(tmpl => (
              <tr key={tmpl.id}>
                <td><code>{tmpl.code}</code></td>
                <td>{tmpl.name}</td>
                <td>
                  <span className={`${styles['kb-badge']} ${styles['kb-badge-neutral']}`}>
                    {tmpl.type}
                  </span>
                </td>
                <td>{(tmpl.variables || []).join(', ') || '-'}</td>
                <td>v{tmpl.version || 1}</td>
                <td className={styles['kb-table-actions']}>
                  <button className={`${styles['kb-btn']} ${styles['kb-btn-secondary']} ${styles['kb-btn-sm']}`} onClick={() => handleEdit(tmpl)}>Edit</button>
                  <button className={`${styles['kb-btn']} ${styles['kb-btn-danger']} ${styles['kb-btn-sm']}`} onClick={() => handleDelete(tmpl)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showModal && (
        <TemplateFormModal
          item={editItem}
          onSave={handleSave}
          onClose={() => setShowModal(false)}
        />
      )}
    </div>
  );
}

function TemplateFormModal({ item, onSave, onClose }) {
  const [form, setForm] = useState({
    code: item?.code || '',
    name: item?.name || '',
    type: item?.type || 'custom',
    content: item?.content || '',
    variables: (item?.variables || []).join(', '),
  });

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm(prev => ({ ...prev, [name]: value }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const payload = {
      ...form,
      variables: form.variables.split(',').map(v => v.trim()).filter(Boolean),
    };
    onSave(payload);
  };

  return (
    <div className={styles['kb-modal-overlay']} onClick={onClose}>
      <div className={styles['kb-modal']} onClick={e => e.stopPropagation()}>
        <div className={styles['kb-modal-header']}>
          <h2>{item ? 'Edit Template' : 'Create Template'}</h2>
          <button className={styles['kb-modal-close']} onClick={onClose}>&times;</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className={styles['kb-modal-body']}>
            <div className={styles['kb-form-row']}>
              <div className={styles['kb-form-group']}>
                <label>Code *</label>
                <input name="code" value={form.code} onChange={handleChange} required disabled={!!item} />
              </div>
              <div className={styles['kb-form-group']}>
                <label>Type</label>
                <select name="type" value={form.type} onChange={handleChange}>
                  {TEMPLATE_TYPES.map(t => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className={styles['kb-form-group']}>
              <label>Name *</label>
              <input name="name" value={form.name} onChange={handleChange} required />
            </div>
            <div className={styles['kb-form-group']}>
              <label>Content *</label>
              <textarea name="content" value={form.content} onChange={handleChange} required style={{ minHeight: '150px', fontFamily: 'monospace' }} />
            </div>
            <div className={styles['kb-form-group']}>
              <label>Variables (comma-separated)</label>
              <input name="variables" value={form.variables} onChange={handleChange} placeholder="var1, var2, var3" />
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
