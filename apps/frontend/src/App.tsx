import { createRouter, navigate as routerNavigate, useRouter } from './core/router';
import { ThemeProvider } from './app/ThemeContext';
import { ToastProvider } from './shared/components/Toast';
import { AuthProvider, useAuth } from './app/AuthContext';
import Layout from './app/layout/Layout';
import LoadingSpinner from './shared/components/LoadingSpinner';
import LoginPage from './pages/LoginPage';

// Lazy-load all pages
import { lazy, Suspense, useEffect } from 'react';

const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const MatchesPage = lazy(() => import('./pages/MatchesPage'));
const MatchDetailPage = lazy(() => import('./pages/MatchDetailPage'));
const RecommendationDetailPage = lazy(() => import('./pages/RecommendationDetailPage'));
const ModelsPage = lazy(() => import('./pages/ModelsPage'));
const DataHealthPage = lazy(() => import('./pages/DataHealthPage'));
const EventsPage = lazy(() => import('./pages/EventsPage'));
const ModulesPage = lazy(() => import('./pages/ModulesPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const ModelProvidersPage = lazy(() => import('./pages/ModelProvidersPage'));
const AgentWorkspacePage = lazy(() => import('./pages/AgentWorkspacePage'));
const AgentPanel = lazy(() => import('./pages/AgentPanel'));
const BacktestPage = lazy(() => import('./pages/BacktestPage'));
const PoolPage = lazy(() => import('./pages/PoolPage'));
const AnalysisPage = lazy(() => import('./pages/AnalysisPage'));
const BettingCenterPage = lazy(() => import('./pages/BettingCenterPage'));
const OddsMovementPage = lazy(() => import('./pages/OddsMovementPage'));
const UpsetsPage = lazy(() => import('./pages/UpsetsPage'));

function RedirectTo({ path, text = '正在进入页面...' }: { path: string; text?: string }) {
  useEffect(() => {
    routerNavigate(path);
  }, [path]);
  return <LoadingSpinner text={text} size="lg" />;
}

// ---- Route table ----
const routes = [
  { path: '/login', render: () => <LoginPage /> },
  { path: '/', render: () => <DashboardPage /> },
  { path: '/matches', render: () => <MatchesPage /> },
  { path: '/matches/:id', render: (p: Record<string, string>) => <MatchDetailPage matchId={Number(p.id)} /> },
  { path: '/recommendations', render: () => <RedirectTo path="/analysis?section=pre_match" /> },
  { path: '/recommendations/:id', render: (p: Record<string, string>) => <RecommendationDetailPage ticketId={Number(p.id)} /> },
  { path: '/betting', render: () => <BettingCenterPage /> },
  { path: '/tickets', render: () => <BettingCenterPage initialTab="tickets" /> },
  { path: '/tickets/new', render: () => <RedirectTo path="/betting?tab=bet-slip" /> },
  { path: '/tickets/:id', render: () => <RedirectTo path="/betting?tab=tickets" /> },
  { path: '/reviews', render: () => <RedirectTo path="/analysis?section=reviews" /> },
  { path: '/models', render: () => <ModelsPage /> },
  { path: '/data-health', render: () => <DataHealthPage /> },
  { path: '/events', render: () => <EventsPage /> },
  { path: '/modules', render: () => <ModulesPage /> },
  { path: '/settings', render: () => <SettingsPage /> },
  { path: '/model-providers', render: () => <ModelProvidersPage /> },
  { path: '/agent-workspace', render: () => <AgentWorkspacePage /> },
  { path: '/agents', render: () => <AgentPanel /> },
  { path: '/backtest', render: () => <BacktestPage /> },
  { path: '/pool', render: () => <PoolPage /> },
  { path: '/analysis', render: () => <AnalysisPage /> },
  { path: '/feature-snapshots', render: () => <AnalysisPage standaloneSection="features" /> },
  { path: '/simulator', render: () => <RedirectTo path="/betting?tab=bet-slip" text="正在进入投注中心..." /> },
  { path: '/simulator/history/:id', render: () => <RedirectTo path="/betting?tab=tickets" text="正在进入投注中心..." /> },
  { path: '/simulator/history', render: () => <RedirectTo path="/betting?tab=tickets" text="正在进入投注中心..." /> },
  { path: '/simulator/bankroll', render: () => <RedirectTo path="/betting?tab=competition" text="正在进入投注中心..." /> },
  { path: '/competition', render: () => <BettingCenterPage initialTab="competition" /> },
  { path: '/competition/history', render: () => <RedirectTo path="/betting?tab=competition" text="正在进入投注中心..." /> },
  { path: '/odds', render: () => <OddsMovementPage /> },
  { path: '/upsets', render: () => <UpsetsPage /> },
];

createRouter(routes);

// ---- Page outlet ----
function PageOutlet() {
  const { currentPath, params } = useRouter();

  // Find matching route
  const routeParts = currentPath.split('/').filter(Boolean);
  for (const route of routes) {
    const rp = route.path.split('/').filter(Boolean);
    if (rp.length !== routeParts.length) continue;
    let match = true;
    for (let i = 0; i < rp.length; i++) {
      if (!rp[i].startsWith(':') && rp[i] !== routeParts[i]) {
        match = false;
        break;
      }
    }
    if (match) {
      return (
        <Suspense fallback={<LoadingSpinner text="加载页面..." size="lg" />}>
          <div key={currentPath} className="fqp-page-transition">
            {route.render(params)}
          </div>
        </Suspense>
      );
    }
  }

  // 404
  return (
    <div className="fqp-empty-state">
      <div className="fqp-empty-icon">🔍</div>
      <div className="fqp-empty-title">页面不存在</div>
      <div className="fqp-empty-desc">路径: {currentPath}</div>
    </div>
  );
}

// ---- Auth-aware content ----
function AppContent() {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="fqp-loading-screen">
        <LoadingSpinner text="加载中..." size="lg" />
      </div>
    );
  }

  if (!user) {
    // Only allow /login when not authenticated
    const path = window.location.hash.replace(/^#/, '') || '/';
    if (path !== '/login') {
      window.location.hash = '#/login';
    }
    return <PageOutlet />;
  }

  // Logged in — redirect away from /login to dashboard
  const loggedPath = window.location.hash.replace(/^#/, '') || '/';
  if (loggedPath === '/login') {
    window.location.hash = '#/';
  }

  return (
    <Layout>
      <PageOutlet />
    </Layout>
  );
}

// ---- App root ----
export default function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <AuthProvider>
          <AppContent />
        </AuthProvider>
      </ToastProvider>
    </ThemeProvider>
  );
}
