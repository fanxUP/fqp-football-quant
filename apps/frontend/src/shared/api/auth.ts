/** Auth API client — login, logout, session check. */

const BASE = '/api/auth';

export interface LoginResponse {
  ok: boolean;
  user: string;
}

export interface MeResponse {
  user: string;
}

export interface DeploymentVersionResponse {
  releaseId: string;
}

export class DeploymentChangedError extends Error {
  constructor() {
    super('服务器已更新');
    this.name = 'DeploymentChangedError';
  }
}

export async function getDeploymentVersion(): Promise<DeploymentVersionResponse> {
  const res = await fetch(`${BASE}/release`, { cache: 'no-store' });
  if (!res.ok) throw new Error('无法读取服务器版本');
  const body = await res.json();
  if (typeof body?.releaseId !== 'string' || !body.releaseId) {
    throw new Error('服务器版本响应无效');
  }
  return { releaseId: body.releaseId };
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
  if (res.status === 409) {
    const body = await res.json().catch(() => ({}));
    if (body.code === 'deployment_changed') throw new DeploymentChangedError();
  }
  if (res.status === 401) return null;
  if (!res.ok) throw new Error('无法验证登录状态');
  return res.json();
}
