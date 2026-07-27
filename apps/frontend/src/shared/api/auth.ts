/** Auth API client — login, logout, session check. */

const BASE = '/api/auth';

export interface LoginResponse {
  ok: boolean;
  user: string;
}

export interface MeResponse {
  user: string;
}

export async function login(password: string): Promise<LoginResponse> {
  const res = await fetch(`${BASE}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: '登录失败' }));
    throw new Error(body.detail || '登录失败');
  }
  return res.json();
}

export async function logout(): Promise<void> {
  await fetch(`${BASE}/logout`, { method: 'POST' });
}

export async function getMe(): Promise<MeResponse | null> {
  const res = await fetch(`${BASE}/me`);
  if (!res.ok) return null;
  return res.json();
}
