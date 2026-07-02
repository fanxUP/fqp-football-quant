import { useRouter } from '../../core/router';

interface NavItem {
  label: string;
  icon: string;
  path: string;
}

const NAV_ITEMS: NavItem[] = [
  { label: '今日', icon: '📊', path: '/' },
  { label: '比赛', icon: '⚽', path: '/matches' },
  { label: '推荐', icon: '🎯', path: '/recommendations' },
  { label: '实票', icon: '🧾', path: '/tickets' },
  { label: '复盘', icon: '📈', path: '/reviews' },
  { label: '模型', icon: '🧠', path: '/models' },
  { label: '数据', icon: '🗄️', path: '/data-health' },
  { label: '模块', icon: '🧩', path: '/modules' },
  { label: '设置', icon: '⚙️', path: '/settings' },
  { label: 'Agent', icon: '🤖', path: '/agents' },
  { label: '回测', icon: '⏪', path: '/backtest' },
  { label: '足彩', icon: '🎱', path: '/pool' },
];

export default function Sidebar() {
  const { currentPath, navigate } = useRouter();

  return (
    <aside className="fqp-sidebar">
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
              onClick={() => navigate(item.path)}
            >
              <span className="fqp-nav-icon">{item.icon}</span>
              <span>{item.label}</span>
            </div>
          );
        })}
      </nav>
    </aside>
  );
}
