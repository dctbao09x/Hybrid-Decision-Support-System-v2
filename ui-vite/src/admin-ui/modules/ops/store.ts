import type { OpsSnapshot } from './service';

export interface OpsState {
  snapshot: OpsSnapshot;
  isLoading: boolean;
  error: string;
  actionBusy: string; // '' | 'backup' | 'retention' | 'cache-{type}' | 'restart-{name}'
  actionResult: string;
}

export type OpsAction =
  | { type: 'set-loading'; payload: boolean }
  | { type: 'set-snapshot'; payload: OpsSnapshot }
  | { type: 'set-error'; payload: string }
  | { type: 'set-action-busy'; payload: string }
  | { type: 'set-action-result'; payload: string };

export const emptyOpsSnapshot: OpsSnapshot = {
  status: {},
  sla: {},
  alerts: [],
  metrics: {},
  health: null,
  systemInfo: null,
  systemResources: null,
  services: [],
  cacheStats: {},
  features: {},
  recoveryStatus: {},
};

export const initialOpsState: OpsState = {
  snapshot: emptyOpsSnapshot,
  isLoading: true,
  error: '',
  actionBusy: '',
  actionResult: '',
};

export function opsReducer(state: OpsState, action: OpsAction): OpsState {
  switch (action.type) {
    case 'set-loading':
      return { ...state, isLoading: action.payload };
    case 'set-snapshot':
      return { ...state, snapshot: action.payload };
    case 'set-error':
      return { ...state, error: action.payload };
    case 'set-action-busy':
      return { ...state, actionBusy: action.payload };
    case 'set-action-result':
      return { ...state, actionResult: action.payload };
    default:
      return state;
  }
}
