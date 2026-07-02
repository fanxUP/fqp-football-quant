import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider, useTheme } from '../app/ThemeContext';
import type { ReactNode } from 'react';

// ---- Helper: component that reads context and exposes it to tests ----

let themeValue: { theme: string; toggleTheme: () => void } | null = null;

function ThemeReader() {
  themeValue = useTheme();
  return (
    <div>
      <span data-testid="theme-value">{themeValue.theme}</span>
      <button data-testid="theme-toggle" onClick={themeValue.toggleTheme}>
        Toggle
      </button>
    </div>
  );
}

function renderWithTheme(ui: ReactNode) {
  themeValue = null;
  return render(<ThemeProvider>{ui}</ThemeProvider>);
}

// ---- Helper: manage localStorage + DOM attribute ----

function clearStoredTheme() {
  localStorage.removeItem('fqp-theme');
  document.documentElement.removeAttribute('data-theme');
}

// ---- Tests ----

describe('ThemeContext', () => {
  beforeEach(() => {
    clearStoredTheme();
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })));
  });

  // ------------------------------------------------------------------
  // Initialisation
  // ------------------------------------------------------------------

  describe('initialisation', () => {
    it('defaults to dark when nothing is stored and system prefers dark', () => {
      renderWithTheme(<ThemeReader />);
      expect(screen.getByTestId('theme-value').textContent).toBe('dark');
    });

    it('respects localStorage when "light" is stored', () => {
      localStorage.setItem('fqp-theme', 'light');
      renderWithTheme(<ThemeReader />);
      expect(screen.getByTestId('theme-value').textContent).toBe('light');
    });

    it('respects localStorage when "dark" is stored', () => {
      localStorage.setItem('fqp-theme', 'dark');
      renderWithTheme(<ThemeReader />);
      expect(screen.getByTestId('theme-value').textContent).toBe('dark');
    });

    it('falls back to system preference "light" when no stored value', () => {
      vi.stubGlobal('matchMedia', vi.fn(() => ({
        matches: true,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })));
      renderWithTheme(<ThemeReader />);
      expect(screen.getByTestId('theme-value').textContent).toBe('light');
    });
  });

  // ------------------------------------------------------------------
  // Toggling
  // ------------------------------------------------------------------
  describe('toggleTheme', () => {
    it('switches from dark to light', async () => {
      const user = userEvent.setup();
      renderWithTheme(<ThemeReader />);

      expect(screen.getByTestId('theme-value').textContent).toBe('dark');
      await user.click(screen.getByTestId('theme-toggle'));
      expect(screen.getByTestId('theme-value').textContent).toBe('light');
    });

    it('switches from light to dark', async () => {
      localStorage.setItem('fqp-theme', 'light');
      const user = userEvent.setup();
      renderWithTheme(<ThemeReader />);

      expect(screen.getByTestId('theme-value').textContent).toBe('light');
      await user.click(screen.getByTestId('theme-toggle'));
      expect(screen.getByTestId('theme-value').textContent).toBe('dark');
    });

    it('persists the new value to localStorage', async () => {
      const user = userEvent.setup();
      renderWithTheme(<ThemeReader />);

      await user.click(screen.getByTestId('theme-toggle'));
      expect(localStorage.getItem('fqp-theme')).toBe('light');

      await user.click(screen.getByTestId('theme-toggle'));
      expect(localStorage.getItem('fqp-theme')).toBe('dark');
    });
  });

  // ------------------------------------------------------------------
  // DOM attribute
  // ------------------------------------------------------------------
  describe('data-theme attribute on <html>', () => {
    it('sets data-theme="light" when theme is light', () => {
      localStorage.setItem('fqp-theme', 'light');
      renderWithTheme(<ThemeReader />);
      expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    });

    it('sets data-theme="dark" when theme is dark', () => {
      renderWithTheme(<ThemeReader />);
      expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    });

    it('updates the attribute on toggle', async () => {
      const user = userEvent.setup();
      renderWithTheme(<ThemeReader />);

      expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
      await user.click(screen.getByTestId('theme-toggle'));
      expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    });
  });

  // ------------------------------------------------------------------
  // System-preference listener
  // ------------------------------------------------------------------
  describe('system preference changes', () => {
    it('registers a change listener on the matchMedia object', () => {
      const addEventListener = vi.fn();
      const removeEventListener = vi.fn();

      vi.stubGlobal('matchMedia', vi.fn(() => ({
        matches: false,
        addEventListener,
        removeEventListener,
      })));

      renderWithTheme(<ThemeReader />);
      expect(addEventListener).toHaveBeenCalledWith('change', expect.any(Function));
    });

    it('returns a cleanup function that removes the listener', () => {
      const removeEventListener = vi.fn();

      vi.stubGlobal('matchMedia', vi.fn(() => ({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener,
      })));

      const { unmount } = renderWithTheme(<ThemeReader />);
      unmount();
      expect(removeEventListener).toHaveBeenCalledWith('change', expect.any(Function));
    });
  });

  // ------------------------------------------------------------------
  // Edge cases
  // ------------------------------------------------------------------
  describe('edge cases', () => {
    it('survives malformed localStorage values', () => {
      localStorage.setItem('fqp-theme', 'INVALID');
      renderWithTheme(<ThemeReader />);
      // Falls back to dark (system mock says dark)
      expect(screen.getByTestId('theme-value').textContent).toBe('dark');
    });

    it('returns default context value when used outside provider', () => {
      // ThemeContext uses createContext with a default — no provider means default
      themeValue = null;
      render(<ThemeReader />);
      // The default value from createContext is 'dark'
      expect(screen.getByTestId('theme-value').textContent).toBe('dark');
    });
  });
});
