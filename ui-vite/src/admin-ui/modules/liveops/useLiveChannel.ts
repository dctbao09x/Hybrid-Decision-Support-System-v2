/**
 * Live Dashboard Hook
 * ===================
 * 
 * React hook for connecting to the Live Channel and managing real-time data.
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { getLiveChannel, LiveChannel, LiveEvent, ModuleType, ConnectionState } from '../../interface/liveChannel';
import { getAdminSession } from '../../../utils/adminSession';

export interface UseLiveChannelOptions {
  modules?: ModuleType[];
  autoConnect?: boolean;
}

export interface LiveChannelHookState {
  connectionState: ConnectionState;
  isConnected: boolean;
  lastEvent: LiveEvent | null;
  events: LiveEvent[];
  error: string | null;
}

export function useLiveChannel(options: UseLiveChannelOptions = {}) {
  const { modules = ['system'], autoConnect = true } = options;
  
  const channelRef = useRef<LiveChannel | null>(null);
  const [state, setState] = useState<LiveChannelHookState>({
    connectionState: 'disconnected',
    isConnected: false,
    lastEvent: null,
    events: [],
    error: null,
  });
  
  const maxEvents = 100;

  // Initialize channel
  useEffect(() => {
    channelRef.current = getLiveChannel();
    
    // Subscribe to state changes
    const unsubState = channelRef.current.onStateChange((connectionState) => {
      setState(prev => ({
        ...prev,
        connectionState,
        isConnected: connectionState === 'connected',
        error: connectionState === 'error' ? 'Connection failed' : null,
      }));
    });
    
    // Subscribe to all events
    const unsubEvents = channelRef.current.onEvent('*', (event) => {
      setState(prev => ({
        ...prev,
        lastEvent: event,
        events: [...prev.events.slice(-(maxEvents - 1)), event],
      }));
    });
    
    // Auto-connect
    if (autoConnect) {
      const session = getAdminSession();
      if (session.accessToken) {
        channelRef.current.connect().catch(error => {
          setState(prev => ({
            ...prev,
            error: error.message,
          }));
        });
      }
    }
    
    // Subscribe to modules
    for (const module of modules) {
      channelRef.current.subscribe(module);
    }
    
    return () => {
      unsubState();
      unsubEvents();
    };
  }, [autoConnect, modules.join(',')]);
  
  // Connect function
  const connect = useCallback(async () => {
    if (channelRef.current) {
      try {
        await channelRef.current.connect();
        setState(prev => ({ ...prev, error: null }));
      } catch (error) {
        setState(prev => ({
          ...prev,
          error: error instanceof Error ? error.message : 'Connection failed',
        }));
      }
    }
  }, []);
  
  // Disconnect function
  const disconnect = useCallback(() => {
    if (channelRef.current) {
      channelRef.current.disconnect();
    }
  }, []);
  
  // Reconnect function
  const reconnect = useCallback(() => {
    if (channelRef.current) {
      channelRef.current.reconnect();
    }
  }, []);
  
  // Subscribe to module
  const subscribe = useCallback((module: ModuleType) => {
    if (channelRef.current) {
      channelRef.current.subscribe(module);
    }
  }, []);
  
  // Unsubscribe from module
  const unsubscribe = useCallback((module: ModuleType) => {
    if (channelRef.current) {
      channelRef.current.unsubscribe(module);
    }
  }, []);
  
  // Send command
  const sendCommand = useCallback((command: string, payload: unknown) => {
    if (channelRef.current) {
      channelRef.current.sendCommand(command, payload);
    }
  }, []);
  
  // Clear events
  const clearEvents = useCallback(() => {
    setState(prev => ({ ...prev, events: [], lastEvent: null }));
  }, []);
  
  return {
    ...state,
    connect,
    disconnect,
    reconnect,
    subscribe,
    unsubscribe,
    sendCommand,
    clearEvents,
    channel: channelRef.current,
  };
}

// Specialized hooks for specific modules
export function useCrawlerChannel() {
  return useLiveChannel({ modules: ['crawler', 'system'] });
}

export function useOpsChannel() {
  return useLiveChannel({ modules: ['ops', 'system'] });
}

export function useMLOpsChannel() {
  return useLiveChannel({ modules: ['mlops', 'system'] });
}

export function useKBChannel() {
  return useLiveChannel({ modules: ['kb', 'system'] });
}

export function useAllModulesChannel() {
  return useLiveChannel({ 
    modules: ['system', 'crawler', 'ops', 'mlops', 'kb', 'governance', 'pipeline'] 
  });
}
