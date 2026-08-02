import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ModelProviderSettingsPanel from './ModelProviderSettingsPanel';

const apiMocks = vi.hoisted(() => ({
  catalog: vi.fn(), list: vi.fn(), save: vi.fn(), test: vi.fn(),
}));

vi.mock('../../core/apiClient', () => ({
  api: { modelProviders: apiMocks },
}));

vi.mock('../../shared/components/Toast', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

vi.mock('./AgentModelBindings', () => ({ default: () => null }));

const preset = {
  providerCode: 'openai', displayName: 'OpenAI', protocol: 'openai' as const,
  defaultBaseUrl: 'https://api.openai.com/v1', defaultModel: 'gpt-5-mini',
  recommendedModels: ['gpt-5-mini'], capabilities: ['analysis'],
  documentationUrl: 'https://example.test/docs', requiresApiKey: true,
};

const savedConnection = {
  providerCode: 'openai', displayName: 'OpenAI', baseUrl: preset.defaultBaseUrl,
  defaultModel: preset.defaultModel, enabled: true, hasApiKey: true,
  apiKeyMask: '••••••••••••', updatedAt: null, lastTestAt: null,
  lastTestStatus: null, lastTestMessage: null,
};

describe('ModelProviderSettingsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.catalog.mockResolvedValue({ providers: [preset] });
    apiMocks.list.mockResolvedValue({ providers: [savedConnection] });
    apiMocks.save.mockResolvedValue({ provider: savedConnection });
  });

  it('保留服务端返回的密钥掩码，并在未编辑时不将掩码当作新密钥提交', async () => {
    render(<ModelProviderSettingsPanel />);

    const keyInput = await screen.findByLabelText(/API 密钥/);
    expect(keyInput).toHaveValue('••••••••••••');

    fireEvent.click(screen.getByRole('button', { name: '加密保存' }));

    await waitFor(() => expect(apiMocks.save).toHaveBeenCalledWith('openai', expect.objectContaining({
      apiKey: undefined,
    })));
  });

  it('新服务商默认允许通过测试后的智能代理使用', async () => {
    apiMocks.list.mockResolvedValue({ providers: [] });
    render(<ModelProviderSettingsPanel />);

    expect(await screen.findByRole('checkbox', { name: /启用此服务商/ })).toBeChecked();
  });
});
