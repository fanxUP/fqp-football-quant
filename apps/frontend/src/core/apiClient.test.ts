import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './apiClient';

describe('api client GET request coalescing', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('shares an in-flight GET request and allows a fresh request after completion', async () => {
    let resolveFetch: ((response: unknown) => void) | undefined;
    const fetchMock = vi.fn(() => new Promise((resolve) => {
      resolveFetch = resolve;
    }));
    vi.stubGlobal('fetch', fetchMock);

    const first = api.health();
    const second = api.health();

    expect(fetchMock).toHaveBeenCalledTimes(1);

    resolveFetch?.({
      ok: true,
      json: () => Promise.resolve({ status: 'ok' }),
    });
    await expect(Promise.all([first, second])).resolves.toEqual([
      { status: 'ok' },
      { status: 'ok' },
    ]);

    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ status: 'ok' }),
    });
    await api.health();

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('extracts FastAPI detail instead of displaying raw JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        text: () => Promise.resolve('{"detail":"模型预测待补齐"}'),
      }),
    );

    await expect(api.pool.analyze()).rejects.toEqual(
      expect.objectContaining({ status: 409, message: '模型预测待补齐' }),
    );
  });

  it('uses the stable task review-history subresource and coalesces duplicate reads', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ events: [{ id: 1, action: 'confirmed' }] }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const first = api.agentWorkspace.reviewHistory(24);
    const second = api.agentWorkspace.reviewHistory(24);

    await expect(Promise.all([first, second])).resolves.toEqual([
      { events: [{ id: 1, action: 'confirmed' }] },
      { events: [{ id: 1, action: 'confirmed' }] },
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/agent-workspace/tasks/24/reviews',
      expect.objectContaining({ headers: expect.objectContaining({ 'Content-Type': 'application/json' }) }),
    );
  });

  it('keeps model interpretation calls open beyond the standard request timeout', async () => {
    vi.useFakeTimers();
    let signal: AbortSignal | undefined;
    vi.stubGlobal('fetch', vi.fn((_path: string, init?: RequestInit) => {
      signal = init?.signal as AbortSignal;
      return new Promise(() => undefined);
    }));

    void api.agentInterpretations.preMatch(42);
    await vi.advanceTimersByTimeAsync(15_000);

    expect(signal?.aborted).toBe(false);
  });

  it('reads an automatic report archive by its fixed business source', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ task: { id: 21, response: '仅供人工核验' } }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.reportAutomation.archive('post_monthly', '2026-08')).resolves.toEqual({
      task: { id: 21, response: '仅供人工核验' },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/report-automation/archive/post_monthly/2026-08',
      expect.objectContaining({ headers: expect.objectContaining({ 'Content-Type': 'application/json' }) }),
    );
  });
});
