import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SettingsPage from './SettingsPage';

describe('SettingsPage', () => {
  beforeEach(() => localStorage.clear());

  it('contains only business and account settings without appearance controls', () => {
    render(<SettingsPage />);
    expect(screen.getByRole('heading', { name: '系统设置' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '本地业务设置' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '修改密码' })).toBeInTheDocument();
    expect(screen.queryByText(/外观与显示|信息密度|页面圆角|动效等级|卡片样式|侧边栏模式|主题背景/)).not.toBeInTheDocument();
  });

  it('still persists business settings without touching the selected theme', async () => {
    const user = userEvent.setup();
    localStorage.setItem('fqp-theme', 'polar-lab');
    render(<SettingsPage />);
    const budget = screen.getByLabelText('每日预算（元）');
    await user.clear(budget);
    await user.type(budget, '250');
    expect(JSON.parse(localStorage.getItem('fqp-settings') ?? '{}').dailyBudget).toBe(250);
    expect(localStorage.getItem('fqp-theme')).toBe('polar-lab');
  });
});
