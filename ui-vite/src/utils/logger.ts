// src/utils/logger.ts
/**
 * Logging utilities for Explain UI (Stage 6)
 * 
 * Provides structured console logging and optional telemetry.
 * Enable verbose mode via VITE_LOG_LEVEL=debug
 */

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

interface LogEntry {
  timestamp: string;
  level: LogLevel;
  message: string;
  data?: Record<string, unknown>;
}

interface TelemetryEvent {
  name: string;
  timestamp: string;
  duration?: number;
  success?: boolean;
  metadata?: Record<string, unknown>;
}

// Configuration from environment
const LOG_LEVEL = (import.meta.env.VITE_LOG_LEVEL as LogLevel) || 'info';
const ENABLE_TELEMETRY = import.meta.env.VITE_ENABLE_TELEMETRY === 'true';
const TELEMETRY_ENDPOINT = import.meta.env.VITE_TELEMETRY_ENDPOINT || '';

// Log level priorities
const LEVEL_PRIORITY: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

// In-memory log buffer for debugging
const logBuffer: LogEntry[] = [];
const MAX_BUFFER_SIZE = 100;

// Telemetry queue for batching
const telemetryQueue: TelemetryEvent[] = [];
const TELEMETRY_BATCH_SIZE = 10;
const TELEMETRY_FLUSH_INTERVAL_MS = 30000;

/**
 * Check if a log level should be output.
 */
function shouldLog(level: LogLevel): boolean {
  return LEVEL_PRIORITY[level] >= LEVEL_PRIORITY[LOG_LEVEL];
}

/**
 * Format log entry for console output.
 */
function formatLogEntry(entry: LogEntry): string {
  const time = entry.timestamp.split('T')[1].slice(0, 12);
  const levelTag = `[${entry.level.toUpperCase()}]`.padEnd(7);
  return `${time} ${levelTag} ${entry.message}`;
}

/**
 * Add entry to log buffer.
 */
function bufferLog(entry: LogEntry): void {
  logBuffer.push(entry);
  if (logBuffer.length > MAX_BUFFER_SIZE) {
    logBuffer.shift();
  }
}

/**
 * Core log function.
 */
function log(level: LogLevel, message: string, data?: Record<string, unknown>): void {
  if (!shouldLog(level)) return;
  
  const entry: LogEntry = {
    timestamp: new Date().toISOString(),
    level,
    message,
    data,
  };
  
  bufferLog(entry);
  
  const formatted = formatLogEntry(entry);
  const consoleMethod = level === 'debug' ? 'log' : level;
  
  if (data && Object.keys(data).length > 0) {
    console[consoleMethod](formatted, data);
  } else {
    console[consoleMethod](formatted);
  }
}

/**
 * Log debug message (only in debug mode).
 */
export function logDebug(message: string, data?: Record<string, unknown>): void {
  log('debug', message, data);
}

/**
 * Log info message.
 */
export function logInfo(message: string, data?: Record<string, unknown>): void {
  log('info', message, data);
}

/**
 * Log warning message.
 */
export function logWarn(message: string, data?: Record<string, unknown>): void {
  log('warn', message, data);
}

/**
 * Log error message.
 */
export function logError(message: string, data?: Record<string, unknown>): void {
  log('error', message, data);
}

/**
 * Track API call metrics.
 */
export function trackApiCall(
  endpoint: string,
  durationMs: number,
  success: boolean,
  errorCode?: string
): void {
  logInfo(`API call: ${endpoint}`, {
    duration: `${durationMs.toFixed(0)}ms`,
    success,
    ...(errorCode && { errorCode }),
  });
  
  if (ENABLE_TELEMETRY) {
    queueTelemetry({
      name: 'api_call',
      timestamp: new Date().toISOString(),
      duration: durationMs,
      success,
      metadata: {
        endpoint,
        errorCode,
      },
    });
  }
}

/**
 * Track user action.
 */
export function trackUserAction(
  action: string,
  metadata?: Record<string, unknown>
): void {
  logDebug(`User action: ${action}`, metadata);
  
  if (ENABLE_TELEMETRY) {
    queueTelemetry({
      name: 'user_action',
      timestamp: new Date().toISOString(),
      metadata: {
        action,
        ...metadata,
      },
    });
  }
}

/**
 * Track page view.
 */
export function trackPageView(page: string, params?: Record<string, unknown>): void {
  logDebug(`Page view: ${page}`, params);
  
  if (ENABLE_TELEMETRY) {
    queueTelemetry({
      name: 'page_view',
      timestamp: new Date().toISOString(),
      metadata: {
        page,
        ...params,
      },
    });
  }
}

/**
 * Track error occurrence.
 */
export function trackError(
  errorCode: string,
  message: string,
  context?: Record<string, unknown>
): void {
  logError(`Error tracked: ${errorCode}`, { message, ...context });
  
  if (ENABLE_TELEMETRY) {
    queueTelemetry({
      name: 'error',
      timestamp: new Date().toISOString(),
      metadata: {
        errorCode,
        message,
        ...context,
      },
    });
  }
}

/**
 * Queue telemetry event for batching.
 */
function queueTelemetry(event: TelemetryEvent): void {
  telemetryQueue.push(event);
  
  if (telemetryQueue.length >= TELEMETRY_BATCH_SIZE) {
    flushTelemetry();
  }
}

/**
 * Flush telemetry queue to endpoint.
 */
async function flushTelemetry(): Promise<void> {
  if (!ENABLE_TELEMETRY || !TELEMETRY_ENDPOINT || telemetryQueue.length === 0) {
    return;
  }
  
  const events = telemetryQueue.splice(0, telemetryQueue.length);
  
  try {
    await fetch(TELEMETRY_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events }),
    });
    logDebug(`[Telemetry] Flushed ${events.length} events`);
  } catch (error) {
    // Don't use logError here to avoid infinite loop
    console.warn('[Telemetry] Failed to flush events:', error);
    // Re-queue events on failure (limited attempts)
    telemetryQueue.unshift(...events.slice(0, 20));
  }
}

/**
 * Get log buffer for debugging.
 */
export function getLogBuffer(): LogEntry[] {
  return [...logBuffer];
}

/**
 * Clear log buffer.
 */
export function clearLogBuffer(): void {
  logBuffer.length = 0;
}

/**
 * Calculate performance timing.
 */
export function measurePerformance(label: string): () => number {
  const start = performance.now();
  return () => {
    const duration = performance.now() - start;
    logDebug(`[Performance] ${label}: ${duration.toFixed(2)}ms`);
    return duration;
  };
}

// Set up periodic telemetry flush
if (ENABLE_TELEMETRY && TELEMETRY_ENDPOINT) {
  setInterval(flushTelemetry, TELEMETRY_FLUSH_INTERVAL_MS);
  
  // Flush on page unload
  if (typeof window !== 'undefined') {
    window.addEventListener('beforeunload', () => {
      if (telemetryQueue.length > 0) {
        // Use sendBeacon for reliability during unload
        const data = JSON.stringify({ events: telemetryQueue });
        navigator.sendBeacon?.(TELEMETRY_ENDPOINT, data);
      }
    });
  }
}

export default {
  logDebug,
  logInfo,
  logWarn,
  logError,
  trackApiCall,
  trackUserAction,
  trackPageView,
  trackError,
  getLogBuffer,
  clearLogBuffer,
  measurePerformance,
};
