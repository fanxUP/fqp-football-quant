import { useEffect, useRef, useState } from 'react';
import { useRouter } from '../../core/router';
import { api } from '../../core/apiClient';
import { getSidebarPanels, type SidebarPanel } from '../../panelRegistry';
import { useLocalSettings } from '../../shared/hooks/useLocalSettings';
import { useTheme } from '../ThemeContext';
import { useLanguage } from '../LanguageContext';
import { shellText, sidebarGroupLabel, sidebarPanelLabel } from '../language';

const SIDEBAR_GROUP_ORDER = ['核心闭环', '研究优化', '策略实验', '系统管理'];
const SIDEBAR_GROUP_FALLBACK: Record<string, string> = {
  official_data_core: '核心闭环',
  recommendation_core: '核心闭环',
  betting_center_module: '核心闭环',
  multidim_feature_module: '研究优化',
  model_research_module: '研究优化',
  model_provider_module: '研究优化',
  agent_workspace_module: '研究优化',
  pool_lottery_module: '策略实验',
  module_runtime_core: '系统管理',
  local_settings_core: '系统管理',
  codex_agent_module: '系统管理',
};
const SIDEBAR_GROUP_ALIASES: Record<string, string> = {
  运维设置: '系统管理',
};

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

const SIDEBAR_ICON_MAP: Record<string, string> = {
  activity: '📊',
  chart: '📊',
  football: '⚽',
  trophy: '🏆',
  target: '🎯',
  upload: '📤',
  radar: '📡',
  'trending-down': '📉',
  'trending-up': '⏫',
  ticket: '🎫',
  brain: '🧠',
  microscope: '🔬',
  database: '🗄️',
  puzzle: '🧩',
  settings: '⚙️',
  bot: '🤖',
};

export function normalizeSidebarIcon(icon: string): string {
  if (!icon) return '•';
  return SIDEBAR_ICON_MAP[icon] ?? icon;
}

const ICON_PATHS: Record<string, string> = {
  '📊': 'M4 20V10h4v10m4 0V4h4v16m4 0V8h2v12M2 20h20',
  '⚽': 'M12 3 3 9v9l9 4 9-4V9L12 3Zm0 5 4 3-2 5h-4l-2-5 4-3Zm-9 1 5 2m8 0 5-2M3 18l7-2m4 0 7 2M12 3v5',
  '🏆': 'M7 3h10v8a5 5 0 0 1-10 0V3Zm0 2H3v3a4 4 0 0 0 4 4m10-7h4v3a4 4 0 0 1-4 4m-5 4v5m-5 0h10',
  '🎯': 'M12 3a9 9 0 1 0 9 9M12 7a5 5 0 1 0 5 5m-5 0 9-9m-5 0h5v5',
  '📤': 'M4 15v5h16v-5M12 16V3m-5 5 5-5 5 5',
  '📡': 'M12 3a9 9 0 1 0 9 9M12 7a5 5 0 1 0 5 5m-5 0 8-8m-8 8v.01',
  '📉': 'M3 5v15h18M5 8l5 5 4-3 7 7m-5 0h5v-5',
  '⏫': 'M3 5v15h18M5 16l5-5 4 3 7-7m-5 0h5v5',
  '🎫': 'M3 5h18v5a2 2 0 0 0 0 4v5H3v-5a2 2 0 0 0 0-4V5Zm12 0v3m0 3v2m0 3v3',
  '🧠': 'M12 3v18M12 5C7 0 3 5 5 9c-5 3-1 9 3 8 0 4 4 5 4 1m0-13c5-5 9 0 7 4 5 3 1 9-3 8 0 4-4 5-4 1',
  '🔬': 'M10 3h6v9h-6V3Zm-3 3h3m6 3 4 4v4H5m7-3v6m-6 1h13',
  '🗄️': 'M4 5h16v14H4V5Zm0 5h16m-16 5h16M7 7h2m-2 5h2m-2 5h2',
  '🧩': 'M3 3h6c-1 5 7 5 6 0h6v6c-5-1-5 7 0 6v6h-6c1-5-7-5-6 0H3v-6c5 1 5-7 0-6V3Z',
  '⚙️': 'M9 3h6l1 4 4 1v8l-4 1-1 4H9l-1-4-4-1V8l4-1 1-4Zm3 6a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z',
  '🤖': 'M5 7h14v13H5V7Zm7-4v4M2 11v5m20-5v5M8 11v2m8-2v2m-7 4h6',
  '🗂️': 'M3 7h7l2-3h8v17H3V7Zm0 5h17m-13 4h4',
  '🔌': 'M8 3v5m8-5v5M6 8h12v4a6 6 0 0 1-12 0V8Zm6 10v5',
  '🧭': 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm4 5-2 6-6 2 2-6 6-2Z',
  '🧊': 'M4 7 12 3l8 4v10l-8 4-8-4V7Zm0 0 8 5 8-5m-8 5v9',
  '📰': 'M3 4h14v16H3V4Zm14 4h4v12h-4M6 8h8m-8 4h8m-8 4h3m2 0h3',
  '⏪': 'M12 5v14L3 12l9-7Zm9 0v14l-9-7 9-7Z',
  '🎱': 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 4a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Zm0 5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Z',
  '🔧': 'M15 3a5 5 0 0 0-6 6l-6 8a2.5 2.5 0 0 0 4 4l8-6a5 5 0 0 0 6-6l-4 4-4-4 4-4-2-2Z',
};
function SidebarIcon({ icon }: { icon: string }) {
  return <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d={ICON_PATHS[normalizeSidebarIcon(icon)] ?? 'M4 4h16v16H4V4Zm4 4h8v8H8V8Z'} /></svg>;
}

export default function Sidebar({ isOpen = false, onClose }: SidebarProps) {
  const { currentPath, navigate } = useRouter();
  const { theme, toggleTheme } = useTheme();
  const { language } = useLanguage();
  const text = shellText(language);
  const { settings } = useLocalSettings();
  const disabledModules = new Set(settings.disabledModules);
  const localSidebarPanels = getSidebarPanels(disabledModules);
  const [runtimePanels, setRuntimePanels] = useState<SidebarPanel[] | null>(null);
  const isMounted = useRef(false);
  const loadedSettingsKey = useRef<string | null>(null);
  const sidebarPanels = runtimePanels ?? localSidebarPanels;

  useEffect(() => {
    isMounted.current = true;
    const settingsKey = settings.disabledModules.join(',');
    const loadRuntimePanels = () => {
      api.ui.panels()
        .then((resp) => {
        if (isMounted.current) setRuntimePanels(resp.panels);
        })
        .catch(() => {
        if (isMounted.current) setRuntimePanels(null);
        });
    };
    if (loadedSettingsKey.current !== settingsKey) {
      loadedSettingsKey.current = settingsKey;
      loadRuntimePanels();
    }
    window.addEventListener('fqp-modules-updated', loadRuntimePanels);
    return () => {
      isMounted.current = false;
      window.removeEventListener('fqp-modules-updated', loadRuntimePanels);
    };
  }, [settings.disabledModules]);

  const handleNav = (path: string) => {
    navigate(path);
    onClose?.();
  };

  return (
    <aside className={`fqp-sidebar${isOpen ? ' drawer-open' : ''}`}>
      <div className="fqp-sidebar-logo">FQP</div>
      <nav className="fqp-sidebar-nav">
        {SIDEBAR_GROUP_ORDER.map((groupName) => {
          const groupPanels = sidebarPanels.filter((item) => {
            const configuredGroup = item.menuGroup || SIDEBAR_GROUP_FALLBACK[item.moduleCode];
            return (SIDEBAR_GROUP_ALIASES[configuredGroup || ''] || configuredGroup) === groupName;
          });
          if (groupPanels.length === 0) return null;
          return (
            <section key={groupName} className="fqp-nav-group" aria-label={sidebarGroupLabel(language, groupName)}>
              <div className="fqp-nav-group-title">{sidebarGroupLabel(language, groupName)}</div>
              {groupPanels.map((item) => {
                const isActive =
                  item.routePath === '/'
                    ? currentPath === '/'
                    : currentPath.startsWith(item.routePath);
                return (
                  <button
                    type="button"
                    key={item.panelCode}
                    className={`fqp-nav-item${isActive ? ' active' : ''}`}
                    onClick={() => handleNav(item.routePath)}
                    aria-current={isActive ? 'page' : undefined}
                  >
                    <span className="fqp-nav-icon" aria-hidden="true">
                      <SidebarIcon icon={item.icon} />
                    </span>
                    <span>{sidebarPanelLabel(language, item.panelCode, item.panelName)}</span>
                  </button>
                );
              })}
            </section>
          );
        })}
      </nav>

      {/* Theme toggle */}
      <button type="button" className="fqp-theme-toggle" onClick={toggleTheme}>
        <span className="fqp-nav-icon" aria-hidden="true"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d={theme === 'polar-lab' ? 'M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11Z' : 'M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10ZM12 1v3m0 16v3M1 12h3m16 0h3M4 4l2 2m12 12 2 2M4 20l2-2M18 6l2-2'} /></svg></span>
        <span>{theme === 'polar-lab' ? text.darkTheme : text.lightTheme}</span>
      </button>
    </aside>
  );
}
