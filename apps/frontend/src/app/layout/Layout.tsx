import { useState, useCallback, type ReactNode } from 'react';
import Sidebar from './Sidebar';

interface LayoutProps {
  children: ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

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

      <main className="fqp-main">
        {children}
      </main>
    </div>
  );
}
