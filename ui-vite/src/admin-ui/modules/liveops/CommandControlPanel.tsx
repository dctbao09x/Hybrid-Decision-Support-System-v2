/**
 * Command Control Panel
 * =====================
 * 
 * UI for executing operational commands.
 */

import React, { useState, useCallback } from 'react';
import { useLiveChannel } from './useLiveChannel';
import * as service from './service';
import type { CommandResponse } from './types';

// ==============================================================================
// Types
// ==============================================================================

interface CommandDefinition {
  id: string;
  label: string;
  description: string;
  action: string;
  icon: string;
  variant: 'default' | 'warning' | 'danger';
  requiresConfirmation: boolean;
  requiresApproval: boolean;
  fields: Array<{
    name: string;
    label: string;
    type: 'text' | 'select' | 'checkbox';
    required?: boolean;
    options?: Array<{ value: string; label: string }>;
    placeholder?: string;
  }>;
  executor: (params: Record<string, string | boolean>) => Promise<CommandResponse>;
}

// ==============================================================================
// Command Definitions
// ==============================================================================

const COMMANDS: CommandDefinition[] = [
  {
    id: 'kill-crawler',
    label: 'Kill Crawler',
    description: 'Force stop a running crawler process',
    action: 'crawler_kill',
    icon: '🛑',
    variant: 'danger',
    requiresConfirmation: true,
    requiresApproval: true,
    fields: [
      { name: 'siteName', label: 'Site Name', type: 'text', required: true, placeholder: 'e.g., site_a' },
      { name: 'force', label: 'Force Kill', type: 'checkbox' },
    ],
    executor: (params) => service.killCrawler(params.siteName as string, { 
      params: { force: params.force } 
    }),
  },
  {
    id: 'pause-job',
    label: 'Pause Job',
    description: 'Pause an active job',
    action: 'job_pause',
    icon: '⏸️',
    variant: 'warning',
    requiresConfirmation: true,
    requiresApproval: false,
    fields: [
      { name: 'jobId', label: 'Job ID', type: 'text', required: true, placeholder: 'Enter job ID' },
    ],
    executor: (params) => service.pauseJob(params.jobId as string),
  },
  {
    id: 'resume-job',
    label: 'Resume Job',
    description: 'Resume a paused job',
    action: 'job_resume',
    icon: '▶️',
    variant: 'default',
    requiresConfirmation: false,
    requiresApproval: false,
    fields: [
      { name: 'jobId', label: 'Job ID', type: 'text', required: true, placeholder: 'Enter job ID' },
    ],
    executor: (params) => service.resumeJob(params.jobId as string),
  },
  {
    id: 'rollback-kb',
    label: 'Rollback KB',
    description: 'Rollback knowledge base to a previous version',
    action: 'kb_rollback',
    icon: '⏪',
    variant: 'danger',
    requiresConfirmation: true,
    requiresApproval: true,
    fields: [
      { name: 'target', label: 'KB Name', type: 'text', required: true, placeholder: 'e.g., main_kb' },
      { name: 'version', label: 'Version', type: 'text', required: true, placeholder: 'e.g., v1.2.3' },
    ],
    executor: (params) => service.rollbackKB(params.version as string, params.target as string),
  },
  {
    id: 'freeze-model',
    label: 'Freeze Model',
    description: 'Freeze a model to prevent updates',
    action: 'mlops_freeze',
    icon: '🔒',
    variant: 'warning',
    requiresConfirmation: true,
    requiresApproval: true,
    fields: [
      { name: 'modelId', label: 'Model ID', type: 'text', required: true, placeholder: 'Enter model ID' },
      { name: 'reason', label: 'Reason', type: 'text', placeholder: 'Optional reason' },
    ],
    executor: (params) => service.freezeModel(params.modelId as string, params.reason as string | undefined),
  },
  {
    id: 'retrain-model',
    label: 'Retrain Model',
    description: 'Trigger model retraining',
    action: 'mlops_retrain',
    icon: '🔄',
    variant: 'default',
    requiresConfirmation: true,
    requiresApproval: false,
    fields: [
      { name: 'modelId', label: 'Model ID', type: 'text', required: true, placeholder: 'Enter model ID' },
    ],
    executor: (params) => service.retrainModel(params.modelId as string),
  },
];

// ==============================================================================
// Components
// ==============================================================================

interface CommandButtonProps {
  command: CommandDefinition;
  onClick: () => void;
  disabled?: boolean;
}

function CommandButton({ command, onClick, disabled }: CommandButtonProps) {
  const bgColor = command.variant === 'danger' ? 'rgba(248,113,113,0.1)' : command.variant === 'warning' ? 'rgba(251,191,36,0.1)' : 'rgba(200,165,90,0.08)';
  const borderColor = command.variant === 'danger' ? 'rgba(248,113,113,0.3)' : command.variant === 'warning' ? 'rgba(251,191,36,0.3)' : 'rgba(200,165,90,0.2)';
  const labelColor = command.variant === 'danger' ? '#f87171' : command.variant === 'warning' ? '#fbbf24' : '#c8a55a';

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        width: '100%', padding: '12px', borderRadius: '10px', textAlign: 'left',
        background: bgColor, border: `1px solid ${borderColor}`,
        cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.5 : 1,
        display: 'flex', alignItems: 'flex-start', gap: '10px', transition: 'border-color 0.2s',
      }}
    >
      <span style={{ fontSize: '20px', lineHeight: 1 }}>{command.icon}</span>
      <div>
        <div style={{ fontWeight: 600, color: labelColor, fontSize: '13px' }}>{command.label}</div>
        <div style={{ fontSize: '12px', color: '#a0a0b4', marginTop: '2px' }}>{command.description}</div>
        {command.requiresApproval && (
          <span style={{ fontSize: '10px', color: '#6a6a7e', background: 'rgba(255,255,255,0.05)', padding: '1px 6px', borderRadius: '999px', marginTop: '4px', display: 'inline-block' }}>
            Requires Approval
          </span>
        )}
      </div>
    </button>
  );
}

interface CommandDialogProps {
  command: CommandDefinition;
  onClose: () => void;
  onExecute: (params: Record<string, string | boolean>) => void;
  executing: boolean;
}

function CommandDialog({ command, onClose, onExecute, executing }: CommandDialogProps) {
  const [params, setParams] = useState<Record<string, string | boolean>>({});
  const [confirmed, setConfirmed] = useState(!command.requiresConfirmation);
  const [dryRun, setDryRun] = useState(false);
  
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (command.requiresConfirmation && !confirmed) {
      return;
    }
    onExecute({ ...params, dryRun });
  };
  
  const isValid = command.fields
    .filter(f => f.required)
    .every(f => params[f.name]);
  
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(5,6,15,0.8)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50, backdropFilter: 'blur(8px)' }}>
      <div style={{ background: 'rgba(12,14,26,0.98)', border: '1px solid rgba(200,165,90,0.2)', borderRadius: '14px', width: 'min(480px, 95vw)', padding: '24px', boxShadow: '0 20px 60px rgba(0,0,0,0.7)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px' }}>
          <span style={{ fontSize: '28px' }}>{command.icon}</span>
          <div>
            <h3 style={{ margin: 0, color: '#ede8df', fontSize: '1rem', fontWeight: 700 }}>{command.label}</h3>
            <p style={{ margin: '4px 0 0', color: '#6a6a7e', fontSize: '13px' }}>{command.description}</p>
          </div>
        </div>
        
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {command.fields.map((field) => (
            <div key={field.name}>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: '#a0a0b4', marginBottom: '6px' }}>
                {field.label}{field.required && <span style={{ color: '#f87171', marginLeft: '4px' }}>*</span>}
              </label>
              
              {field.type === 'text' && (
                <input
                  type="text"
                  value={(params[field.name] as string) || ''}
                  onChange={(e) => setParams(p => ({ ...p, [field.name]: e.target.value }))}
                  placeholder={field.placeholder}
                  required={field.required}
                  style={{ width: '100%', padding: '8px 10px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(200,165,90,0.15)', borderRadius: '8px', color: '#ede8df', fontSize: '13px', boxSizing: 'border-box' }}
                />
              )}
              
              {field.type === 'checkbox' && (
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={(params[field.name] as boolean) || false}
                    onChange={(e) => setParams(p => ({ ...p, [field.name]: e.target.checked }))}
                  />
                  <span style={{ fontSize: '13px', color: '#a0a0b4' }}>{field.placeholder || 'Enable'}</span>
                </label>
              )}
              
              {field.type === 'select' && field.options && (
                <select
                  value={(params[field.name] as string) || ''}
                  onChange={(e) => setParams(p => ({ ...p, [field.name]: e.target.value }))}
                  required={field.required}
                  style={{ width: '100%', padding: '8px 10px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(200,165,90,0.15)', borderRadius: '8px', color: '#ede8df', fontSize: '13px' }}
                >
                  <option value="">Select...</option>
                  {field.options.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              )}
            </div>
          ))}
          
          <div style={{ borderTop: '1px solid rgba(200,165,90,0.1)', paddingTop: '14px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px', color: '#a0a0b4' }}>
              <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
              Dry Run (simulate without executing)
            </label>
            
            {command.requiresConfirmation && !dryRun && (
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px', color: '#f87171' }}>
                <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                I understand this action may have significant impact
              </label>
            )}
          </div>
          
          <div style={{ display: 'flex', gap: '10px', paddingTop: '4px' }}>
            <button type="button" onClick={onClose} disabled={executing}
              style={{ flex: 1, padding: '9px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(200,165,90,0.15)', borderRadius: '8px', color: '#a0a0b4', cursor: 'pointer', fontSize: '13px' }}>
              Cancel
            </button>
            <button type="submit"
              disabled={!isValid || (command.requiresConfirmation && !confirmed && !dryRun) || executing}
              style={{
                flex: 1, padding: '9px', borderRadius: '8px', border: 'none', cursor: 'pointer', fontSize: '13px', fontWeight: 600,
                background: command.variant === 'danger' ? 'rgba(248,113,113,0.8)' : command.variant === 'warning' ? 'rgba(251,191,36,0.8)' : 'rgba(200,165,90,0.8)',
                color: '#05060f', opacity: (!isValid || executing) ? 0.5 : 1
              }}>
              {executing ? 'Executing...' : dryRun ? 'Simulate' : 'Execute'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

interface CommandResultProps {
  result: CommandResponse;
  onClose: () => void;
}

function CommandResult({ result, onClose }: CommandResultProps) {
  const isSuccess = result.status === 'ok';
  
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(5,6,15,0.8)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50, backdropFilter: 'blur(8px)' }}>
      <div style={{ background: 'rgba(12,14,26,0.98)', border: '1px solid rgba(200,165,90,0.2)', borderRadius: '14px', width: 'min(400px, 95vw)', padding: '24px', boxShadow: '0 20px 60px rgba(0,0,0,0.7)' }}>
        <div style={{ textAlign: 'center', marginBottom: '16px' }}>
          <span style={{ fontSize: '36px', color: isSuccess ? '#6ee7b7' : '#f87171' }}>{isSuccess ? '✓' : '✗'}</span>
        </div>
        
        <h3 style={{ textAlign: 'center', color: isSuccess ? '#6ee7b7' : '#f87171', margin: '0 0 16px', fontSize: '1rem', fontWeight: 700 }}>
          {isSuccess ? 'Command Submitted' : 'Command Failed'}
        </h3>
        
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(200,165,90,0.1)', borderRadius: '8px', padding: '12px', fontSize: '13px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: '#6a6a7e' }}>Command ID:</span>
            <span style={{ fontFamily: 'monospace', color: '#ede8df' }}>{result.data.commandId}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: '#6a6a7e' }}>State:</span>
            <span style={{ textTransform: 'capitalize', color: '#ede8df' }}>{result.data.state}</span>
          </div>
          {Boolean(result.meta?.dry_run) && (
            <div style={{ color: '#fbbf24', fontSize: '11px', marginTop: '4px' }}>ℹ Dry run — no changes were made</div>
          )}
        </div>
        
        <button onClick={onClose}
          style={{ width: '100%', marginTop: '16px', padding: '9px', background: 'rgba(200,165,90,0.1)', border: '1px solid rgba(200,165,90,0.2)', borderRadius: '8px', color: '#c8a55a', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}>
          Close
        </button>
      </div>
    </div>
  );
}

// ==============================================================================
// Main Component
// ==============================================================================

export function CommandControlPanel() {
  const [selectedCommand, setSelectedCommand] = useState<CommandDefinition | null>(null);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<CommandResponse | null>(null);
  const { isConnected } = useLiveChannel();
  
  const handleExecute = useCallback(async (params: Record<string, string | boolean>) => {
    if (!selectedCommand) return;
    
    setExecuting(true);
    try {
      const response = await selectedCommand.executor(params);
      setResult(response);
      setSelectedCommand(null);
    } catch (error) {
      setResult({
        status: 'error',
        data: {
          commandId: '',
          state: 'failed',
        },
        meta: { error: String(error) },
      });
    } finally {
      setExecuting(false);
    }
  }, [selectedCommand]);
  
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px' }}>
          <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: isConnected ? '#6ee7b7' : '#fbbf24', display: 'inline-block' }} />
          <span style={{ color: '#6a6a7e' }}>{isConnected ? 'Connected' : 'Connecting...'}</span>
        </div>
      </div>
      
      <div className="admin-grid-cards">
        {COMMANDS.map((cmd) => (
          <CommandButton key={cmd.id} command={cmd} onClick={() => setSelectedCommand(cmd)} disabled={!isConnected} />
        ))}
      </div>
      
      {selectedCommand && (
        <CommandDialog
          command={selectedCommand}
          onClose={() => setSelectedCommand(null)}
          onExecute={handleExecute}
          executing={executing}
        />
      )}
      
      {result && (
        <CommandResult
          result={result}
          onClose={() => setResult(null)}
        />
      )}
    </div>
  );
}

export default CommandControlPanel;
