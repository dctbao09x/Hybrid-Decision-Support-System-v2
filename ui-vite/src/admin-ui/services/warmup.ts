/**
 * API Warmup Service
 * ==================
 * 
 * Pre-warms backend connections to eliminate cold start latency.
 * 
 * Features:
 * - Background warmup on page load
 * - Periodic keep-alive pings
 * - Health status tracking
 * - Graceful degradation
 */

import { apiRequest } from './apiClient';
import { endpoints } from './endpoints';

// Simple logger for warmup service (avoids circular deps)
const LOG_LEVEL = import.meta.env.VITE_LOG_LEVEL || 'info';
const shouldLogDebug = LOG_LEVEL === 'debug';

function warmupLog(message: string, data?: Record<string, unknown>): void {
  if (shouldLogDebug) {
    if (data) {
      console.log(message, data);
    } else {
      console.log(message);
    }
  }
}

export interface WarmupStatus {
  lastWarmup: number;
  backendReady: boolean;
  healthCheckPassing: boolean;
  latencyMs: number;
  consecutiveFailures: number;
  isWarming: boolean;
}

interface WarmupConfig {
  /** Warmup interval in ms (default: 30s) */
  keepAliveIntervalMs: number;
  /** Max consecutive failures before marking unhealthy */
  maxConsecutiveFailures: number;
  /** Timeout for warmup request */
  warmupTimeoutMs: number;
  /** Enable periodic keep-alive */
  enableKeepAlive: boolean;
}

const DEFAULT_CONFIG: WarmupConfig = {
  keepAliveIntervalMs: 30000,
  maxConsecutiveFailures: 3,
  warmupTimeoutMs: 5000,
  enableKeepAlive: true,
};

class WarmupService {
  private status: WarmupStatus = {
    lastWarmup: 0,
    backendReady: false,
    healthCheckPassing: false,
    latencyMs: 0,
    consecutiveFailures: 0,
    isWarming: false,
  };

  private config: WarmupConfig;
  private keepAliveTimer: number | null = null;
  private started = false;
  private listeners: Array<(status: WarmupStatus) => void> = [];

  constructor(config: Partial<WarmupConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  /**
   * Start the warmup service.
   * Call this on app initialization.
   */
  async start(): Promise<void> {
    if (this.started) return;
    this.started = true;

    warmupLog('[Warmup] Starting warmup service...');

    // Initial warmup
    await this.warmup();

    // Start keep-alive if enabled
    if (this.config.enableKeepAlive) {
      this.startKeepAlive();
    }
  }

  /**
   * Stop the warmup service.
   */
  stop(): void {
    if (this.keepAliveTimer) {
      window.clearInterval(this.keepAliveTimer);
      this.keepAliveTimer = null;
    }
    this.started = false;
    warmupLog('[Warmup] Service stopped');
  }

  /**
   * Perform a warmup request to backend.
   */
  async warmup(): Promise<boolean> {
    if (this.status.isWarming) {
      warmupLog('[Warmup] Already warming, skipping');
      return this.status.backendReady;
    }

    this.status.isWarming = true;
    const startTime = performance.now();

    try {
      // Hit the ready endpoint to warm up the backend
      const result = await apiRequest<{ ready?: boolean; status?: string }>(
        endpoints.health.ready,
        {
          method: 'GET',
          skipAuth: true,
          timeoutMs: this.config.warmupTimeoutMs,
        }
      );

      const latencyMs = performance.now() - startTime;
      
      this.status = {
        ...this.status,
        lastWarmup: Date.now(),
        backendReady: true,
        healthCheckPassing: result?.ready ?? result?.status === 'ready',
        latencyMs,
        consecutiveFailures: 0,
        isWarming: false,
      };

      warmupLog(`[Warmup] Backend ready (${latencyMs.toFixed(0)}ms)`);
      this.notifyListeners();
      return true;

    } catch (error) {
      const latencyMs = performance.now() - startTime;
      
      this.status = {
        ...this.status,
        lastWarmup: Date.now(),
        latencyMs,
        consecutiveFailures: this.status.consecutiveFailures + 1,
        isWarming: false,
      };

      // Only mark as not ready after max failures
      if (this.status.consecutiveFailures >= this.config.maxConsecutiveFailures) {
        this.status.backendReady = false;
        this.status.healthCheckPassing = false;
      }

      if (import.meta.env.DEV) {
        console.warn(
          `[Warmup] Failed (attempt ${this.status.consecutiveFailures}):`,
          error
        );
      }
      this.notifyListeners();
      return false;
    }
  }

  /**
   * Start periodic keep-alive pings.
   */
  private startKeepAlive(): void {
    if (this.keepAliveTimer) return;

    this.keepAliveTimer = window.setInterval(
      () => this.warmup(),
      this.config.keepAliveIntervalMs
    );

    warmupLog(
      `[Warmup] Keep-alive started (interval: ${this.config.keepAliveIntervalMs}ms)`
    );
  }

  /**
   * Get current warmup status.
   */
  getStatus(): WarmupStatus {
    return { ...this.status };
  }

  /**
   * Check if backend is ready.
   */
  isReady(): boolean {
    return this.status.backendReady && this.status.healthCheckPassing;
  }

  /**
   * Subscribe to status changes.
   */
  subscribe(listener: (status: WarmupStatus) => void): () => void {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== listener);
    };
  }

  private notifyListeners(): void {
    const status = this.getStatus();
    this.listeners.forEach((listener) => listener(status));
  }
}

// Singleton instance
let warmupServiceInstance: WarmupService | null = null;

/**
 * Get the warmup service instance.
 */
export function getWarmupService(): WarmupService {
  if (!warmupServiceInstance) {
    warmupServiceInstance = new WarmupService();
  }
  return warmupServiceInstance;
}

/**
 * Initialize warmup on app load.
 * Call this in your app's entry point.
 */
export async function initWarmup(): Promise<void> {
  const service = getWarmupService();
  await service.start();
}

/**
 * React hook for warmup status.
 */
export function useWarmupStatus(): WarmupStatus {
  const [status, setStatus] = useState<WarmupStatus>(
    getWarmupService().getStatus()
  );

  useEffect(() => {
    const unsubscribe = getWarmupService().subscribe(setStatus);
    return unsubscribe;
  }, []);

  return status;
}

// Re-export for convenience
import { useState, useEffect } from 'react';
