import { beforeEach, describe, expect, it } from 'vitest';
import { useMemo } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider, initializeTheme, useTheme } from './ThemeContext';
import { THEME_STORAGE_KEY } from '../theme/storage';

function ThemeReader() {
  const { theme, setTheme, toggleTheme } = useTheme();
  const paletteTheme = useMemo(() => document.documentElement.dataset.theme, [theme]);
  return <>
    <span data-testid="theme-value">{theme}</span>
    <span data-testid="palette-theme">{paletteTheme ?? 'unset'}</span>
    <button type="button" onClick={() => setTheme('polar-lab')}>Polar</button>
    <button type="button" onClick={toggleTheme}>Toggle</button>
  </>;
}

describe('ThemeContext', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  it('restores the palette before the first application render', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'polar-lab');
    initializeTheme();
    render(<ThemeProvider><ThemeReader /></ThemeProvider>);
    expect(screen.getByTestId('palette-theme')).toHaveTextContent('polar-lab');
  });

  it('updates CSS before chart consumers render with the next theme', async () => {
    const user = userEvent.setup();
    render(<ThemeProvider><ThemeReader /></ThemeProvider>);
    await user.click(screen.getByRole('button', { name: 'Polar' }));
    expect(screen.getByTestId('palette-theme')).toHaveTextContent('polar-lab');
    await user.click(screen.getByRole('button', { name: 'Toggle' }));
    expect(screen.getByTestId('palette-theme')).toHaveTextContent('redline-quant');
  });

  it('uses black-red by default', () => {
    render(<ThemeProvider><ThemeReader /></ThemeProvider>);
    expect(document.documentElement).toHaveAttribute('data-theme', 'redline-quant');
  });

  it('restores polar and removes stale appearance attributes', () => {
    localStorage.setItem('fqp.appearance.settings', JSON.stringify({ theme: 'polar-lab', density: 'terminal', sidebarMode: 'icons' }));
    document.documentElement.dataset.density = 'terminal';
    document.documentElement.dataset.sidebarMode = 'icons';
    render(<ThemeProvider><ThemeReader /></ThemeProvider>);
    expect(document.documentElement).toHaveAttribute('data-theme', 'polar-lab');
    expect(document.documentElement).not.toHaveAttribute('data-density');
    expect(document.documentElement).not.toHaveAttribute('data-sidebar-mode');
    expect(localStorage.getItem('fqp.appearance.settings')).toBeNull();
  });

  it('switches immediately, persists, and survives a remount', async () => {
    const user = userEvent.setup();
    const view = render(<ThemeProvider><ThemeReader /></ThemeProvider>);
    await user.click(screen.getByRole('button', { name: 'Polar' }));
    expect(document.documentElement).toHaveAttribute('data-theme', 'polar-lab');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('polar-lab');
    view.unmount();
    render(<ThemeProvider><ThemeReader /></ThemeProvider>);
    expect(screen.getByTestId('theme-value')).toHaveTextContent('polar-lab');
    await user.click(screen.getByRole('button', { name: 'Toggle' }));
    expect(document.documentElement).toHaveAttribute('data-theme', 'redline-quant');
  });
});
