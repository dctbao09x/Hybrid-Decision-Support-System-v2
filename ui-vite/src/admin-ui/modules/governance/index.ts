/**
 * Governance Module Exports
 * =========================
 * 
 * Central export point for all governance components.
 */

// Main Components
export { GovernanceContainer } from './Container';
export { GovernanceView } from './View';
export { GovernanceWorkspace } from './GovernanceWorkspace';
export { GovernanceDashboard } from './GovernanceDashboard';

// Monitoring Widgets (Phase 1-3)
export { ScoreDistributionHistogram } from './ScoreDistributionHistogram';
export { AlertThresholdConfig } from './AlertThresholdConfig';
export { RuleTriggerChart } from './RuleTriggerChart';
export { RankingVolatilityChart } from './RankingVolatilityChart';
export { RankingFrequencyChart } from './RankingFrequencyChart';
export { KLDivergenceIndicator } from './KLDivergenceIndicator';

// Services and Hooks
export { loadGovernanceDashboard, type GovernanceHealth } from './service';
export { useGovernanceModule } from './hooks';
export { type GovernanceState, type GovernanceAction, initialGovernanceState, governanceReducer } from './store';
