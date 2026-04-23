// src/components/common/ProgressBar/ProgressBar.jsx
import styles from './ProgressBar.module.css';

export default function ProgressBar({ value, max = 100, showLabel = true }) {
  const percentage = Math.min((value / max) * 100, 100);

  return (
    <div className={styles.container}>
      <div className={styles.bar}>
        <div 
          className={styles.fill} 
          style={{ width: `${percentage}%` }}
        ></div>
      </div>
      {showLabel && (
        <span className={styles.label}>{Math.round(percentage)}%</span>
      )}
    </div>
  );
}