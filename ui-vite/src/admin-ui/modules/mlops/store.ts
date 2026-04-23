import type { MLOpsHealth } from './service';

export interface MLOpsState {
  health: MLOpsHealth | null;
  isLoading: boolean;
  error: string;
}

export type MLOpsAction =
  | { type: 'set-loading'; payload: boolean }
  | { type: 'set-health'; payload: MLOpsHealth }
  | { type: 'set-error'; payload: string };

export const initialMLOpsState: MLOpsState = {
  health: null,
  isLoading: true,
  error: '',
};

export function mlopsReducer(state: MLOpsState, action: MLOpsAction): MLOpsState {
  switch (action.type) {
    case 'set-loading':
      return { ...state, isLoading: action.payload };
    case 'set-health':
      return { ...state, health: action.payload };
    case 'set-error':
      return { ...state, error: action.payload };
    default:
      return state;
  }
}
