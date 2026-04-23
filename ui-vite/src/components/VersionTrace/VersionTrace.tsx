// src/components/VersionTrace/VersionTrace.tsx
/**
 * VersionTrace — P14 Schema Hash + Version Trace + Artifact Chain
 * ================================================================
 *
 * Renders the four version axes attached to every 1-button response:
 *   model_version / rule_version / taxonomy_version / schema_version
 *
 * Mismatch detection
 * ------------------
 * The first schema_hash seen in a session is stored in localStorage as the
 * "baseline".  Every subsequent response hash is compared against it.
 * If they differ, a warning banner is shown above the badges so the user
 * knows the system components have changed since the session started.
 *
 * The user can "accept" the new hash — this updates the baseline.
 *
 * Contract
 * --------
 * Props come directly from  DecisionResponse.meta  (Prompt-14 fields).
 * If any field is missing / "unknown" the badge is rendered in a degraded
 * state but no exception is thrown.
 */

import { useEffect, useState } from 'react';
import styles from './VersionTrace.module.css';

// ─── Constants ────────────────────────────────────────────────────────────────

/** localStorage key for the baseline schema hash. */
const LS_KEY = 'hdss_schema_hash_baseline';

/** The statically-known schema version this client was built for.
 *  Bump this whenever the DecisionResponse JSON schema breaks backward compat. */
export const EXPECTED_SCHEMA_VERSION = 'response-v4.0';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface VersionTraceProps {
  /** Active ML model version (from meta.model_version). */
  model_version: string;
  /** Rule-set fingerprint (from meta.rule_version). */
  rule_version: string;
  /** Taxonomy dataset fingerprint (from meta.taxonomy_version). */
  taxonomy_version: string;
  /** JSON schema semver (from meta.schema_version). */
  schema_version: string;
  /** Combined SHA-256 of all four versions (from meta.schema_hash). */
  schema_hash: string;
  /** Optional: timestamp when versions were resolved. */
  resolved_at?: string;
  /** Optional: SHA-256 root computed from artifact chain stages. */
  artifact_chain_root?: string;
}

// ─── Helper ──────────────────────────────────────────────────────────────────

function truncate(s: string, n = 16): string {
  if (!s || s === 'unknown') return s;
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function VersionTrace({
  model_version,
  rule_version,
  taxonomy_version,
  schema_version,
  schema_hash,
  resolved_at,
  artifact_chain_root,
}: VersionTraceProps) {
  const [mismatch, setMismatch] = useState(false);
  const [schemaMismatch, setSchemaMismatch] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  // ── Initialise / detect mismatch on mount (or when hash changes) ──────────
  useEffect(() => {
    const stored = localStorage.getItem(LS_KEY);
    if (!stored) {
      // First response — store as baseline, no mismatch
      localStorage.setItem(LS_KEY, schema_hash);
      setMismatch(false);
    } else {
      setMismatch(schema_hash !== stored && schema_hash !== 'unknown');
    }

    // Check whether the schema_version matches what this frontend expects
    setSchemaMismatch(
      schema_version !== EXPECTED_SCHEMA_VERSION &&
        schema_version !== 'unknown',
    );
    setDismissed(false);
  }, [schema_hash, schema_version]);

  // ── Accept new hash as baseline ────────────────────────────────────────────
  const handleAccept = () => {
    localStorage.setItem(LS_KEY, schema_hash);
    setMismatch(false);
    setDismissed(true);
  };

  const handleDismiss = () => setDismissed(true);

  const hasMismatch = (mismatch || schemaMismatch) && !dismissed;

  return (
    <div
      className={styles.root}
      data-testid="version-trace"
      aria-label="Version trace for this decision response"
    >
      {/* ─── Mismatch banner ─────────────────────────────────────────── */}
      {hasMismatch && (
        <div className={styles.mismatchBanner} role="alert" data-testid="version-mismatch-banner">
          <span className={styles.mismatchIcon}>⚠</span>
          <span className={styles.mismatchText}>
            {schemaMismatch
              ? `Schema version mismatch — response has "${schema_version}" but frontend expects "${EXPECTED_SCHEMA_VERSION}".`
              : `Schema hash changed since session start — component versions may have been updated.`}
          </span>
          <div className={styles.mismatchActions}>
            {!schemaMismatch && (
              <button
                className={styles.acceptBtn}
                onClick={handleAccept}
                aria-label="Accept new schema hash as baseline"
              >
                Chấp nhận
              </button>
            )}
            <button
              className={styles.dismissBtn}
              onClick={handleDismiss}
              aria-label="Dismiss mismatch warning"
            >
              Bỏ qua
            </button>
          </div>
        </div>
      )}

      {/* ─── Version badges ──────────────────────────────────────────── */}
      <div className={styles.badgesRow} data-testid="version-badges">
        <VersionBadge
          label="Model"
          value={model_version}
          testId="badge-model-version"
        />
        <VersionBadge
          label="Rules"
          value={rule_version}
          truncate
          testId="badge-rule-version"
        />
        <VersionBadge
          label="Taxonomy"
          value={taxonomy_version}
          truncate
          testId="badge-taxonomy-version"
        />
        <VersionBadge
          label="Schema"
          value={schema_version}
          highlight={schemaMismatch ? 'warn' : 'none'}
          testId="badge-schema-version"
        />
      </div>

      {/* ─── Hash row ────────────────────────────────────────────────── */}
      <div className={styles.hashRow} data-testid="schema-hash-row">
        <span className={styles.hashLabel}>schema_hash</span>
        <code
          className={`${styles.hashValue} ${mismatch && !dismissed ? styles.hashMismatch : ''}`}
          title={schema_hash}
          data-testid="schema-hash-value"
        >
          {truncate(schema_hash, 24)}
        </code>

        {artifact_chain_root && (
          <>
            <span className={styles.hashLabel} style={{ marginLeft: '1rem' }}>chain_root</span>
            <code
              className={styles.hashValue}
              title={artifact_chain_root}
              data-testid="artifact-chain-root-value"
            >
              {truncate(artifact_chain_root, 24)}
            </code>
          </>
        )}

        {resolved_at && (
          <span className={styles.resolvedAt} data-testid="version-resolved-at">
            {new Date(resolved_at).toLocaleString('vi-VN')}
          </span>
        )}
      </div>
    </div>
  );
}

// ─── Sub-component ────────────────────────────────────────────────────────────

interface VersionBadgeProps {
  label: string;
  value: string;
  truncate?: boolean;
  highlight?: 'warn' | 'error' | 'none';
  testId?: string;
}

function VersionBadge({
  label,
  value,
  truncate: doTruncate = false,
  highlight = 'none',
  testId,
}: VersionBadgeProps) {
  const isUnknown = !value || value === 'unknown';
  const displayValue = doTruncate ? truncate(value, 12) : value;

  return (
    <div
      className={`${styles.badge} ${isUnknown ? styles.badgeUnknown : ''} ${
        highlight === 'warn' ? styles.badgeWarn : ''
      } ${highlight === 'error' ? styles.badgeError : ''}`}
      data-testid={testId}
      title={value}
    >
      <span className={styles.badgeLabel}>{label}</span>
      <span className={styles.badgeValue}>{displayValue}</span>
    </div>
  );
}
