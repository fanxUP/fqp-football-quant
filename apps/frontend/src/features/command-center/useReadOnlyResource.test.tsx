import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import useReadOnlyResource from './useReadOnlyResource';

describe('query-scoped resource reads', () => {
  it('loads a new query immediately and ignores a slower old response', async () => {
    let resolveOld!: (value: string) => void;
    const oldRead = new Promise<string>(resolve => { resolveOld = resolve; });
    const fetcher = vi.fn((key: string) => key === 'old' ? oldRead : Promise.resolve('new result'));
    const view = renderHook(({ query }) => useReadOnlyResource(() => fetcher(query), 30_000, false, query), { initialProps: { query: 'old' } });
    view.rerender({ query: 'new' });
    await waitFor(() => expect(view.result.current.data).toBe('new result'));
    await act(async () => { resolveOld('old result'); await oldRead; });
    expect(view.result.current.data).toBe('new result');
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('retains data on a same-query failure but clears it on a different-query failure', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce('current matches').mockRejectedValue(new Error('失败'));
    const view = renderHook(({ query }) => useReadOnlyResource(fetcher, 30_000, false, query), { initialProps: { query: 'current' } });
    await waitFor(() => expect(view.result.current.data).toBe('current matches'));
    await act(async () => { await view.result.current.refresh(); });
    expect(view.result.current.data).toBe('current matches');
    view.rerender({ query: 'history' });
    await waitFor(() => expect(view.result.current.error).toBe('失败'));
    expect(view.result.current.data).toBeNull();
  });
});
