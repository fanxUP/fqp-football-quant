import { useState, useCallback, type ReactNode } from 'react';
import Sidebar from './Sidebar';
import { useAuth } from '../AuthContext';
import { useLanguage } from '../LanguageContext';
import { LANGUAGE_OPTIONS, shellText, type AppLanguage } from '../language';

interface LayoutProps {
  children: ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { logout } = useAuth();
  const { language, setLanguage } = useLanguage();
  const text = shellText(language);

  const openSidebar = useCallback(() => setSidebarOpen(true), []);
  const closeSidebar = useCallback(() => setSidebarOpen(false), []);

  return (
    <div className="fqp-layout">
      {/* Hamburger button — mobile only */}
      <button
        className="fqp-hamburger"
        onClick={openSidebar}
        aria-label={text.openMenu}
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

      <div className="fqp-top-actions" aria-label={text.accountActions}>
        <label className="fqp-language-select">
          <span aria-hidden="true">🌐</span>
          <select
            aria-label={text.language}
            value={language}
            onChange={(event) => setLanguage(event.target.value as AppLanguage)}
          >
            {LANGUAGE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <button type="button" className="fqp-logout-btn" onClick={() => logout()}>
          <span aria-hidden="true">🚪</span>
          <span>{text.logout}</span>
        </button>
      </div>

      <main className="fqp-main">
        {children}
      </main>
    </div>
  );
}
