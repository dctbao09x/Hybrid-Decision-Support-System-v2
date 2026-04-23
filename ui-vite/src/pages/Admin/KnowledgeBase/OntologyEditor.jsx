// src/pages/Admin/KnowledgeBase/OntologyEditor.jsx
/**
 * Ontology Tree Editor - hierarchical node management
 */

import { useState, useEffect, useCallback } from 'react';
import styles from './KBAdmin.module.css';
import * as kbApi from '../../../services/kbApi';

const NODE_TYPES = [
  { value: 'domain', label: 'Domain' },
  { value: 'category', label: 'Category' },
  { value: 'skill', label: 'Skill' },
  { value: 'concept', label: 'Concept' },
];

export default function OntologyEditor({ showToast }) {
  const [nodes, setNodes] = useState([]);
  const [rootNodes, setRootNodes] = useState([]);
  const [selectedNode, setSelectedNode] = useState(null);
  const [expandedNodes, setExpandedNodes] = useState(new Set());
  const [childrenCache, setChildrenCache] = useState({});
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editItem, setEditItem] = useState(null);
  const [parentForNew, setParentForNew] = useState(null);

  const loadRootNodes = useCallback(async () => {
    setLoading(true);
    try {
      const roots = await kbApi.getOntologyRoots();
      setRootNodes(roots || []);
      // Also load all for search
      const all = await kbApi.listOntologyNodes({ limit: 500 });
      setNodes(all || []);
    } catch (err) {
      showToast(err.message, true);
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    loadRootNodes();
  }, [loadRootNodes]);

  const loadChildren = async (nodeId) => {
    if (childrenCache[nodeId]) return childrenCache[nodeId];
    try {
      const children = await kbApi.getOntologyChildren(nodeId);
      setChildrenCache(prev => ({ ...prev, [nodeId]: children }));
      return children;
    } catch (err) {
      showToast(err.message, true);
      return [];
    }
  };

  const toggleExpand = async (nodeId) => {
    const newExpanded = new Set(expandedNodes);
    if (newExpanded.has(nodeId)) {
      newExpanded.delete(nodeId);
    } else {
      await loadChildren(nodeId);
      newExpanded.add(nodeId);
    }
    setExpandedNodes(newExpanded);
  };

  const handleCreateRoot = () => {
    setEditItem(null);
    setParentForNew(null);
    setShowModal(true);
  };

  const handleCreateChild = (parent) => {
    setEditItem(null);
    setParentForNew(parent);
    setShowModal(true);
  };

  const handleEdit = (node) => {
    setEditItem(node);
    setParentForNew(null);
    setShowModal(true);
  };

  const handleDelete = async (node) => {
    if (!confirm(`Delete node "${node.label}"? This may affect child nodes.`)) return;
    try {
      await kbApi.deleteOntologyNode(node.node_id);
      showToast('Node deleted');
      // Clear cache and reload
      setChildrenCache({});
      loadRootNodes();
    } catch (err) {
      showToast(err.message, true);
    }
  };

  const handleSave = async (data) => {
    try {
      if (editItem) {
        await kbApi.updateOntologyNode(editItem.node_id, data);
        showToast('Node updated');
      } else {
        await kbApi.createOntologyNode(data);
        showToast('Node created');
      }
      setShowModal(false);
      setChildrenCache({});
      loadRootNodes();
    } catch (err) {
      showToast(err.message, true);
    }
  };

  const handleNodeClick = (node) => {
    setSelectedNode(node);
  };

  const renderNode = (node, depth = 0) => {
    const hasChildren = childrenCache[node.node_id]?.length > 0 || !expandedNodes.has(node.node_id);
    const isExpanded = expandedNodes.has(node.node_id);
    const children = childrenCache[node.node_id] || [];

    return (
      <div key={node.node_id} className={styles['ontology-node-wrapper']}>
        <div 
          className={`${styles['ontology-node']} ${selectedNode?.node_id === node.node_id ? styles['ontology-node-selected'] : ''}`}
          style={{ paddingLeft: `${depth * 20 + 8}px` }}
          onClick={() => handleNodeClick(node)}
        >
          <span 
            className={styles['ontology-expand']}
            onClick={(e) => { e.stopPropagation(); toggleExpand(node.node_id); }}
          >
            {hasChildren ? (isExpanded ? '▼' : '▶') : '•'}
          </span>
          <span className={`${styles['kb-badge']} ${styles['kb-badge-neutral']}`}>
            {node.type}
          </span>
          <span className={styles['ontology-label']}>{node.label}</span>
          <code className={styles['ontology-code']}>{node.code}</code>
        </div>
        {isExpanded && children.map(child => renderNode(child, depth + 1))}
      </div>
    );
  };

  if (loading) {
    return (
      <div className={styles['kb-loading']}>
        <div className={styles['kb-spinner']} />
      </div>
    );
  }

  return (
    <div className={styles['ontology-container']}>
      <div className={styles['ontology-tree']}>
        <div className={styles['kb-toolbar']}>
          <h3>Ontology Tree</h3>
          <button 
            className={`${styles['kb-btn']} ${styles['kb-btn-primary']} ${styles['kb-btn-sm']}`} 
            onClick={handleCreateRoot}
          >
            + Root Node
          </button>
        </div>
        <div className={styles['ontology-tree-content']}>
          {rootNodes.length === 0 ? (
            <div className={styles['kb-empty']}>
              <p>No nodes. Create a root node to start.</p>
            </div>
          ) : (
            rootNodes.map(node => renderNode(node))
          )}
        </div>
      </div>

      <div className={styles['ontology-detail']}>
        {selectedNode ? (
          <div className={styles['ontology-detail-content']}>
            <h3>{selectedNode.label}</h3>
            <div className={styles['ontology-detail-grid']}>
              <div className={styles['ontology-detail-item']}>
                <label>Code</label>
                <span><code>{selectedNode.code}</code></span>
              </div>
              <div className={styles['ontology-detail-item']}>
                <label>Type</label>
                <span>{selectedNode.type}</span>
              </div>
              <div className={styles['ontology-detail-item']}>
                <label>Node ID</label>
                <span>{selectedNode.node_id}</span>
              </div>
              <div className={styles['ontology-detail-item']}>
                <label>Parent ID</label>
                <span>{selectedNode.parent_id || '-'}</span>
              </div>
              <div className={styles['ontology-detail-item']}>
                <label>Version</label>
                <span>v{selectedNode.version || 1}</span>
              </div>
              <div className={styles['ontology-detail-item']}>
                <label>Status</label>
                <span>{selectedNode.status || 'active'}</span>
              </div>
            </div>
            {selectedNode.relations && Object.keys(selectedNode.relations).length > 0 && (
              <div className={styles['ontology-detail-section']}>
                <label>Relations</label>
                <pre>{JSON.stringify(selectedNode.relations, null, 2)}</pre>
              </div>
            )}
            {selectedNode.metadata && Object.keys(selectedNode.metadata).length > 0 && (
              <div className={styles['ontology-detail-section']}>
                <label>Metadata</label>
                <pre>{JSON.stringify(selectedNode.metadata, null, 2)}</pre>
              </div>
            )}
            <div className={styles['ontology-detail-actions']}>
              <button 
                className={`${styles['kb-btn']} ${styles['kb-btn-secondary']}`}
                onClick={() => handleCreateChild(selectedNode)}
              >
                + Add Child
              </button>
              <button 
                className={`${styles['kb-btn']} ${styles['kb-btn-secondary']}`}
                onClick={() => handleEdit(selectedNode)}
              >
                Edit
              </button>
              <button 
                className={`${styles['kb-btn']} ${styles['kb-btn-danger']}`}
                onClick={() => handleDelete(selectedNode)}
              >
                Delete
              </button>
            </div>
          </div>
        ) : (
          <div className={styles['kb-empty']}>
            <p>Select a node to view details</p>
          </div>
        )}
      </div>

      {showModal && (
        <OntologyFormModal
          item={editItem}
          parentNode={parentForNew}
          allNodes={nodes}
          onSave={handleSave}
          onClose={() => setShowModal(false)}
        />
      )}
    </div>
  );
}

function OntologyFormModal({ item, parentNode, allNodes, onSave, onClose }) {
  const [form, setForm] = useState({
    code: item?.code || '',
    type: item?.type || 'concept',
    label: item?.label || '',
    parent_id: item?.parent_id || parentNode?.node_id || '',
    relations: JSON.stringify(item?.relations || {}, null, 2),
    metadata: JSON.stringify(item?.metadata || {}, null, 2),
  });

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm(prev => ({ ...prev, [name]: value }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    let relations, metadata;
    try {
      relations = JSON.parse(form.relations || '{}');
      metadata = JSON.parse(form.metadata || '{}');
    } catch {
      alert('Invalid JSON in relations or metadata');
      return;
    }
    const payload = {
      code: form.code,
      type: form.type,
      label: form.label,
      parent_id: form.parent_id || null,
      relations,
      metadata,
    };
    onSave(payload);
  };

  return (
    <div className={styles['kb-modal-overlay']} onClick={onClose}>
      <div className={styles['kb-modal']} onClick={e => e.stopPropagation()}>
        <div className={styles['kb-modal-header']}>
          <h2>{item ? 'Edit Node' : 'Create Node'}</h2>
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
                  {NODE_TYPES.map(t => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className={styles['kb-form-group']}>
              <label>Label *</label>
              <input name="label" value={form.label} onChange={handleChange} required />
            </div>
            <div className={styles['kb-form-group']}>
              <label>Parent Node</label>
              <select name="parent_id" value={form.parent_id} onChange={handleChange}>
                <option value="">None (Root)</option>
                {allNodes.filter(n => n.node_id !== item?.node_id).map(n => (
                  <option key={n.node_id} value={n.node_id}>{n.label} ({n.code})</option>
                ))}
              </select>
            </div>
            <div className={styles['kb-form-group']}>
              <label>Relations (JSON)</label>
              <textarea 
                name="relations" 
                value={form.relations} 
                onChange={handleChange} 
                style={{ fontFamily: 'monospace', minHeight: '80px' }}
              />
            </div>
            <div className={styles['kb-form-group']}>
              <label>Metadata (JSON)</label>
              <textarea 
                name="metadata" 
                value={form.metadata} 
                onChange={handleChange} 
                style={{ fontFamily: 'monospace', minHeight: '80px' }}
              />
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
