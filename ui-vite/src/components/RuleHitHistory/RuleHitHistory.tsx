// src/components/RuleHitHistory/RuleHitHistory.tsx
/**
 * RuleHitHistory — P10
 * ====================
 *
 * Displays the rule engine audit trace from DecisionResponse.rule_applied.
 * Shows each rule evaluated during Stage 7 (frozen pass-through).
 *
 * Props:
 *   rules — array from DecisionResponse.rule_applied
 */

import styles from './RuleHitHistory.module.css';

export interface RuleEntry {
  rule: string;
  category?: string;
  priority?: number;
  outcome: string;  // "pass_through" | "flagged" | "error"
  frozen?: boolean;
}

interface RuleHitHistoryProps {
  rules: RuleEntry[];
}

const OUTCOME_STYLE: Record<string, { color: string; label: string }> = {
  pass_through: { color: '#4caf7d', label: 'PASS' },
  flagged: { color: '#e0a052', label: 'FLAG' },
  error: { color: '#e05252', label: 'ERR' },
};

function OutcomeBadge({ outcome }: { outcome: string }) {
  const cfg = OUTCOME_STYLE[outcome] ?? { color: '#888', label: outcome.toUpperCase().slice(0, 5) };
  return (
    <span
      className={styles.badge}
      style={{ background: cfg.color + '22', border: `1px solid ${cfg.color}`, color: cfg.color }}
    >
      {cfg.label}
    </span>
  );
}

export default function RuleHitHistory({ rules }: RuleHitHistoryProps) {
  if (!rules || rules.length === 0) {
    return (
      <div className={styles.wrap}>
        <h3 className={styles.title}>Rule Hit History</h3>
        <p className={styles.empty}>Không có rule nào được đánh giá.</p>
      </div>
    );
  }

  const flagged = rules.filter(r => r.outcome === 'flagged');
  const passed = rules.filter(r => r.outcome === 'pass_through');

  // Group by category
  const byCategory: Record<string, RuleEntry[]> = {};
  for (const r of rules) {
    const cat = r.category ?? 'uncategorized';
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(r);
  }

  return (
    <div className={styles.wrap}>
      <h3 className={styles.title}>Rule Hit History</h3>

      {/* Summary bar */}
      <div className={styles.summaryBar}>
        <div className={styles.summaryItem}>
          <span className={styles.summaryVal}>{rules.length}</span>
          <span className={styles.summaryKey}>total</span>
        </div>
        <div className={styles.summaryItem}>
          <span className={styles.summaryVal} style={{ color: '#4caf7d' }}>{passed.length}</span>
          <span className={styles.summaryKey}>pass</span>
        </div>
        <div className={styles.summaryItem}>
          <span className={styles.summaryVal} style={{ color: '#e0a052' }}>{flagged.length}</span>
          <span className={styles.summaryKey}>flagged</span>
        </div>
        <div className={styles.summaryItem}>
          <span className={styles.summaryVal} style={{ color: '#6b6b7a' }}>FROZEN</span>
          <span className={styles.summaryKey}>engine state</span>
        </div>
      </div>

      {/* Per-category sections */}
      {Object.entries(byCategory).map(([cat, catRules]) => (
        <details key={cat} className={styles.catDetails} open={cat !== 'uncategorized'}>
          <summary className={styles.catSummary}>
            <span className={styles.catName}>{cat.replace(/_/g, ' ')}</span>
            <span className={styles.catCount}>{catRules.length}</span>
          </summary>

          <div className={styles.ruleList}>
            {catRules.map((rule, i) => (
              <div key={i} className={styles.ruleRow}>
                <div className={styles.ruleLeft}>
                  <span className={styles.ruleName}>{rule.rule.replace(/_/g, ' ')}</span>
                  {rule.priority !== undefined && (
                    <span className={styles.rulePriority}>P{rule.priority}</span>
                  )}
                </div>
                <OutcomeBadge outcome={rule.outcome} />
              </div>
            ))}
          </div>
        </details>
      ))}

      {rules.some(r => r.frozen) && (
        <p className={styles.frozenNote}>
          Rule engine is FROZEN — no ranking modifications applied.
        </p>
      )}
    </div>
  );
}
