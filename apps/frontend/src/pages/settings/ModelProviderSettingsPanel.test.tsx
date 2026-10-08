import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ModelProviderSettingsPanel from './ModelProviderSettingsPanel';

const apiMocks = vi.hoisted(() => ({
  catalog: vi.fn(), list: vi.fn(), save: vi.fn(), test: vi.fn(), models: vi.fn(),
  login: vi.fn(), loginStatus: vi.fn(), loginInput: vi.fn(), cancelLogin: vi.fn(), disconnect: vi.fn(),
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
  documentationUrl: 'https://example.test/docs', requiresApiKey: true, authMethods: ['api_key', 'oauth'], oauthLabel: '登录 OpenAI 账号', modelCount: 1, engine: 'pi-ai',
};

const savedConnection = {
  providerCode: 'openai', displayName: 'OpenAI', baseUrl: preset.defaultBaseUrl,
  defaultModel: preset.defaultModel, enabled: true, hasApiKey: true,
  apiKeyMask: '••••••••••••', updatedAt: null, lastTestAt: null,
  lastTestStatus: null, lastTestMessage: null,
  requiresApiKey: true, authType: 'api_key' as const, hasCredential: true, apiProtocol: 'auto',
};

describe('ModelProviderSettingsPanel', () => {
  afterEach(() => vi.restoreAllMocks());
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.catalog.mockResolvedValue({ providers: [preset] });
    apiMocks.models.mockResolvedValue({ models: [{ id: 'gpt-5-mini', name: 'GPT Mini', api: 'openai-responses', input: ['text', 'image'], reasoning: true, contextWindow: 128000, maxTokens: 4096 }], total: 1 });
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

  it('已启用但尚未验证模型时明确显示待测试', async () => {
    render(<ModelProviderSettingsPanel />);

    expect(await screen.findByText('待测试')).toHaveAttribute('data-status', 'testing');
  });

  it('仅将启用且完成真实模型测试的服务商标为已就绪', async () => {
    apiMocks.list.mockResolvedValue({ providers: [{
      ...savedConnection, lastTestStatus: 'passed', lastTestMessage: '模型调用正常',
    }] });
    render(<ModelProviderSettingsPanel />);

    expect(await screen.findByText('已就绪')).toHaveAttribute('data-status', 'ready');
  });
  it('搜索供应商并显示 Pi 模型能力', async () => {
    apiMocks.catalog.mockResolvedValue({ providers: [preset, { ...preset, providerCode: 'deepseek', displayName: 'DeepSeek', authMethods: ['api_key'] }] });
    render(<ModelProviderSettingsPanel />);
    await screen.findByLabelText('搜索供应商');
    fireEvent.change(screen.getByLabelText('搜索供应商'), { target: { value: 'DeepSeek' } });
    expect(screen.queryByRole('button', { name: /OpenAI.*待测试/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /DeepSeek.*未配置/ }));
    expect(await screen.findByText('支持推理')).toBeInTheDocument();
    expect(screen.getByText('文本与图像')).toBeInTheDocument();
    expect(apiMocks.models).toHaveBeenCalledWith('deepseek', '', 0);
  });

  it('模型修改后先保存配置再允许验证', async () => {
    render(<ModelProviderSettingsPanel />);
    const input = await screen.findByLabelText('默认模型 ID');
    fireEvent.change(input, { target: { value: 'new-model' } });
    expect(screen.getByRole('button', { name: '验证模型' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '加密保存' }));
    await waitFor(() => expect(apiMocks.save).toHaveBeenCalledWith('openai', expect.objectContaining({ defaultModel: 'new-model', apiProtocol: 'auto' })));
  });

  it('只向支持的供应商显示账号登录并支持取消授权', async () => {
    const consoleError = vi.spyOn(console, 'error');
    const login = { loginId: 'login-1', providerCode: 'openai', status: 'waiting', expiresAt: Date.now() / 1000 + 300,
      events: [{ type: 'device_code', verificationUri: 'https://example.test/device', userCode: 'ABC123' }], prompt: null, provider: null };
    apiMocks.login.mockResolvedValue(login);
    apiMocks.cancelLogin.mockResolvedValue({ ...login, status: 'cancelled' });
    apiMocks.loginStatus.mockResolvedValue(login);
    render(<ModelProviderSettingsPanel />);
    fireEvent.click(await screen.findByRole('radio', { name: '账号登录' }));
    fireEvent.click(screen.getByRole('button', { name: '登录 OpenAI 账号' }));
    expect(await screen.findByText('ABC123')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /打开设备授权页面/ })).toHaveAttribute('href', 'https://example.test/device');
    fireEvent.click(screen.getByRole('button', { name: '取消登录' }));
    await waitFor(() => expect(apiMocks.cancelLogin).toHaveBeenCalledWith('login-1'));
    expect(apiMocks.login.mock.calls[0][1].apiKey).toBeUndefined();
    expect(consoleError.mock.calls.flat().join(' ')).not.toMatch(/same key|unique.*key/i);
  });

  it('目录加载失败时提供重试入口', async () => {
    apiMocks.catalog.mockRejectedValueOnce(new Error('Pi 未安装'));
    render(<ModelProviderSettingsPanel />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Pi 未安装');
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
    expect(await screen.findByLabelText('搜索供应商')).toBeInTheDocument();
  });

});
