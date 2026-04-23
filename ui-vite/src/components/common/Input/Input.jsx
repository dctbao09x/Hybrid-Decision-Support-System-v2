// src/components/common/Input/Input.jsx
import styles from './Input.module.css';

export default function Input({ 
  label, 
  error,
  helperText,
  icon,
  ...props 
}) {
  return (
    <div className={styles.wrapper}>
      {label && <label className={styles.label}>{label}</label>}
      <div className={styles.inputContainer}>
        {icon && <span className={styles.icon}>{icon}</span>}
        <input 
          className={`${styles.input} ${error ? styles.error : ''} ${icon ? styles.withIcon : ''}`}
          {...props}
        />
      </div>
      {error && <span className={styles.errorText}>{error}</span>}
      {helperText && !error && <span className={styles.helperText}>{helperText}</span>}
    </div>
  );
}