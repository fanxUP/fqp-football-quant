import { useCallback, useEffect, useRef, useState } from 'react';
import useBackgroundRefresh from '../../shared/hooks/useBackgroundRefresh';
export interface ReadOnlyResource<T> { data: T | null; error: string | null; loading: boolean; receivedAt: number | null }

/** One polling owner per resource. Consumers retain evidence from the last successful GET. */
export default function useReadOnlyResource<T>(fetcher: () => Promise<T>, interval = 30_000) {
  const [state, setState] = useState<ReadOnlyResource<T>>({ data: null, error: null, loading: true, receivedAt: null });
  const mounted = useRef(false);
  const initialized = useRef(false);
  const pending = useRef(false);
  const nextAttempt = useRef(0);
  const failureCount = useRef(0);
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;
  const refresh = useCallback(async (manual = false) => {
    if (pending.current || (!manual && Date.now() < nextAttempt.current)) return;
    pending.current = true;
    try {
      const data = await fetchRef.current();
      if (mounted.current) {
        failureCount.current = 0; nextAttempt.current = 0;
        setState({ data, error: null, loading: false, receivedAt: Date.now() });
      }
    } catch (error) {
      if (mounted.current) {
        failureCount.current += 1;
        nextAttempt.current = Date.now() + Math.min(60_000, interval * 2 ** (failureCount.current - 1));
        setState(previous => ({ ...previous, loading: false, error: error instanceof Error ? error.message : '请求失败' }));
      }
    } finally { pending.current = false; }
  }, [interval]);
  useEffect(() => {
    mounted.current = true;
    if (!initialized.current) { initialized.current = true; void refresh(); }
    return () => { mounted.current = false; };
  }, [refresh]);
  useBackgroundRefresh(refresh, interval);
  return { ...state, refresh: () => refresh(true) };
}
