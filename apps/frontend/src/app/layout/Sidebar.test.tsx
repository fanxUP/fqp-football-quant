import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Sidebar from './Sidebar';

// ---- Mocks ----------------------------------------------------------------

let mockTheme = 'dark';
const mockToggleTheme = vi.fn();
const mockNavigate = vi.fn();
let mockCurrentPath = '/';

vi.mock('../../app/ThemeContext', () => ({
  useTheme: () => ({ theme: mockTheme, toggleTheme: mockToggleTheme }),
}));

vi.mock('../../core/router', () => ({
  useRouter: () => ({ currentPath: mockCurrentPath, navigate: mockNavigate, params: {} }),
}));

// ---- Helpers --------------------------------------------------------------

function renderSidebar(isOpen = false, onClose?: () => void) {
  return render(<Sidebar isOpen={isOpen} onClose={onClose} />);
}

// ---- Tests ----------------------------------------------------------------

describe('Sidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTheme = 'dark';
    mockCurrentPath = '/';
  });

  // ------------------------------------------------------------------
  // Static rendering
  // ------------------------------------------------------------------
  describe('rendering', () => {
    it('renders the brand logo', () => {
      renderSidebar();
      expect(screen.getByText('FQP')).toBeTruthy();
    });

    it('renders all 13 navigation items', () => {
      renderSidebar();
      expect(screen.getByText('今日')).toBeTruthy();
      expect(screen.getByText('比赛')).toBeTruthy();
      expect(screen.getByText('推荐')).toBeTruthy();
      expect(screen.getByText('实票')).toBeTruthy();
      expect(screen.getByText('复盘')).toBeTruthy();
      expect(screen.getByText('模型')).toBeTruthy();
      expect(screen.getByText('数据')).toBeTruthy();
      expect(screen.getByText('模块')).toBeTruthy();
      expect(screen.getByText('设置')).toBeTruthy();
      expect(screen.getByText('Agent')).toBeTruthy();
      expect(screen.getByText('回测')).toBeTruthy();
      expect(screen.getByText('足彩')).toBeTruthy();
      expect(screen.getByText('分析')).toBeTruthy();
    });

    it('renders the theme toggle button', () => {
      renderSidebar();
      // dark theme → shows "亮色模式"
      expect(screen.getByText('亮色模式')).toBeTruthy();
    });
  });

  // ------------------------------------------------------------------
  // Navigation
  // ------------------------------------------------------------------
  describe('navigation', () => {
    it('navigates when a nav item is clicked', async () => {
      const user = userEvent.setup();
      renderSidebar();
      await user.click(screen.getByText('今日'));
      expect(mockNavigate).toHaveBeenCalledWith('/');
    });

    it('navigates to correct paths', async () => {
      const user = userEvent.setup();
      renderSidebar();

      const checks: [string, string][] = [
        ['今日', '/'],
        ['比赛', '/matches'],
        ['推荐', '/recommendations'],
        ['实票', '/tickets'],
        ['复盘', '/reviews'],
        ['模型', '/models'],
        ['数据', '/data-health'],
        ['模块', '/modules'],
        ['设置', '/settings'],
        ['Agent', '/agents'],
        ['回测', '/backtest'],
        ['足彩', '/pool'],
        ['分析', '/analysis'],
      ];

      for (const [label, path] of checks) {
        mockNavigate.mockClear();
        await user.click(screen.getByText(label));
        expect(mockNavigate).toHaveBeenCalledWith(path);
      }
    });

    it('calls onClose after navigation when provided', async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      renderSidebar(true, onClose);

      await user.click(screen.getByText('今日'));
      expect(mockNavigate).toHaveBeenCalledWith('/');
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('does not throw when onClose is not provided', async () => {
      const user = userEvent.setup();
      renderSidebar(false);
      // Should not throw
      await user.click(screen.getByText('今日'));
    });
  });

  // ------------------------------------------------------------------
  // Active state
  // ------------------------------------------------------------------
  describe('active state', () => {
    it('marks current path as active', () => {
      mockCurrentPath = '/matches';
      renderSidebar();
      // The "比赛" nav item should have the active class
      const matchItem = screen.getByText('比赛').closest('.fqp-nav-item');
      expect(matchItem?.classList.contains('active')).toBe(true);
    });

    it('does not mark inactive paths', () => {
      mockCurrentPath = '/matches';
      renderSidebar();
      const otherItem = screen.getByText('推荐').closest('.fqp-nav-item');
      expect(otherItem?.classList.contains('active')).toBe(false);
    });

    it('handles root path exactly (not prefix-match everything)', () => {
      mockCurrentPath = '/matches';
      renderSidebar();
      const rootItem = screen.getByText('今日').closest('.fqp-nav-item');
      // '/' should not be active when currentPath is '/matches'
      expect(rootItem?.classList.contains('active')).toBe(false);
    });

    it('marks root active when currentPath is exactly /', () => {
      mockCurrentPath = '/';
      renderSidebar();
      const rootItem = screen.getByText('今日').closest('.fqp-nav-item');
      expect(rootItem?.classList.contains('active')).toBe(true);
    });
  });

  // ------------------------------------------------------------------
  // Theme toggle
  // ------------------------------------------------------------------
  describe('theme toggle', () => {
    it('calls toggleTheme when clicked', async () => {
      const user = userEvent.setup();
      renderSidebar();
      await user.click(screen.getByText('亮色模式'));
      expect(mockToggleTheme).toHaveBeenCalledTimes(1);
    });

    it('shows correct label in dark mode', () => {
      mockTheme = 'dark';
      renderSidebar();
      expect(screen.getByText('亮色模式')).toBeTruthy();
    });

    it('shows correct label in light mode', () => {
      mockTheme = 'light';
      renderSidebar();
      expect(screen.getByText('暗色模式')).toBeTruthy();
    });

    it('shows ☀️ in dark mode', () => {
      mockTheme = 'dark';
      renderSidebar();
      const toggle = screen.getByText('亮色模式');
      expect(toggle.parentElement?.textContent).toContain('☀️');
    });

    it('shows 🌙 in light mode', () => {
      mockTheme = 'light';
      renderSidebar();
      const toggle = screen.getByText('暗色模式');
      expect(toggle.parentElement?.textContent).toContain('🌙');
    });
  });

  // ------------------------------------------------------------------
  // Mobile drawer
  // ------------------------------------------------------------------
  describe('mobile drawer (isOpen / onClose)', () => {
    it('has the fqp-sidebar class', () => {
      const { container } = renderSidebar();
      expect(container.querySelector('.fqp-sidebar')).toBeTruthy();
    });

    it('adds drawer-open class when isOpen=true', () => {
      const { container } = renderSidebar(true);
      expect(container.querySelector('.drawer-open')).toBeTruthy();
    });

    it('does not have drawer-open class when isOpen=false', () => {
      const { container } = renderSidebar(false);
      expect(container.querySelector('.drawer-open')).toBeFalsy();
    });
  });
});
