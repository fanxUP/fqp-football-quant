import { useEffect, useRef, useState } from 'react';
import { useRouter } from '../../core/router';
import { api } from '../../core/apiClient';
import { getSidebarPanels, type SidebarPanel } from '../../panelRegistry';
import { useLocalSettings } from '../../shared/hooks/useLocalSettings';
import { useTheme } from '../ThemeContext';
import { useAuth } from '../AuthContext';

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

export default function Sidebar({ isOpen = false, onClose }: SidebarProps) {
  const { currentPath, navigate } = useRouter();
  const { theme, toggleTheme } = useTheme();
  const { logout } = useAuth();
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
            <section key={groupName} className="fqp-nav-group" aria-label={groupName}>
              <div className="fqp-nav-group-title">{groupName}</div>
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
                      {normalizeSidebarIcon(item.icon)}
                    </span>
                    <span>{item.panelName}</span>
                  </button>
                );
              })}
            </section>
          );
        })}
      </nav>

      {/* Theme toggle */}
      <button type="button" className="fqp-theme-toggle" onClick={toggleTheme}>
        <span className="fqp-nav-icon">{theme === 'polar-lab' ? '🌙' : '☀️'}</span>
        <span>{theme === 'polar-lab' ? '切换黑红主题' : '切换极地浅色'}</span>
      </button>

      <button type="button" className="fqp-logout-btn" onClick={() => logout()}>
        <span className="fqp-nav-icon">🚪</span>
        <span>退出登录</span>
      </button>
    </aside>
  );
}
