import { StrictMode } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Sidebar, { normalizeSidebarIcon } from './Sidebar';

// ---- Mocks ----------------------------------------------------------------

let mockTheme = 'redline-quant';
const mockToggleTheme = vi.fn();
const mockNavigate = vi.fn();
const mockLogout = vi.fn();
const { mockRuntimePanels } = vi.hoisted(() => ({
  mockRuntimePanels: vi.fn(),
}));
let mockCurrentPath = '/';

vi.mock('../../app/ThemeContext', () => ({
  useTheme: () => ({ theme: mockTheme, toggleTheme: mockToggleTheme }),
}));

vi.mock('../AuthContext', () => ({
  useAuth: () => ({ user: 'admin', isLoading: false, login: vi.fn(), logout: mockLogout }),
}));

vi.mock('../../core/router', () => ({
  useRouter: () => ({ currentPath: mockCurrentPath, navigate: mockNavigate, params: {} }),
}));

vi.mock('../../core/apiClient', () => ({
  api: {
    ui: {
      panels: mockRuntimePanels,
    },
  },
}));

// ---- Helpers --------------------------------------------------------------

function renderSidebar(isOpen = false, onClose?: () => void) {
  return render(<Sidebar isOpen={isOpen} onClose={onClose} />);
}

// ---- Tests ----------------------------------------------------------------

describe('Sidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockTheme = 'redline-quant';
    mockCurrentPath = '/';
    mockRuntimePanels.mockRejectedValue(new Error('backend unavailable'));
  });

  // ------------------------------------------------------------------
  // Static rendering
  // ------------------------------------------------------------------
  describe('rendering', () => {
    it.each([
      ['activity', '📊'],
      ['upload', '📤'],
      ['radar', '📡'],
    ])('maps legacy runtime icon code %s to a display symbol', (icon, expected) => {
      expect(normalizeSidebarIcon(icon)).toBe(expected);
    });

    it('renders the brand logo', () => {
      renderSidebar();
      expect(screen.getByText('FQP')).toBeTruthy();
    });

    it('renders all navigation items from the panel registry', () => {
      renderSidebar();
      const labels = [
        '今日驾驶舱',
        '比赛中心',
        '赛事中心',
        '赔率走势',
        '投注中心',
        '今日决策分析',
        '模型表现',
        '策略验证',
        '足彩彩池',
        '系统监控',
        '功能模块',
        '系统设置',
        '智能代理',
      ];

      for (const label of labels) {
        expect(screen.getByText(label)).toBeTruthy();
      }
    });

    it('renders the theme toggle button', () => {
      renderSidebar();
      expect(screen.getByText('切换极地浅色')).toBeTruthy();
    });

    it('hides menu items for disabled modules', () => {
      localStorage.setItem(
        'fqp-settings',
        JSON.stringify({ disabledModules: ['betting_center_module'] }),
      );

      renderSidebar();

      expect(screen.queryByText('投注中心')).toBeNull();
      expect(screen.getByText('今日决策分析')).toBeTruthy();
      expect(screen.getByText('功能模块')).toBeTruthy();
    });

    it('hides strategy lab items when their module is disabled', () => {
      localStorage.setItem(
        'fqp-settings',
        JSON.stringify({ disabledModules: ['pool_lottery_module'] }),
      );

      renderSidebar();

      expect(screen.queryByText('足彩彩池')).toBeNull();
      expect(screen.getByText('投注中心')).toBeTruthy();
    });

    it('uses runtime panels from backend when available', async () => {
      mockRuntimePanels.mockResolvedValue({
        total: 1,
        panels: [
          {
            panelCode: 'remote_panel',
            moduleCode: 'module_runtime_core',
            panelName: '远程入口',
            routePath: '/remote',
            icon: 'remote',
            order: 1,
          },
        ],
      });

      renderSidebar();

      await waitFor(() => expect(screen.getByText('远程入口')).toBeTruthy());
      expect(screen.queryByText('今日驾驶舱')).toBeNull();
    });

    it('renders the runtime system monitor in the maintenance group', async () => {
      mockRuntimePanels.mockResolvedValue({
        total: 1,
        panels: [
          {
            panelCode: 'data_health',
            moduleCode: 'ops_admin',
            panelName: '系统监控',
            routePath: '/data-health',
            menuGroup: '运维设置',
            category: 'maintenance',
            icon: 'database',
            order: 310,
          },
        ],
      });

      renderSidebar();

      expect(await screen.findByRole('button', { name: /系统监控/ })).toBeInTheDocument();
      expect(screen.getByText('系统管理')).toBeInTheDocument();
    });

    it('uses semantic buttons for navigation and theme switching', () => {
      renderSidebar();

      expect(screen.getByRole('button', { name: /今日驾驶舱/ })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /切换极地浅色/ })).toBeInTheDocument();
    });

    it('loads runtime panels once in StrictMode', async () => {
      render(<StrictMode><Sidebar /></StrictMode>);

      await waitFor(() => expect(mockRuntimePanels).toHaveBeenCalledTimes(1));
    });

    it('maps runtime icon codes to display symbols', async () => {
      mockRuntimePanels.mockResolvedValue({
        total: 1,
        panels: [
          {
            panelCode: 'runtime_ticket',
            moduleCode: 'betting_center_module',
            panelName: '彩票台账',
            routePath: '/betting',
            icon: 'ticket',
            order: 1,
          },
        ],
      });

      const { container } = renderSidebar();

      await waitFor(() => expect(screen.getByText('彩票台账')).toBeTruthy());
      const navItem = screen.getByText('彩票台账').closest('.fqp-nav-item');
      expect(navItem?.querySelector('.fqp-nav-icon')?.textContent).toBe('🎫');
      expect(container.textContent).not.toContain('ticket彩票台账');
    });
  });

  // ------------------------------------------------------------------
  // Navigation
  // ------------------------------------------------------------------
  describe('navigation', () => {
    it('navigates when a nav item is clicked', async () => {
      const user = userEvent.setup();
      renderSidebar();
      await user.click(screen.getByText('今日驾驶舱'));
      expect(mockNavigate).toHaveBeenCalledWith('/');
    });

    it('navigates to correct paths', () => {
      renderSidebar();

      const checks: [string, string][] = [
        ['今日驾驶舱', '/'],
        ['比赛中心', '/matches'],
        ['赛事中心', '/events'],
        ['赔率走势', '/odds'],
        ['投注中心', '/betting'],
        ['今日决策分析', '/analysis'],
        ['模型表现', '/models'],
        ['策略验证', '/backtest'],
        ['足彩彩池', '/pool'],
        ['系统监控', '/data-health'],
        ['功能模块', '/modules'],
        ['系统设置', '/settings'],
        ['智能代理', '/agents'],
      ];

      for (const [label, path] of checks) {
        mockNavigate.mockClear();
        fireEvent.click(screen.getByText(label));
        expect(mockNavigate).toHaveBeenCalledWith(path);
      }
    });

    it('calls onClose after navigation when provided', async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      renderSidebar(true, onClose);

      await user.click(screen.getByText('今日驾驶舱'));
      expect(mockNavigate).toHaveBeenCalledWith('/');
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('does not throw when onClose is not provided', async () => {
      const user = userEvent.setup();
      renderSidebar(false);
      // Should not throw
      await user.click(screen.getByText('今日驾驶舱'));
    });
  });

  // ------------------------------------------------------------------
  // Active state
  // ------------------------------------------------------------------
  describe('active state', () => {
    it('marks current path as active', () => {
      mockCurrentPath = '/matches';
      renderSidebar();
      const matchItem = screen.getByText('比赛中心').closest('.fqp-nav-item');
      expect(matchItem?.classList.contains('active')).toBe(true);
    });

    it('does not mark inactive paths', () => {
      mockCurrentPath = '/matches';
      renderSidebar();
      const otherItem = screen.getByText('今日决策分析').closest('.fqp-nav-item');
      expect(otherItem?.classList.contains('active')).toBe(false);
    });

    it('handles root path exactly (not prefix-match everything)', () => {
      mockCurrentPath = '/matches';
      renderSidebar();
      const rootItem = screen.getByText('今日驾驶舱').closest('.fqp-nav-item');
      // '/' should not be active when currentPath is '/matches'
      expect(rootItem?.classList.contains('active')).toBe(false);
    });

    it('marks root active when currentPath is exactly /', () => {
      mockCurrentPath = '/';
      renderSidebar();
      const rootItem = screen.getByText('今日驾驶舱').closest('.fqp-nav-item');
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
      await user.click(screen.getByText('切换极地浅色'));
      expect(mockToggleTheme).toHaveBeenCalledTimes(1);
    });

    it('shows the light-theme target in a dark theme', () => {
      mockTheme = 'redline-quant';
      renderSidebar();
      expect(screen.getByText('切换极地浅色')).toBeTruthy();
    });

    it('shows the dark-theme target in the light theme', () => {
      mockTheme = 'polar-lab';
      renderSidebar();
      expect(screen.getByText('切换黑红主题')).toBeTruthy();
    });

    it('shows ☀️ in dark mode', () => {
      mockTheme = 'redline-quant';
      renderSidebar();
      const toggle = screen.getByText('切换极地浅色');
      expect(toggle.parentElement?.textContent).toContain('☀️');
    });

    it('shows 🌙 in light mode', () => {
      mockTheme = 'polar-lab';
      renderSidebar();
      const toggle = screen.getByText('切换黑红主题');
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
