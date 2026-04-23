export interface GovernanceState {
  dashboard: Record<string, unknown> | null;
  isLoading: boolean;
  error: string;
}

export type GovernanceAction =
  | { type: 'set-loading'; payload: boolean }
  | { type: 'set-dashboard'; payload: Record<string, unknown> }
  | { type: 'set-error'; payload: string };

export const initialGovernanceState: GovernanceState = {
  dashboard: null,
  isLoading: true,
  error: '',
};

export function governanceReducer(state: GovernanceState, action: GovernanceAction): GovernanceState {
  switch (action.type) {
    case 'set-loading':
      return { ...state, isLoading: action.payload };
    case 'set-dashboard':
      return { ...state, dashboard: action.payload };
    case 'set-error':
      return { ...state, error: action.payload };
    default:
      return state;
  }
}
