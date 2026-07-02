import { createRouter, useRouter } from './core/router';
import { ThemeProvider } from './app/ThemeContext';
import { ToastProvider } from './shared/components/Toast';
import Layout from './app/layout/Layout';
import LoadingSpinner from './shared/components/LoadingSpinner';

// Lazy-load all pages
import { lazy, Suspense } from 'react';

const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const MatchesPage = lazy(() => import('./pages/MatchesPage'));
const MatchDetailPage = lazy(() => import('./pages/MatchDetailPage'));
const RecommendationsPage = lazy(() => import('./pages/RecommendationsPage'));
const RecommendationDetailPage = lazy(() => import('./pages/RecommendationDetailPage'));
const TicketsPage = lazy(() => import('./pages/TicketsPage'));
const TicketNewPage = lazy(() => import('./pages/TicketNewPage'));
const TicketDetailPage = lazy(() => import('./pages/TicketDetailPage'));
const ReviewsPage = lazy(() => import('./pages/ReviewsPage'));
const ModelsPage = lazy(() => import('./pages/ModelsPage'));
const DataHealthPage = lazy(() => import('./pages/DataHealthPage'));
const ModulesPage = lazy(() => import('./pages/ModulesPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const AgentPanel = lazy(() => import('./pages/AgentPanel'));
const BacktestPage = lazy(() => import('./pages/BacktestPage'));
const PoolPage = lazy(() => import('./pages/PoolPage'));
const AnalysisPage = lazy(() => import('./pages/AnalysisPage'));

// ---- Route table ----
const routes = [
  { path: '/', render: () => <DashboardPage /> },
  { path: '/matches', render: () => <MatchesPage /> },
  { path: '/matches/:id', render: (p: Record<string, string>) => <MatchDetailPage matchId={Number(p.id)} /> },
  { path: '/recommendations', render: () => <RecommendationsPage /> },
  { path: '/recommendations/:id', render: (p: Record<string, string>) => <RecommendationDetailPage ticketId={Number(p.id)} /> },
  { path: '/tickets', render: () => <TicketsPage /> },
  { path: '/tickets/new', render: () => <TicketNewPage /> },
  { path: '/tickets/:id', render: (p: Record<string, string>) => <TicketDetailPage ticketId={Number(p.id)} /> },
  { path: '/reviews', render: () => <ReviewsPage /> },
  { path: '/models', render: () => <ModelsPage /> },
  { path: '/data-health', render: () => <DataHealthPage /> },
  { path: '/modules', render: () => <ModulesPage /> },
  { path: '/settings', render: () => <SettingsPage /> },
  { path: '/agents', render: () => <AgentPanel /> },
  { path: '/backtest', render: () => <BacktestPage /> },
  { path: '/pool', render: () => <PoolPage /> },
  { path: '/analysis', render: () => <AnalysisPage /> },
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
          {route.render(params)}
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

// ---- App root ----
export default function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <Layout>
          <PageOutlet />
        </Layout>
      </ToastProvider>
    </ThemeProvider>
  );
}
