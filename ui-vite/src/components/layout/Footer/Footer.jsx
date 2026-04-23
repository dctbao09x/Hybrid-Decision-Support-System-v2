// src/components/layout/Footer/Footer.jsx
import styles from './Footer.module.css';

export default function Footer() {
  return (
    <footer className={styles.footer}>
      <div className="container">
        <div className={styles.content}>
          <div className={styles.section}>
            <h4 className={styles.title}>DongSon Nexus</h4>
            <p className={styles.description}>
              Thấu hiểu trọng tâm. Quyết định vững chắc.
            </p>
          </div>

          <div className={styles.section}>
            <h5 className={styles.sectionTitle}>Về chúng tôi</h5>
            <ul className={styles.links}>
              <li><a href="#">Giới thiệu</a></li>
              <li><a href="#">Liên hệ</a></li>
              <li><a href="#">Điều khoản</a></li>
            </ul>
          </div>

          <div className={styles.section}>
            <h5 className={styles.sectionTitle}>Hỗ trợ</h5>
            <ul className={styles.links}>
              <li><a href="#">Câu hỏi thường gặp</a></li>
              <li><a href="#">Hướng dẫn</a></li>
              <li><a href="#">Chính sách</a></li>
            </ul>
          </div>
        </div>

        <div className={styles.bottom}>
          <p>© 2024 DongSon Nexus. All rights reserved.</p>
        </div>
      </div>
    </footer>
  );
}