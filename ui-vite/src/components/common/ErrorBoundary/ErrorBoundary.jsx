import { Component } from 'react';
import styles from './ErrorBoundary.module.css';

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    if (this.props.onError) {
      this.props.onError(error, info);
    }
  }

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className={styles.container}>
          <h2 className={styles.title}>Có lỗi xảy ra</h2>
          <p className={styles.message}>
            Trang đã gặp lỗi không mong muốn. Hãy thử tải lại.
          </p>
          <button className={styles.button} onClick={this.handleReload}>
            Tải lại
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
