// src/components/common/Loading/Loading.jsx
import styles from './Loading.module.css';

export default function Loading({ size = 'md', fullScreen = false }) {
  if (fullScreen) {
    return (
      <div className={styles.fullScreen}>
        <div className={`${styles.spinner} ${styles[size]}`}></div>
      </div>
    );
  }

  return <div className={`${styles.spinner} ${styles[size]}`}></div>;
}