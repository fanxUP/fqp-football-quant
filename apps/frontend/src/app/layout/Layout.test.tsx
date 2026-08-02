import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Layout from './Layout';

// ---- Mocks ----------------------------------------------------------------

// Sidebar is tested independently; we render a minimal placeholder for
// Layout tests so we can assert the drawer wiring.

vi.mock('./Sidebar', () => ({
  default: ({ isOpen, onClose }: { isOpen?: boolean; onClose?: () => void }) => (
    <div data-testid="sidebar" data-open={String(!!isOpen)}>
      <button data-testid="sidebar-close" onClick={onClose}>
        Close Sidebar
      </button>
    </div>
  ),
}));

const mockLogout = vi.fn();

vi.mock('../AuthContext', () => ({
  useAuth: () => ({ logout: mockLogout }),
}));

// ---- Helper ---------------------------------------------------------------

// jsdom matchMedia stub for any media-query logic
beforeEach(() => {
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })));
});

// ---- Tests ----------------------------------------------------------------

describe('Layout', () => {
  // ------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------
  describe('rendering', () => {
    it('renders the logout control in the main top-right action area', () => {
      const { container } = render(<Layout><div /></Layout>);

      expect(screen.getByRole('button', { name: '退出登录' })).toBeTruthy();
      expect(container.querySelector('.fqp-top-actions .fqp-logout-btn')).toBeTruthy();
    });

    it('renders a Simplified Chinese language selector before logout by default', () => {
      const { container } = render(<Layout><div /></Layout>);

      const languageSelector = screen.getByRole('combobox', { name: '界面语言' });
      expect(languageSelector).toHaveValue('zh-CN');
      expect(screen.getByRole('option', { name: '简体中文' })).toBeTruthy();
      expect(screen.getByRole('option', { name: 'English' })).toBeTruthy();
      expect(container.querySelector('.fqp-top-actions .fqp-language-select + .fqp-logout-btn')).toBeTruthy();
    });

    it('renders children inside the main area', () => {
      render(
        <Layout>
          <div data-testid="child">Hello</div>
        </Layout>,
      );
      expect(screen.getByTestId('child').textContent).toBe('Hello');
    });

    it('renders the sidebar', () => {
      render(<Layout><div /></Layout>);
      expect(screen.getByTestId('sidebar')).toBeTruthy();
    });

    it('renders the hamburger button', () => {
      render(<Layout><div /></Layout>);
      const btn = screen.getByRole('button', { name: '打开菜单' });
      expect(btn).toBeTruthy();
      expect(btn.querySelectorAll('span').length).toBe(3);
    });

    it('does not render the global disclaimer footer', () => {
      render(<Layout><div /></Layout>);
      const removedFooterPattern = new RegExp(
        [['不', '提供'], ['代', '购'], ['出', '票'], ['收', '款']]
          .map((parts) => parts.join(''))
          .join('|'),
      );
      expect(screen.queryByText(removedFooterPattern)).toBeNull();
    });
  });

  // ------------------------------------------------------------------
  // Mobile sidebar toggle
  // ------------------------------------------------------------------
  describe('sidebar drawer', () => {
    it('starts with sidebar closed', () => {
      render(<Layout><div /></Layout>);
      expect(screen.getByTestId('sidebar').dataset.open).toBe('false');
    });

    it('opens sidebar when hamburger is clicked', async () => {
      const user = userEvent.setup();
      render(<Layout><div /></Layout>);

      await user.click(screen.getByRole('button', { name: '打开菜单' }));
      expect(screen.getByTestId('sidebar').dataset.open).toBe('true');
    });

    it('shows overlay when sidebar is open', async () => {
      const user = userEvent.setup();
      const { container } = render(<Layout><div /></Layout>);

      // Overlay should NOT exist initially
      expect(container.querySelector('.fqp-sidebar-overlay')).toBeFalsy();

      // Open sidebar → overlay should appear
      await user.click(screen.getByRole('button', { name: '打开菜单' }));
      expect(container.querySelector('.fqp-sidebar-overlay')).toBeTruthy();
    });
  });

  // ------------------------------------------------------------------
  // Overlay click closes
  // ------------------------------------------------------------------
  describe('overlay dismissal', () => {
    it('closes sidebar when overlay is clicked', async () => {
      const user = userEvent.setup();
      const { container } = render(<Layout><div /></Layout>);

      // Open
      await user.click(screen.getByRole('button', { name: '打开菜单' }));
      expect(screen.getByTestId('sidebar').dataset.open).toBe('true');

      // Click overlay
      const overlay = container.querySelector('.fqp-sidebar-overlay')!;
      await user.click(overlay);
      expect(screen.getByTestId('sidebar').dataset.open).toBe('false');
    });

    it('hides overlay after closing', async () => {
      const user = userEvent.setup();
      const { container } = render(<Layout><div /></Layout>);

      await user.click(screen.getByRole('button', { name: '打开菜单' }));
      const overlay = container.querySelector('.fqp-sidebar-overlay')!;
      await user.click(overlay);

      expect(container.querySelector('.fqp-sidebar-overlay')).toBeFalsy();
    });
  });

  // ------------------------------------------------------------------
  // Sidebar onClose closes drawer
  // ------------------------------------------------------------------
  describe('sidebar onClose prop', () => {
    it('closes the drawer when sidebar calls onClose', async () => {
      const user = userEvent.setup();
      render(<Layout><div /></Layout>);

      // Open
      await user.click(screen.getByRole('button', { name: '打开菜单' }));
      expect(screen.getByTestId('sidebar').dataset.open).toBe('true');

      // Simulate sidebar calling onClose (e.g., nav item clicked)
      await user.click(screen.getByTestId('sidebar-close'));
      expect(screen.getByTestId('sidebar').dataset.open).toBe('false');
    });
  });
});
