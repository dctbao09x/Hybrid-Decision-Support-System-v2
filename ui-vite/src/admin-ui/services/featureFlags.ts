import featuresConfig from '../config/features.json';

export type AdminFeatureKey = keyof typeof featuresConfig;

const runtimeAvailability: Partial<Record<AdminFeatureKey, boolean>> = {};

function readOverrides(): Partial<Record<AdminFeatureKey, boolean>> {
  try {
    const raw = localStorage.getItem('admin:feature-overrides');
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Partial<Record<AdminFeatureKey, boolean>>;
    return parsed;
  } catch {
    return {};
  }
}

export function markFeatureAvailability(feature: AdminFeatureKey, available: boolean) {
  runtimeAvailability[feature] = available;
}

export function isFeatureEnabled(feature: AdminFeatureKey): boolean {
  const baseEnabled = Boolean(featuresConfig[feature]);
  if (!baseEnabled) return false;

  const overrides = readOverrides();
  const override = overrides[feature];
  if (typeof override === 'boolean') return override;

  const runtime = runtimeAvailability[feature];
  if (typeof runtime === 'boolean') return runtime;

  return true;
}
