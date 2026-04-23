// src/pages/Admin/KnowledgeBase/ImportTool.jsx
/**
 * Bulk Import Tool - CSV/JSON upload for KB entities
 */

import { useState, useRef } from 'react';
import styles from './KBAdmin.module.css';
import * as kbApi from '../../../services/kbApi';

const ENTITY_TYPES = [
  { value: 'career', label: 'Careers' },
  { value: 'skill', label: 'Skills' },
  { value: 'template', label: 'Templates' },
  { value: 'ontology', label: 'Ontology Nodes' },
];

export default function ImportTool({ showToast }) {
  const [entityType, setEntityType] = useState('career');
  const [file, setFile] = useState(null);
  const [parsedData, setParsedData] = useState(null);
  const [dryRun, setDryRun] = useState(true);
  const [skipDuplicates, setSkipDuplicates] = useState(true);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState(null);
  const fileInputRef = useRef(null);

  const handleFileSelect = async (e) => {
    const selectedFile = e.target.files[0];
    if (!selectedFile) return;

    setFile(selectedFile);
    setResult(null);
    setParsedData(null);

    try {
      const text = await selectedFile.text();
      let data;

      if (selectedFile.name.endsWith('.json')) {
        data = JSON.parse(text);
        if (!Array.isArray(data)) {
          data = [data]; // wrap single object
        }
      } else if (selectedFile.name.endsWith('.csv')) {
        data = parseCSV(text);
      } else {
        throw new Error('Unsupported file type. Use .json or .csv');
      }

      setParsedData(data);
      showToast(`Parsed ${data.length} records`);
    } catch (err) {
      showToast(err.message, true);
      setFile(null);
    }
  };

  const parseCSV = (text) => {
    const lines = text.trim().split('\n');
    if (lines.length < 2) throw new Error('CSV must have header and at least one data row');

    const headers = lines[0].split(',').map(h => h.trim().replace(/^"|"$/g, ''));
    const data = [];

    for (let i = 1; i < lines.length; i++) {
      const values = parseCSVLine(lines[i]);
      if (values.length !== headers.length) continue;

      const row = {};
      headers.forEach((h, idx) => {
        let val = values[idx];
        // Try to parse JSON fields
        if (val.startsWith('[') || val.startsWith('{')) {
          try {
            val = JSON.parse(val);
          } catch {}
        }
        row[h] = val;
      });
      data.push(row);
    }

    return data;
  };

  const parseCSVLine = (line) => {
    const values = [];
    let current = '';
    let inQuotes = false;

    for (let i = 0; i < line.length; i++) {
      const char = line[i];
      if (char === '"') {
        inQuotes = !inQuotes;
      } else if (char === ',' && !inQuotes) {
        values.push(current.trim().replace(/^"|"$/g, ''));
        current = '';
      } else {
        current += char;
      }
    }
    values.push(current.trim().replace(/^"|"$/g, ''));

    return values;
  };

  const handleImport = async () => {
    if (!parsedData || parsedData.length === 0) {
      showToast('No data to import', true);
      return;
    }

    setImporting(true);
    setResult(null);

    try {
      const importResult = await kbApi.bulkImport(entityType, parsedData, {
        dry_run: dryRun,
        skip_duplicates: skipDuplicates,
      });
      setResult(importResult);
      if (dryRun) {
        showToast(`Dry run complete: ${importResult.success_count} would be imported`);
      } else {
        showToast(`Import complete: ${importResult.success_count} imported`);
      }
    } catch (err) {
      showToast(err.message, true);
    } finally {
      setImporting(false);
    }
  };

  const handleClear = () => {
    setFile(null);
    setParsedData(null);
    setResult(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      // Trigger file input with dropped file
      const dt = new DataTransfer();
      dt.items.add(droppedFile);
      fileInputRef.current.files = dt.files;
      handleFileSelect({ target: { files: [droppedFile] } });
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
  };

  return (
    <div>
      <div className={styles['import-container']}>
        <div className={styles['import-config']}>
          <h3>Import Configuration</h3>
          
          <div className={styles['kb-form-group']}>
            <label>Entity Type</label>
            <select value={entityType} onChange={e => setEntityType(e.target.value)}>
              {ENTITY_TYPES.map(t => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>

          <div className={styles['import-options']}>
            <label className={styles['import-checkbox']}>
              <input 
                type="checkbox" 
                checked={dryRun} 
                onChange={e => setDryRun(e.target.checked)} 
              />
              <span>Dry Run (validate without saving)</span>
            </label>
            <label className={styles['import-checkbox']}>
              <input 
                type="checkbox" 
                checked={skipDuplicates} 
                onChange={e => setSkipDuplicates(e.target.checked)} 
              />
              <span>Skip Duplicates</span>
            </label>
          </div>

          <div 
            className={styles['import-dropzone']}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".json,.csv"
              onChange={handleFileSelect}
              style={{ display: 'none' }}
            />
            <div className={styles['import-dropzone-icon']}>📁</div>
            <p>Drop file here or click to browse</p>
            <p className={styles['import-dropzone-hint']}>Supports .json and .csv files</p>
          </div>

          {file && (
            <div className={styles['import-file-info']}>
              <span>📄 {file.name}</span>
              <button 
                className={`${styles['kb-btn']} ${styles['kb-btn-danger']} ${styles['kb-btn-sm']}`}
                onClick={handleClear}
              >
                Clear
              </button>
            </div>
          )}

          <div className={styles['import-actions']}>
            <button
              className={`${styles['kb-btn']} ${styles['kb-btn-primary']}`}
              onClick={handleImport}
              disabled={!parsedData || importing}
            >
              {importing ? 'Importing...' : (dryRun ? 'Validate' : 'Import')}
            </button>
          </div>
        </div>

        <div className={styles['import-preview']}>
          <h3>Preview</h3>
          
          {!parsedData && (
            <div className={styles['kb-empty']}>
              <p>Upload a file to preview data</p>
            </div>
          )}

          {parsedData && parsedData.length > 0 && (
            <div className={styles['import-preview-content']}>
              <p className={styles['import-preview-count']}>
                {parsedData.length} record(s) parsed
              </p>
              <div className={styles['import-preview-table']}>
                <table className={styles['kb-table']}>
                  <thead>
                    <tr>
                      <th>#</th>
                      {Object.keys(parsedData[0]).slice(0, 5).map(key => (
                        <th key={key}>{key}</th>
                      ))}
                      {Object.keys(parsedData[0]).length > 5 && <th>...</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {parsedData.slice(0, 10).map((row, idx) => (
                      <tr key={idx}>
                        <td>{idx + 1}</td>
                        {Object.keys(row).slice(0, 5).map(key => (
                          <td key={key}>
                            {typeof row[key] === 'object' 
                              ? JSON.stringify(row[key]).slice(0, 30) + '...'
                              : String(row[key]).slice(0, 30)}
                          </td>
                        ))}
                        {Object.keys(row).length > 5 && <td>...</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {parsedData.length > 10 && (
                  <p className={styles['import-preview-more']}>
                    ... and {parsedData.length - 10} more rows
                  </p>
                )}
              </div>
            </div>
          )}

          {result && (
            <div className={styles['import-result']}>
              <h4>Import Result</h4>
              <div className={styles['import-result-stats']}>
                <div className={`${styles['import-stat']} ${styles['import-stat-success']}`}>
                  <span className={styles['import-stat-value']}>{result.success_count}</span>
                  <span className={styles['import-stat-label']}>Success</span>
                </div>
                <div className={`${styles['import-stat']} ${styles['import-stat-error']}`}>
                  <span className={styles['import-stat-value']}>{result.error_count}</span>
                  <span className={styles['import-stat-label']}>Errors</span>
                </div>
                <div className={`${styles['import-stat']} ${styles['import-stat-skip']}`}>
                  <span className={styles['import-stat-value']}>{result.skipped_count}</span>
                  <span className={styles['import-stat-label']}>Skipped</span>
                </div>
              </div>

              {result.errors && result.errors.length > 0 && (
                <div className={styles['import-errors']}>
                  <h5>Errors</h5>
                  <ul>
                    {result.errors.slice(0, 10).map((err, idx) => (
                      <li key={idx} className={styles['import-error-item']}>
                        <strong>Row {err.row}:</strong> {err.error}
                      </li>
                    ))}
                  </ul>
                  {result.errors.length > 10 && (
                    <p>... and {result.errors.length - 10} more errors</p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <div className={styles['import-help']}>
        <h3>File Format Guide</h3>
        <div className={styles['import-help-grid']}>
          <div className={styles['import-help-item']}>
            <h4>Career CSV</h4>
            <code>name,code,level,domain_id,description,market_tags</code>
            <p>market_tags as JSON array: ["tag1","tag2"]</p>
          </div>
          <div className={styles['import-help-item']}>
            <h4>Skill CSV</h4>
            <code>name,code,category,description,related_skills</code>
            <p>related_skills as JSON array</p>
          </div>
          <div className={styles['import-help-item']}>
            <h4>Template JSON</h4>
            <pre>{`[{
  "code": "tpl_001",
  "name": "Report",
  "type": "report",
  "content": "...",
  "variables": ["var1"]
}]`}</pre>
          </div>
          <div className={styles['import-help-item']}>
            <h4>Ontology JSON</h4>
            <pre>{`[{
  "code": "ont_001",
  "type": "domain",
  "label": "IT",
  "parent_id": null
}]`}</pre>
          </div>
        </div>
      </div>
    </div>
  );
}
