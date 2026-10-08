import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AgentModelBindings from './AgentModelBindings';

const apiMocks = vi.hoisted(() => ({ bindings: vi.fn(), saveBinding: vi.fn() }));

vi.mock('../../core/apiClient', () => ({
  api: { modelProviders: apiMocks },
}));

vi.mock('../../shared/components/Toast', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

vi.mock('./ModelInvocationAudit', () => ({ default: () => null }));

const provider = {
  providerCode: 'deepseek', displayName: 'DeepSeek', baseUrl: 'https://api.deepseek.com',
  defaultModel: 'deepseek-v4-pro', enabled: true, hasApiKey: true,
  apiKeyMask: '••••••••••••', updatedAt: null, lastTestAt: '2026-08-12T00:00:00Z',
  lastTestStatus: 'passed' as const, lastTestMessage: '调用正常',
  requiresApiKey: true, authType: 'api_key' as const, hasCredential: true, apiProtocol: 'auto',
};

describe('AgentModelBindings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.bindings.mockResolvedValue({ bindings: [{
      agentCode: 'review_agent', agentName: '复盘 Agent', providerCode: 'deepseek',
      providerName: 'DeepSeek', model: 'old-model', enabled: true,
      providerEnabled: true, providerTestStatus: null, updatedAt: null,
    }] });
  });

  it('服务商刚测试通过后立即同步 Agent 就绪状态与最新模型，无需刷新页面', async () => {
    render(<AgentModelBindings providers={[provider]} />);

    expect(await screen.findByRole('option', { name: /复盘 Agent.*deepseek-v4-pro/ })).toBeInTheDocument();
    expect(screen.queryByText(/暂无可试运行/)).not.toBeInTheDocument();
  });
});
