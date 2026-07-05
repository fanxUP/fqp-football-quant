import { useRouter } from '../../core/router';
import { useTheme } from '../ThemeContext';

interface NavItem {
  label: string;
  icon: string;
  path: string;
}

const NAV_ITEMS: NavItem[] = [
  { label: '数据概览', icon: '📊', path: '/' },
  { label: '开赛盘口', icon: '⚽', path: '/matches' },
  { label: '赛事中心', icon: '🏆', path: '/events' },
  { label: '智能推荐', icon: '🎯', path: '/recommendations' },
  { label: '赔率走势', icon: '📉', path: '/odds' },
  { label: '实票管理', icon: '🧾', path: '/tickets' },
  { label: '复盘分析', icon: '📈', path: '/reviews' },
  { label: '模型中心', icon: '🧠', path: '/models' },
  { label: '系统监控', icon: '🗄️', path: '/data-health' },
  { label: '功能模块', icon: '🧩', path: '/modules' },
  { label: '系统设置', icon: '⚙️', path: '/settings' },
  { label: '智能代理', icon: '🤖', path: '/agents' },
  { label: '策略回测', icon: '⏪', path: '/backtest' },
  { label: '足彩彩池', icon: '🎱', path: '/pool' },
  { label: '深度分析', icon: '🔬', path: '/analysis' },
  { label: '模拟投注', icon: '🎮', path: '/simulator' },
  { label: '对抗竞赛', icon: '⚔️', path: '/competition' },
];

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

export default function Sidebar({ isOpen = false, onClose }: SidebarProps) {
  const { currentPath, navigate } = useRouter();
  const { theme, toggleTheme } = useTheme();

  const handleNav = (path: string) => {
    navigate(path);
    onClose?.();
  };

  return (
    <aside className={`fqp-sidebar${isOpen ? ' drawer-open' : ''}`}>
      <div className="fqp-sidebar-logo">FQP</div>
      <nav className="fqp-sidebar-nav">
        {NAV_ITEMS.map((item) => {
          const isActive =
            item.path === '/'
              ? currentPath === '/'
              : currentPath.startsWith(item.path);
          return (
            <div
              key={item.path}
              className={`fqp-nav-item${isActive ? ' active' : ''}`}
              onClick={() => handleNav(item.path)}
            >
              <span className="fqp-nav-icon">{item.icon}</span>
              <span>{item.label}</span>
            </div>
          );
        })}
      </nav>

      {/* Theme toggle */}
      <div className="fqp-theme-toggle" onClick={toggleTheme}>
        <span className="fqp-nav-icon">{theme === 'dark' ? '☀️' : '🌙'}</span>
        <span>{theme === 'dark' ? '亮色模式' : '暗色模式'}</span>
      </div>
    </aside>
  );
}
