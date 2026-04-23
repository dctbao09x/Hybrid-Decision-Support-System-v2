import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { adminLogout } from '../../services/adminAuthApi';

const IDLE_TIMEOUT_MS = Number(import.meta.env.VITE_ADMIN_IDLE_TIMEOUT_MS || 15 * 60 * 1000);

export function useIdleLogout(enabled: boolean) {
  const navigate = useNavigate();

  useEffect(() => {
    if (!enabled) return;

    let timeout = window.setTimeout(async () => {
      await adminLogout();
      navigate('/admin/login', { replace: true });
    }, IDLE_TIMEOUT_MS);

    const reset = () => {
      window.clearTimeout(timeout);
      timeout = window.setTimeout(async () => {
        await adminLogout();
        navigate('/admin/login', { replace: true });
      }, IDLE_TIMEOUT_MS);
    };

    const events = ['mousemove', 'keydown', 'click', 'scroll'];
    events.forEach((eventName) => window.addEventListener(eventName, reset));

    return () => {
      window.clearTimeout(timeout);
      events.forEach((eventName) => window.removeEventListener(eventName, reset));
    };
  }, [enabled, navigate]);
}
