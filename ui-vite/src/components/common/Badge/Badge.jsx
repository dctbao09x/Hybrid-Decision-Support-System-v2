// src/components/common/Badge/Badge.jsx
import styles from './Badge.module.css';

export default function Badge({ children, variant = 'default', size = 'md' }) {
  return (
    <span className={`${styles.badge} ${styles[variant]} ${styles[size]}`}>
      {children}
    </span>
  );
}