import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ModulesPage from './ModulesPage';

const { mockModules, mockSetModuleStatus } = vi.hoisted(() => ({
  mockModules: vi.fn(),
  mockSetModuleStatus: vi.fn(),
}));

vi.mock('../core/apiClient', () => ({
  api: {
    ui: {
      modules: mockModules,
      setModuleStatus: mockSetModuleStatus,
    },
  },
}));

describe('ModulesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockModules.mockResolvedValue({
      total: 1,
      categories: ['strategy_lab'],
      modules: [
        {
          moduleCode: 'pool_lottery_module',
          moduleName: '传统足彩',
          category: 'strategy_lab',
          required: false,
          safeDisable: true,
          status: 'active',
          disabled: false,
          dependsOn: ['recommendation_core'],
          panels: ['pool_lottery'],
        },
      ],
    });
    mockSetModuleStatus.mockResolvedValue({
      disabledModules: ['pool_lottery_module'],
      module: {
        moduleCode: 'pool_lottery_module',
        moduleName: '传统足彩',
        category: 'strategy_lab',
        required: false,
        safeDisable: true,
        status: 'disabled',
        disabled: true,
        dependsOn: ['recommendation_core'],
        panels: ['pool_lottery'],
      },
    });
  });

  it('updates module status through the runtime API', async () => {
    const user = userEvent.setup();
    render(<ModulesPage />);

    await screen.findByText('传统足彩');
    await user.click(screen.getByText('传统足彩'));
    await user.click(screen.getByText('禁用模块'));

    await waitFor(() => {
      expect(mockSetModuleStatus).toHaveBeenCalledWith('pool_lottery_module', {
        disabled: true,
      });
    });
    expect(localStorage.getItem('fqp-settings')).not.toContain('pool_lottery_module');
  });
});
