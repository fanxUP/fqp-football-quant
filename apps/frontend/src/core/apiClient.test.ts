import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './apiClient';

describe('api client GET request coalescing', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
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
});
