import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReadOnlyResource } from '../features/command-center/useReadOnlyResource';

/** Historical evidence and settings have one manual reader; writes use the same pending guard. */
export default function useManualEvidence<T>(fetcher: () => Promise<T>) {
  const [state, setState] = useState<ReadOnlyResource<T>>({ data: null, error: null, loading: true, receivedAt: null });
  const mounted = useRef(false);
  const started = useRef(false);
  const pending = useRef(false);
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;
  const refresh = useCallback(async () => {
    if (pending.current) return;
    pending.current = true;
    setState(previous => ({ ...previous, loading: true }));
    try {
      const data = await fetchRef.current();
      if (mounted.current) setState({ data, error: null, loading: false, receivedAt: Date.now() });
    } catch (reason) {
      if (mounted.current) setState(previous => ({ ...previous, error: reason instanceof Error ? reason.message : '读取失败', loading: false }));
    } finally { pending.current = false; }
  }, []);
  useEffect(() => {
    mounted.current = true;
    if (!started.current) { started.current = true; void refresh(); }
    return () => { mounted.current = false; };
  }, [refresh]);
  const update = useCallback((transform: (value: T) => T) => {
    if (mounted.current) setState(previous => previous.data === null ? previous : ({ ...previous, data: transform(previous.data) }));
  }, []);
  return { ...state, refresh, update, isReading: () => pending.current };
}
