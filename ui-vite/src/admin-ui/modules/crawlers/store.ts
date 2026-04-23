import type { CrawlerJob, CrawlerLog } from './service';

export interface CrawlersState {
  jobs: CrawlerJob[];
  logs: Record<string, CrawlerLog[]>;
  selectedSite: string;
  isLoading: boolean;
  error: string;
  isScheduleOpen: boolean;
}

export type CrawlersAction =
  | { type: 'set-loading'; payload: boolean }
  | { type: 'set-jobs'; payload: CrawlerJob[] }
  | { type: 'set-error'; payload: string }
  | { type: 'set-selected-site'; payload: string }
  | { type: 'set-site-logs'; payload: { site: string; logs: CrawlerLog[] } }
  | { type: 'set-schedule-open'; payload: boolean };

export const initialCrawlersState: CrawlersState = {
  jobs: [],
  logs: {},
  selectedSite: '',
  isLoading: true,
  error: '',
  isScheduleOpen: false,
};

export function crawlersReducer(state: CrawlersState, action: CrawlersAction): CrawlersState {
  switch (action.type) {
    case 'set-loading':
      return { ...state, isLoading: action.payload };
    case 'set-jobs': {
      const fallbackSite = state.selectedSite || action.payload[0]?.id || '';
      return { ...state, jobs: action.payload, selectedSite: fallbackSite };
    }
    case 'set-error':
      return { ...state, error: action.payload };
    case 'set-selected-site':
      return { ...state, selectedSite: action.payload };
    case 'set-site-logs':
      return {
        ...state,
        logs: {
          ...state.logs,
          [action.payload.site]: action.payload.logs,
        },
      };
    case 'set-schedule-open':
      return { ...state, isScheduleOpen: action.payload };
    default:
      return state;
  }
}
