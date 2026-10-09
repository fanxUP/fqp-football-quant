import { useState, useCallback, type ReactNode } from 'react';
import Sidebar from './Sidebar';
import { LiveStatusProvider } from '../../features/command-center/LiveStatus';
import GlobalStatusBar from '../../features/command-center/GlobalStatusBar';
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
    <LiveStatusProvider><div className="fqp-layout">
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

      <div className="cc-shell">
      <header className="cc-top-bar">
      <GlobalStatusBar />
      <div className="fqp-top-actions" aria-label={text.accountActions}>
        <label className="fqp-language-select">
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><circle cx="12" cy="12" r="9" /><ellipse cx="12" cy="12" rx="4" ry="9" /><path d="M3 12h18" /></svg>
          <select
            aria-label={text.language}
            value={language}
            onChange={(event) => setLanguage(event.target.value as AppLanguage)}
          >
            {LANGUAGE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.flag} {option.label}</option>)}
          </select>
        </label>
        <button type="button" className="fqp-logout-btn" onClick={() => logout()}>
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M10 4H4v16h6M10 12h10m-4-4 4 4-4 4" /></svg>
          <span>{text.logout}</span>
        </button>
      </div>

      </header>
      <main className="fqp-main">
        {children}
      </main>
      </div>
    </div></LiveStatusProvider>
  );
}
