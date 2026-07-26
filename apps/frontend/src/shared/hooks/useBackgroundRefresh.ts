import { useEffect, useRef } from 'react';

const DEFAULT_REFRESH_INTERVAL_MS = 30_000;

/** Refresh live data without replacing the page's initial loading state. */
export default function useBackgroundRefresh(
  refresh: () => void | Promise<void>,
  intervalMs = DEFAULT_REFRESH_INTERVAL_MS,
) {
  const refreshRef = useRef(refresh);
  const refreshingRef = useRef(false);

  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  useEffect(() => {
    const run = async () => {
      if (refreshingRef.current) return;
      refreshingRef.current = true;
      try {
        await refreshRef.current();
      } finally {
        refreshingRef.current = false;
      }
    };
    const trigger = () => { void run().catch(() => undefined); };
    const timer = window.setInterval(trigger, intervalMs);
    window.addEventListener('focus', trigger);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', trigger);
    };
  }, [intervalMs]);
}
