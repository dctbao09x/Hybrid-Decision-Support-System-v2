// src/pages/Admin/KnowledgeBase/KBAdmin.jsx
/**
 * Knowledge Base Admin - Main Container
 */

import { useState, useEffect, useCallback } from 'react';
import styles from './KBAdmin.module.css';
import CareerManager from './CareerManager';
import SkillManager from './SkillManager';
import TemplateManager from './TemplateManager';
import OntologyEditor from './OntologyEditor';
import ImportTool from './ImportTool';

const TABS = [
  { id: 'careers', label: 'Careers', icon: '💼' },
  { id: 'skills', label: 'Skills', icon: '🛠️' },
  { id: 'templates', label: 'Templates', icon: '📄' },
  { id: 'ontology', label: 'Ontology', icon: '🔗' },
  { id: 'import', label: 'Import', icon: '📥' },
];

export default function KBAdmin() {
  const [activeTab, setActiveTab] = useState('careers');
  const [toast, setToast] = useState(null);

  const showToast = useCallback((message, isError = false) => {
    setToast({ message, isError });
    setTimeout(() => setToast(null), 3000);
  }, []);

  const renderContent = () => {
    switch (activeTab) {
      case 'careers':
        return <CareerManager showToast={showToast} />;
      case 'skills':
        return <SkillManager showToast={showToast} />;
      case 'templates':
        return <TemplateManager showToast={showToast} />;
      case 'ontology':
        return <OntologyEditor showToast={showToast} />;
      case 'import':
        return <ImportTool showToast={showToast} />;
      default:
        return null;
    }
  };

  return (
    <div className={styles['kb-admin']}>
      <div className={styles['kb-admin-header']}>
        <h1>Knowledge Base Admin</h1>
      </div>

      <div className={styles['kb-tabs']}>
        {TABS.map(tab => (
          <button
            key={tab.id}
            className={`${styles['kb-tab']} ${activeTab === tab.id ? styles.active : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {renderContent()}

      {toast && (
        <div className={`${styles['kb-toast']} ${toast.isError ? styles['kb-toast-error'] : ''}`}>
          {toast.message}
        </div>
      )}
    </div>
  );
}
