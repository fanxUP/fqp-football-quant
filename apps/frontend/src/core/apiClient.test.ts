import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './apiClient';

describe('api client GET request coalescing', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('reads only the exact dashboard prediction count and coalesces concurrent reads', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ total: 42 }) });
    vi.stubGlobal('fetch', fetchMock);
    await expect(Promise.all([api.dashboard.predictionCount(), api.dashboard.predictionCount()])).resolves.toEqual([{ total: 42 }, { total: 42 }]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/dashboard/prediction-count');
  });

  it('prediction summary requests use summary-only mode without fetching recent rows', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ predictions: [], total: null, summary: null }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.predictions({ limit: 200, include_summary: false });
    await api.predictions({ summary_only: true });
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(['/api/predictions?limit=200&include_summary=false', '/api/predictions?summary_only=true']);
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

  it('keeps full detail compatible and coalesces only identical section reads', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal('fetch', fetchMock);
    await Promise.all([
      api.matches.detail(101), api.matches.detailSection(101, 'core'),
      api.matches.detailSection(101, 'core'), api.matches.detailSection(101, 'roster'),
    ]);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/matches/101/detail', '/api/matches/101/detail?section=core', '/api/matches/101/detail?section=roster',
    ]);
  });

  it('bounds coalesced agent reads, releases timed-out requests and allows a fresh retry', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_path: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    }));
    vi.stubGlobal('fetch', fetchMock);
    const reads = Promise.allSettled([api.agentOperations.tasks('failed'), api.agentOperations.tasks('failed')]);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(await reads).toEqual([
      { status: 'rejected', reason: expect.objectContaining({ status: 0, message: expect.stringContaining('超时') }) },
      { status: 'rejected', reason: expect.objectContaining({ status: 0, message: expect.stringContaining('超时') }) },
    ]);
    fetchMock.mockResolvedValueOnce(new Response('{"tasks":[]}'));
    await expect(api.agentOperations.tasks('failed')).resolves.toEqual({ tasks: [] });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('keeps the timeout active while reading the response body', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn(async (_path: string, init?: RequestInit) => ({
      ok: true,
      json: () => new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
      }),
    })));
    let result: unknown;
    const read = api.agentOperations.staleJobs().catch(reason => { result = reason; });
    await vi.advanceTimersByTimeAsync(15_000);
    expect(result).toEqual(expect.objectContaining({ status: 0, message: expect.stringContaining('超时') }));
    await read;
  });
});
