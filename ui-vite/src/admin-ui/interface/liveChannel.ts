/**
 * Live Channel - Realtime Data Communication Layer
 * =================================================
 * 
 * Provides WebSocket/SSE/Polling fallback for real-time operations.
 * 
 * Features:
 * - Auto reconnect with exponential backoff
 * - Heartbeat monitoring
 * - Permission-aware streams
 * - Module-based subscriptions
 */

import { getAdminSession } from '../../utils/adminSession';
import { refreshAdminToken } from '../../services/adminAuthApi';

// ==============================================================================
// Types
// ==============================================================================

export type LiveEventType = 'status' | 'alert' | 'metric' | 'log' | 'command' | 'heartbeat';
export type ModuleType = 'mlops' | 'crawler' | 'ops' | 'kb' | 'governance' | 'pipeline' | 'system';

export interface LiveEvent<T = unknown> {
  type: LiveEventType;
  module: ModuleType;
  payload: T;
  ts: string;
  traceId?: string;
}

export interface ChannelConfig {
  wsUrl?: string;
  sseUrl?: string;
  pollUrl?: string;
  heartbeatInterval?: number;
  reconnectBaseDelay?: number;
  maxReconnectDelay?: number;
  maxReconnectAttempts?: number;
}

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting' | 'error';
export type TransportType = 'websocket' | 'sse' | 'polling';

export interface LiveChannelState {
  connectionState: ConnectionState;
  transport: TransportType | null;
  lastHeartbeat: number | null;
  reconnectAttempts: number;
  subscribedModules: Set<ModuleType>;
}

type EventHandler<T = unknown> = (event: LiveEvent<T>) => void;
type StateChangeHandler = (state: ConnectionState) => void;

// ==============================================================================
// Default Configuration
// ==============================================================================

const DEFAULT_CONFIG: Required<ChannelConfig> = {
  wsUrl: `${resolveWsBaseUrl()}/api/v1/live/ws`,
  sseUrl: `${resolveApiBaseUrl()}/api/v1/live/sse`,
  pollUrl: `${resolveApiBaseUrl()}/api/v1/live/poll`,
  heartbeatInterval: 30000,
  reconnectBaseDelay: 1000,
  maxReconnectDelay: 30000,
  maxReconnectAttempts: 10,
};

function resolveApiBaseUrl(): string {
  const raw = import.meta.env.VITE_API_BASE_URL ?? '';
  if (!raw) return ''; // use relative paths via Vite proxy
  try {
    const parsed = new URL(raw);
    if (parsed.hostname === 'localhost') {
      parsed.hostname = '127.0.0.1';
    }
    return parsed.toString().replace(/\/$/, '');
  } catch {
    return '';
  }
}

function resolveWsBaseUrl(): string {
  const apiUrl = resolveApiBaseUrl();
  if (!apiUrl) {
    // Derive WebSocket URL from current page origin via proxy
    const loc = window.location;
    return `${loc.protocol === 'https:' ? 'wss' : 'ws'}://${loc.host}`;
  }
  return apiUrl.replace(/^http/, 'ws');
}

// ==============================================================================
// Live Channel Class
// ==============================================================================

export class LiveChannel {
  private config: Required<ChannelConfig>;
  private state: LiveChannelState;
  private ws: WebSocket | null = null;
  private sse: EventSource | null = null;
  private pollInterval: number | null = null;
  private heartbeatTimer: number | null = null;
  private reconnectTimer: number | null = null;
  private pollingFailureCount = 0;
  
  private eventHandlers: Map<string, Set<EventHandler>> = new Map();
  private stateHandlers: Set<StateChangeHandler> = new Set();
  
  constructor(config: ChannelConfig = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.state = {
      connectionState: 'disconnected',
      transport: null,
      lastHeartbeat: null,
      reconnectAttempts: 0,
      subscribedModules: new Set(),
    };
  }

  // ============================================================================
  // Public API
  // ============================================================================

  /**
   * Connect to the realtime channel
   */
  async connect(): Promise<void> {
    if (
      this.state.connectionState === 'connected' ||
      this.state.connectionState === 'connecting'
    ) {
      return;
    }

    // Clean up any existing transports before reconnecting
    this.stopPolling();
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.close();
      this.ws = null;
    }
    if (this.sse) {
      this.sse.onerror = null;
      this.sse.close();
      this.sse = null;
    }

    this.setConnectionState('connecting');

    // Try WebSocket first, then SSE, then polling
    try {
      await this.connectWebSocket();
      return;
    } catch (wsError) {
      console.warn('[LiveChannel] WebSocket failed, trying SSE:', wsError);
    }

    try {
      await this.connectSSE();
      return;
    } catch (sseError) {
      console.warn('[LiveChannel] SSE failed, falling back to polling:', sseError);
    }

    try {
      await this.startPolling();
    } catch (pollError) {
      console.error('[LiveChannel] All transports failed:', pollError);
      this.setConnectionState('error');
      throw new Error('Failed to establish realtime connection');
    }
  }

  /**
   * Subscribe to events from a specific module
   */
  subscribe(module: ModuleType): void {
    this.state.subscribedModules.add(module);
    this.sendSubscription('subscribe', module);
  }

  /**
   * Unsubscribe from a specific module
   */
  unsubscribe(module: ModuleType): void {
    this.state.subscribedModules.delete(module);
    this.sendSubscription('unsubscribe', module);
  }

  /**
   * Unsubscribe from all modules
   */
  unsubscribeAll(): void {
    for (const module of this.state.subscribedModules) {
      this.sendSubscription('unsubscribe', module);
    }
    this.state.subscribedModules.clear();
  }

  /**
   * Register an event handler
   */
  onEvent<T = unknown>(type: LiveEventType | '*', handler: EventHandler<T>): () => void {
    const key = type;
    if (!this.eventHandlers.has(key)) {
      this.eventHandlers.set(key, new Set());
    }
    this.eventHandlers.get(key)!.add(handler as EventHandler);
    
    // Return unsubscribe function
    return () => {
      this.eventHandlers.get(key)?.delete(handler as EventHandler);
    };
  }

  /**
   * Register a state change handler
   */
  onStateChange(handler: StateChangeHandler): () => void {
    this.stateHandlers.add(handler);
    return () => {
      this.stateHandlers.delete(handler);
    };
  }

  /**
   * Force reconnection
   */
  reconnect(): void {
    this.disconnect();
    this.state.reconnectAttempts = 0;
    this.connect();
  }

  /**
   * Disconnect from the channel
   */
  disconnect(): void {
    this.stopHeartbeat();
    this.stopReconnect();

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    if (this.sse) {
      this.sse.close();
      this.sse = null;
    }

    this.stopPolling();

    this.setConnectionState('disconnected');
    this.state.transport = null;
  }

  /**
   * Get current state
   */
  getState(): Readonly<LiveChannelState> {
    return { ...this.state, subscribedModules: new Set(this.state.subscribedModules) };
  }

  /**
   * Send a command through the channel
   */
  sendCommand(command: string, payload: unknown): void {
    const message = JSON.stringify({
      action: 'command',
      command,
      payload,
      ts: new Date().toISOString(),
    });

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(message);
    } else {
      console.warn('[LiveChannel] Cannot send command: not connected via WebSocket');
    }
  }

  // ============================================================================
  // Private: WebSocket
  // ============================================================================

  private connectWebSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      const session = getAdminSession();
      const token = session?.accessToken || '';
      
      const url = new URL(this.config.wsUrl);
      url.searchParams.set('token', token);
      
      this.ws = new WebSocket(url.toString());
      
      const timeout = setTimeout(() => {
        reject(new Error('WebSocket connection timeout'));
      }, 10000);

      this.ws.onopen = () => {
        clearTimeout(timeout);
        this.state.transport = 'websocket';
        this.setConnectionState('connected');
        this.state.reconnectAttempts = 0;
        this.startHeartbeat();
        
        // Resubscribe to modules
        for (const module of this.state.subscribedModules) {
          this.sendSubscription('subscribe', module);
        }
        
        resolve();
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as LiveEvent;
          this.handleEvent(data);
        } catch (e) {
          console.error('[LiveChannel] Failed to parse message:', e);
        }
      };

      this.ws.onclose = (_event) => {
        clearTimeout(timeout);
        if (this.state.connectionState === 'connected') {
          this.scheduleReconnect();
        }
      };

      this.ws.onerror = (error) => {
        clearTimeout(timeout);
        reject(error);
      };
    });
  }

  // ============================================================================
  // Private: SSE
  // ============================================================================

  private connectSSE(): Promise<void> {
    return new Promise((resolve, reject) => {
      const session = getAdminSession();
      const token = session?.accessToken || '';
      
      const url = new URL(this.config.sseUrl);
      url.searchParams.set('token', token);
      
      this.sse = new EventSource(url.toString());
      
      const timeout = setTimeout(() => {
        reject(new Error('SSE connection timeout'));
      }, 10000);

      this.sse.onopen = () => {
        clearTimeout(timeout);
        this.state.transport = 'sse';
        this.setConnectionState('connected');
        this.state.reconnectAttempts = 0;
        this.startHeartbeat();
        resolve();
      };

      this.sse.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as LiveEvent;
          this.handleEvent(data);
        } catch (e) {
          console.error('[LiveChannel] Failed to parse SSE message:', e);
        }
      };

      this.sse.onerror = (error) => {
        clearTimeout(timeout);
        if (this.state.connectionState === 'connected') {
          this.scheduleReconnect();
        } else {
          reject(error);
        }
      };
    });
  }

  // ============================================================================
  // Private: Polling
  // ============================================================================

  private startPolling(): Promise<void> {
    return new Promise((resolve, reject) => {
      const pollOnce = async (allowRefresh = true) => {
        const session = getAdminSession();
        const token = session?.accessToken || '';

        if (!token) {
          throw new Error('Missing admin access token for live polling');
        }

        const response = await fetch(this.config.pollUrl, {
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
          credentials: 'include',
        });

        if (response.status === 401 && allowRefresh && session.refreshToken) {
          await refreshAdminToken();
          return pollOnce(false);
        }

        if (!response.ok) {
          throw new Error(`Poll failed: ${response.status}`);
        }

        const events = await response.json();
        if (Array.isArray(events)) {
          for (const event of events) {
            this.handleEvent(event as LiveEvent);
          }
        }
      };

      const poll = async () => {
        try {
          await pollOnce(true);
          this.pollingFailureCount = 0;
        } catch (e) {
          this.pollingFailureCount += 1;
          console.error('[LiveChannel] Polling error:', e);

          if (this.pollingFailureCount >= 3) {
            this.stopPolling();
            this.scheduleReconnect();
          }
        }
      };

      // Initial poll must succeed before claiming connected state.
      pollOnce(true).then(() => {
        this.pollingFailureCount = 0;
        this.state.transport = 'polling';
        this.setConnectionState('connected');
        this.state.reconnectAttempts = 0;

        // Clear any existing interval before starting a new one
        this.stopPolling();
        this.pollInterval = window.setInterval(() => {
          void poll();
        }, 5000);
        resolve();
      }).catch(reject);
    });
  }

  // ============================================================================
  // Private: Heartbeat
  // ============================================================================

  private startHeartbeat(): void {
    this.stopHeartbeat();
    
    this.heartbeatTimer = window.setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ action: 'ping' }));
      }
      
      // Check for missed heartbeats
      if (this.state.lastHeartbeat) {
        const sinceLastHeartbeat = Date.now() - this.state.lastHeartbeat;
        if (sinceLastHeartbeat > this.config.heartbeatInterval * 2) {
          console.warn('[LiveChannel] Missed heartbeats, reconnecting...');
          this.scheduleReconnect();
        }
      }
    }, this.config.heartbeatInterval);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private stopPolling(): void {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
  }

  // ============================================================================
  // Private: Reconnection
  // ============================================================================

  private scheduleReconnect(): void {
    // Prevent stacking multiple reconnect timers
    if (this.reconnectTimer) {
      return;
    }

    if (this.state.reconnectAttempts >= this.config.maxReconnectAttempts) {
      console.error('[LiveChannel] Max reconnect attempts reached');
      this.setConnectionState('error');
      return;
    }

    this.setConnectionState('reconnecting');
    this.state.reconnectAttempts++;

    // Exponential backoff
    const delay = Math.min(
      this.config.reconnectBaseDelay * Math.pow(2, this.state.reconnectAttempts - 1),
      this.config.maxReconnectDelay
    );

    if (import.meta.env.DEV) {
      console.log(`[LiveChannel] Reconnecting in ${delay}ms (attempt ${this.state.reconnectAttempts})`);
    }

    this.reconnectTimer = window.setTimeout(() => {
      this.connect();
    }, delay);
  }

  private stopReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  // ============================================================================
  // Private: Helpers
  // ============================================================================

  private setConnectionState(state: ConnectionState): void {
    if (this.state.connectionState !== state) {
      this.state.connectionState = state;
      for (const handler of this.stateHandlers) {
        try {
          handler(state);
        } catch (e) {
          console.error('[LiveChannel] State handler error:', e);
        }
      }
    }
  }

  private handleEvent(event: LiveEvent): void {
    // Update heartbeat time for heartbeat events
    if (event.type === 'heartbeat') {
      this.state.lastHeartbeat = Date.now();
      return;
    }

    // Check if subscribed to this module
    if (event.module && !this.state.subscribedModules.has(event.module) && 
        !this.state.subscribedModules.has('system' as ModuleType)) {
      return;
    }

    // Call specific handlers
    const specificHandlers = this.eventHandlers.get(event.type);
    if (specificHandlers) {
      for (const handler of specificHandlers) {
        try {
          handler(event);
        } catch (e) {
          console.error('[LiveChannel] Event handler error:', e);
        }
      }
    }

    // Call wildcard handlers
    const wildcardHandlers = this.eventHandlers.get('*');
    if (wildcardHandlers) {
      for (const handler of wildcardHandlers) {
        try {
          handler(event);
        } catch (e) {
          console.error('[LiveChannel] Wildcard handler error:', e);
        }
      }
    }
  }

  private sendSubscription(action: 'subscribe' | 'unsubscribe', module: ModuleType): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        action,
        module,
        ts: new Date().toISOString(),
      }));
    }
  }
}

// ==============================================================================
// Singleton Instance
// ==============================================================================

let channelInstance: LiveChannel | null = null;

export function getLiveChannel(config?: ChannelConfig): LiveChannel {
  if (!channelInstance) {
    channelInstance = new LiveChannel(config);
  }
  return channelInstance;
}

export function resetLiveChannel(): void {
  if (channelInstance) {
    channelInstance.disconnect();
    channelInstance = null;
  }
}
