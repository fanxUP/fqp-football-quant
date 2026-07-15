import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider } from '../app/ThemeContext';
import { APPEARANCE_STORAGE_KEY } from '../theme/storage';
import SettingsPage from './SettingsPage';

describe('SettingsPage appearance settings', () => {
  beforeEach(() => localStorage.clear());

  it('groups all documented themes and disables themes that are still planned', () => {
    render(<ThemeProvider><SettingsPage /></ThemeProvider>);

    expect(screen.getByRole('heading', { name: '专业量化' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '足球赛事' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '科技未来' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '个性主题' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /黑红量化/ })).toBeEnabled();
    expect(screen.getByRole('button', { name: /赛博朋克/ })).toBeDisabled();
  });

  it('previews a theme and only persists it after applying settings', async () => {
    const user = userEvent.setup();
    render(<ThemeProvider><SettingsPage /></ThemeProvider>);

    await user.click(screen.getByRole('button', { name: /黑金量化终端/ }));
    expect(document.documentElement).toHaveAttribute('data-theme', 'black-gold-terminal');
    expect(JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY) ?? '{}').theme).toBe('redline-quant');

    await user.click(screen.getByRole('button', { name: '应用外观设置' }));
    expect(JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY) ?? '{}').theme).toBe('black-gold-terminal');
  });

  it('updates density and radius through accessible controls', async () => {
    const user = userEvent.setup();
    render(<ThemeProvider><SettingsPage /></ThemeProvider>);

    await user.click(screen.getByRole('radio', { name: '专业终端' }));
    await user.click(screen.getByRole('radio', { name: '直角专业' }));

    expect(document.documentElement).toHaveAttribute('data-density', 'terminal');
    expect(document.documentElement).toHaveAttribute('data-radius', 'square');
  });

  it('previews the selected theme with its recommended component defaults', async () => {
    const user = userEvent.setup();
    render(<ThemeProvider><SettingsPage /></ThemeProvider>);

    await user.click(screen.getByRole('button', { name: /极地数据实验室/ }));

    expect(document.documentElement).toHaveAttribute('data-theme', 'polar-lab');
    expect(document.documentElement).toHaveAttribute('data-density', 'standard');
    expect(document.documentElement).toHaveAttribute('data-card-style', 'elevated');
  });
});
