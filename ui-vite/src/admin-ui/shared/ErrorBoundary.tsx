/**
 * Global Error Boundary
 * =====================
 * 
 * Catches unhandled errors and provides graceful degradation.
 * 
 * Features:
 * - React error boundary for component errors
 * - Global error event handler for unhandled rejections
 * - User-friendly error display
 * - Error reporting to backend (optional)
 */

import React, { Component, ErrorInfo, ReactNode } from 'react';

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

/**
 * Error boundary component for catching React rendering errors.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('[ErrorBoundary] Caught error:', error, errorInfo);
    
    this.setState({ errorInfo });
    
    // Call custom error handler if provided
    if (this.props.onError) {
      this.props.onError(error, errorInfo);
    }
    
    // Report to error tracking service
    reportError(error, {
      componentStack: errorInfo.componentStack ?? undefined,
      source: 'ErrorBoundary',
    });
  }

  handleRetry = (): void => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="error-boundary-fallback" style={styles.container}>
          <div style={styles.content}>
            <h2 style={styles.title}>Something went wrong</h2>
            <p style={styles.message}>
              An unexpected error occurred. Please try refreshing the page.
            </p>
            {this.state.error && (
              <details style={styles.details}>
                <summary style={styles.summary}>Error details</summary>
                <pre style={styles.code}>
                  {this.state.error.message}
                  {this.state.errorInfo?.componentStack}
                </pre>
              </details>
            )}
            <button onClick={this.handleRetry} style={styles.button}>
              Try Again
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: '200px',
    padding: '20px',
  },
  content: {
    textAlign: 'center',
    maxWidth: '600px',
  },
  title: {
    fontSize: '1.5rem',
    fontWeight: 600,
    marginBottom: '12px',
    color: '#dc3545',
  },
  message: {
    color: '#6c757d',
    marginBottom: '16px',
  },
  details: {
    textAlign: 'left',
    marginBottom: '16px',
    padding: '12px',
    backgroundColor: '#f8f9fa',
    borderRadius: '4px',
  },
  summary: {
    cursor: 'pointer',
    fontWeight: 500,
  },
  code: {
    fontSize: '0.8rem',
    overflow: 'auto',
    maxHeight: '200px',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
  button: {
    padding: '8px 24px',
    fontSize: '1rem',
    backgroundColor: '#0d6efd',
    color: 'white',
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer',
  },
};

/**
 * Error reporting utilities
 */

interface ErrorContext {
  componentStack?: string;
  source?: string;
  userId?: string;
  sessionId?: string;
  url?: string;
  userAgent?: string;
  [key: string]: unknown;
}

/**
 * Report an error to the backend error tracking service.
 */
export function reportError(error: Error, context: ErrorContext = {}): void {
  const errorReport = {
    message: error.message,
    name: error.name,
    stack: error.stack,
    url: window.location.href,
    userAgent: navigator.userAgent,
    timestamp: new Date().toISOString(),
    ...context,
  };

  // Log locally
  console.error('[ErrorReport]', errorReport);

  // Send to backend (fire and forget)
  try {
    fetch('/api/v1/errors/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(errorReport),
      keepalive: true, // Ensure delivery even on page unload
    }).catch(() => {
      // Silently ignore - we can't do much if error reporting fails
    });
  } catch {
    // Ignore errors during error reporting
  }
}

/**
 * Global error handlers setup.
 * Call this once on app initialization.
 */
export function setupGlobalErrorHandlers(): void {
  // Handle unhandled promise rejections
  window.addEventListener('unhandledrejection', (event) => {
    console.error('[GlobalError] Unhandled promise rejection:', event.reason);
    
    const error = event.reason instanceof Error
      ? event.reason
      : new Error(String(event.reason));
    
    reportError(error, {
      source: 'unhandledrejection',
    });
  });

  // Handle global errors
  window.addEventListener('error', (event) => {
    console.error('[GlobalError] Uncaught error:', event.error);
    
    if (event.error instanceof Error) {
      reportError(event.error, {
        source: 'window.onerror',
        filename: event.filename,
        lineno: event.lineno,
        colno: event.colno,
      });
    }
  });

  if (import.meta.env.DEV) {
    console.log('[GlobalError] Error handlers installed');
  }
}

/**
 * API error handler for network failures.
 * Use this in API service layers.
 */
export function handleApiError(
  error: unknown,
  context: { operation: string; endpoint?: string }
): never {
  const apiError = error as {
    status?: number;
    message?: string;
    code?: string;
  };

  const errorMessage = apiError.message || 'An unexpected error occurred';
  const status = apiError.status || 500;

  // Log with context
  console.error(`[API Error] ${context.operation}:`, {
    status,
    message: errorMessage,
    endpoint: context.endpoint,
  });

  // Report to backend
  reportError(new Error(`API Error: ${errorMessage}`), {
    source: 'api',
    operation: context.operation,
    endpoint: context.endpoint,
    status,
    code: apiError.code,
  });

  throw error;
}
