// src/components/common/Button/Button.jsx
import styles from './Button.module.css';

export default function Button({ 
  children, 
  variant = 'primary', 
  size = 'md',
  fullWidth = false,
  disabled = false,
  onClick,
  type = 'button',
  icon,
  ...props 
}) {
  const classNames = [
    styles.button,
    styles[variant],
    styles[size],
    fullWidth && styles.fullWidth,
    disabled && styles.disabled
  ].filter(Boolean).join(' ');

  return (
    <button 
      className={classNames}
      onClick={onClick}
      disabled={disabled}
      type={type}
      {...props}
    >
      {icon && <span className={styles.icon}>{icon}</span>}
      {children}
    </button>
  );
}