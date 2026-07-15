import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider, useTheme } from './ThemeContext';
import { APPEARANCE_STORAGE_KEY } from '../theme/storage';

function ThemeReader() {
  const {
    appearance,
    setTheme,
    updateAppearance,
    previewAppearance,
    commitAppearance,
    cancelPreview,
    toggleTheme,
  } = useTheme();
  return (
    <div>
      <span data-testid="theme-value">{appearance.theme}</span>
      <button type="button" onClick={() => setTheme('black-gold-terminal')}>Black gold</button>
      <button type="button" onClick={() => updateAppearance({ density: 'terminal', radius: 'square' })}>Terminal density</button>
      <button type="button" onClick={() => previewAppearance({ ...appearance, theme: 'deep-navy' })}>Preview navy</button>
      <button type="button" onClick={commitAppearance}>Apply preview</button>
      <button type="button" onClick={cancelPreview}>Cancel preview</button>
      <button type="button" onClick={toggleTheme}>Toggle</button>
    </div>
  );
}

describe('ThemeContext', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  it('uses the redline quant appearance by default', () => {
    render(<ThemeProvider><ThemeReader /></ThemeProvider>);

    expect(screen.getByTestId('theme-value')).toHaveTextContent('redline-quant');
    expect(document.documentElement).toHaveAttribute('data-theme', 'redline-quant');
    expect(document.documentElement).toHaveAttribute('data-density', 'compact');
  });

  it('restores a complete appearance from localStorage', () => {
    localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify({
      theme: 'polar-lab',
      density: 'comfortable',
      motion: 'off',
      radius: 'soft',
    }));

    render(<ThemeProvider><ThemeReader /></ThemeProvider>);

    expect(screen.getByTestId('theme-value')).toHaveTextContent('polar-lab');
    expect(document.documentElement).toHaveAttribute('data-motion', 'off');
    expect(document.documentElement).toHaveAttribute('data-radius', 'soft');
  });

  it('updates DOM attributes and persists changes immediately', async () => {
    const user = userEvent.setup();
    render(<ThemeProvider><ThemeReader /></ThemeProvider>);

    await user.click(screen.getByRole('button', { name: 'Black gold' }));
    await user.click(screen.getByRole('button', { name: 'Terminal density' }));

    expect(document.documentElement).toHaveAttribute('data-theme', 'black-gold-terminal');
    expect(document.documentElement).toHaveAttribute('data-density', 'terminal');
    expect(document.documentElement).toHaveAttribute('data-radius', 'square');
    expect(JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY) ?? '{}')).toMatchObject({
      theme: 'black-gold-terminal',
      density: 'terminal',
      radius: 'square',
    });
  });

  it('uses the sidebar shortcut to switch between the default dark and light themes', async () => {
    const user = userEvent.setup();
    render(<ThemeProvider><ThemeReader /></ThemeProvider>);

    await user.click(screen.getByRole('button', { name: 'Toggle' }));
    expect(screen.getByTestId('theme-value')).toHaveTextContent('polar-lab');

    await user.click(screen.getByRole('button', { name: 'Toggle' }));
    expect(screen.getByTestId('theme-value')).toHaveTextContent('redline-quant');
  });

  it('previews without persisting until apply and can cancel the preview', async () => {
    const user = userEvent.setup();
    render(<ThemeProvider><ThemeReader /></ThemeProvider>);

    await user.click(screen.getByRole('button', { name: 'Preview navy' }));
    expect(document.documentElement).toHaveAttribute('data-theme', 'deep-navy');
    expect(JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY) ?? '{}').theme).toBe('redline-quant');

    await user.click(screen.getByRole('button', { name: 'Cancel preview' }));
    expect(document.documentElement).toHaveAttribute('data-theme', 'redline-quant');

    await user.click(screen.getByRole('button', { name: 'Preview navy' }));
    await user.click(screen.getByRole('button', { name: 'Apply preview' }));
    expect(JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY) ?? '{}').theme).toBe('deep-navy');
  });
});
