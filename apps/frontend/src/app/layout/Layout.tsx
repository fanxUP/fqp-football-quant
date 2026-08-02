import { useState, useCallback, type ReactNode } from 'react';
import Sidebar from './Sidebar';
import { useAuth } from '../AuthContext';

interface LayoutProps {
  children: ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { logout } = useAuth();

  const openSidebar = useCallback(() => setSidebarOpen(true), []);
  const closeSidebar = useCallback(() => setSidebarOpen(false), []);

  return (
    <div className="fqp-layout">
      {/* Hamburger button — mobile only */}
      <button
        className="fqp-hamburger"
        onClick={openSidebar}
        aria-label="打开菜单"
      >
        <span />
        <span />
        <span />
      </button>

      {/* Sidebar overlay — mobile only */}
      {sidebarOpen && (
        <div className="fqp-sidebar-overlay" onClick={closeSidebar} />
      )}

      <Sidebar isOpen={sidebarOpen} onClose={closeSidebar} />

      <div className="fqp-top-actions" aria-label="账户操作">
        <button type="button" className="fqp-logout-btn" onClick={() => logout()}>
          <span aria-hidden="true">🚪</span>
          <span>退出登录</span>
        </button>
      </div>

      <main className="fqp-main">
        {children}
      </main>
    </div>
  );
}
