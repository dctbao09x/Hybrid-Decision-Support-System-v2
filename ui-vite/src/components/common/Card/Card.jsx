// src/components/common/Card/Card.jsx
import styles from './Card.module.css';

export default function Card({ 
  children, 
  hover = false,
  onClick,
  className = '',
  ...props 
}) {
  const classNames = [
    styles.card,
    hover && styles.hover,
    onClick && styles.clickable,
    className
  ].filter(Boolean).join(' ');

  return (
    <div className={classNames} onClick={onClick} {...props}>
      {children}
    </div>
  );
}