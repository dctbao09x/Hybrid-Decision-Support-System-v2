import type { KBHealth } from './service';

export interface KBState {
  health: KBHealth | null;
  isLoading: boolean;
  error: string;
}

export type KBAction =
  | { type: 'set-loading'; payload: boolean }
  | { type: 'set-health'; payload: KBHealth }
  | { type: 'set-error'; payload: string };

export const initialKBState: KBState = {
  health: null,
  isLoading: true,
  error: '',
};

export function kbReducer(state: KBState, action: KBAction): KBState {
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
