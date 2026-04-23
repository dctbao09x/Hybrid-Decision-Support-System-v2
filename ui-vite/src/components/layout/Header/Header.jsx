// src/components/layout/Header/Header.jsx
/**
 * Header - Simplified Navigation for 1-Button Pipeline
 * 
 * Only shows:
 *   - Logo (links to main page)
 *   - Admin link (for admin users)
 */
import { Link, useLocation } from 'react-router-dom';
import styles from './Header.module.css';

export default function Header() {
  const location = useLocation();

  // Simplified nav - only main page (all functionality consolidated)
  const navItems = [
    { path: '/', label: 'Trang chủ' },
  ];

  return (
    <header className={styles.header}>
      <div className="container">
        <div className={styles.content}>
          <Link to="/" className={styles.logo}>
            <span className={styles.logoText}>DongSon Nexus</span>
          </Link>

          <nav className={styles.nav}>
            {navItems.map(item => (
              <Link
                key={item.path}
                to={item.path}
                className={`${styles.navLink} ${location.pathname === item.path ? styles.active : ''}`}
              >
                {item.label}
              </Link>
            ))}
          </nav>

          <div className={styles.actions}>
            {/* Admin link - only for authenticated admins */}
            <Link to="/admin/login" className={styles.adminLink}>
              Admin
            </Link>
          </div>
        </div>
      </div>
    </header>
  );
}
