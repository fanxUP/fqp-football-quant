### Task 5: Frontend — LoginPage and route integration

**Files:**
- Create: `apps/frontend/src/pages/LoginPage.tsx`
- Modify: `apps/frontend/src/App.tsx`
- Modify: `apps/frontend/src/main.tsx`

**Interfaces:**
- Consumes: `AuthContext`, hash router
- Produces: Login page UI, auth-wrapped App

- [ ] **Step 1: Create `apps/frontend/src/pages/LoginPage.tsx`**

```typescript
import { type FormEvent, useState } from 'react';
import { useAuth } from '../app/AuthContext';

export default function LoginPage() {
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!password) {
      setError('请输入密码');
      return;
    }
    setLoading(true);
    try {
      await login(password);
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fqp-login-page">
      <div className="fqp-login-card">
        <div className="fqp-login-logo">
          <span className="fqp-login-icon">⚽</span>
        </div>
        <h1 className="fqp-login-title">FQP</h1>
        <p className="fqp-login-subtitle">足球预测量化系统</p>

        <form onSubmit={handleSubmit} className="fqp-login-form">
          <div className="fqp-login-field">
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="输入密码"
              autoFocus
              disabled={loading}
              className="fqp-login-input"
            />
          </div>

          {error && <p className="fqp-login-error">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="fqp-login-button"
          >
            {loading ? '登录中...' : '登 录'}
          </button>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Append login route to App.tsx routes**

Modify `/home/admin/fqp-football-quant/apps/frontend/src/App.tsx`:

Add import at top:
```typescript
import LoginPage from './pages/LoginPage';
```

Add route in the routes array (at the beginning):
```typescript
const routes = [
  { path: '/login', render: () => <LoginPage /> },
  { path: '/', render: () => <DashboardPage /> },
  // ... existing routes unchanged
];
```

Wrap PageOutlet with AuthContext in the App function:

```typescript
import { AuthProvider } from './app/AuthContext';

export default function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <AuthProvider>
          <Layout>
            <PageOutlet />
          </Layout>
        </AuthProvider>
      </ToastProvider>
    </ThemeProvider>
  );
}
```

Wait — this approach wraps everything including the login page. The login page doesn't need the Layout. Let me adjust:

Instead, let the LoginPage be outside Layout. The App should be:

```typescript
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

function AppContent() {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="fqp-loading-screen">
        <div className="fqp-loading-spinner" />
        <p>加载中...</p>
      </div>
    );
  }

  // Not logged in — render login page without Layout
  if (!user) {
    return <PageOutlet />;
  }

  // Logged in — normal app with Layout
  return (
    <Layout>
      <PageOutlet />
    </Layout>
  );
}
```

This keeps the login page outside the sidebar layout.

Now I need to make the login route always resolve to LoginPage, and handle the redirect when protected routes are accessed without auth. But since our hash router is simple, let me instead check in the route handler whether the user is authenticated.

Actually, the simpler approach is: the login page is just a normal route. The `AppContent` component checks auth state. If not logged in, it renders pages (including LoginPage). The login page itself is rendered without Layout. Other pages would also render without Layout if not logged in — but since they're not reachable (hash would be wrong), it's fine.

And for protected routes (non-login pages) when not logged in, I should redirect. Let me add a redirect in AppContent:

```typescript
function AppContent() {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return <LoadingScreen />;
  }

  // Get current path from hash
  const currentPath = window.location.hash.replace(/^#/, '') || '/';

  if (!user && currentPath !== '/login') {
    // Redirect to login
    window.location.hash = '#/login';
    // Show empty while redirecting
    return null;
  }

  if (!user) {
    // On login page — no Layout
    return <PageOutlet />;
  }

  // Logged in — normal app with Layout
  return (
    <Layout>
      <PageOutlet />
    </Layout>
  );
}
```

Wait, but the `useRouter` is outside the AppContent — it's in `PageOutlet`. Let me check the flow again.

In the existing code, App renders Layout > PageOutlet. PageOutlet uses `useRouter()` from the custom router, which internally listens to hashchange events.

The router is initialized in App.tsx:
```typescript
createRouter(routes);
```

This sets up the hashchange listener and the route table. The `useRouter()` hook returns `{ currentPath, params, navigate }`.

So I need to integrate auth into App.tsx around the existing Layout + PageOutlet pattern. Let me restructure:

```typescript
function AppContent() {
  const { user, isLoading } = useAuth();

  return user ? (
    <Layout>
      <PageOutlet />
    </Layout>
  ) : (
    <PageOutlet />  // Will show LoginPage when on /login, redirect otherwise
  );
}
```

And in the redirect logic... hmm, I can't easily redirect within AppContent because I don't have the router's navigate here. I could use the raw hash approach.

Actually, the simplest approach: ProtectedRoute component wraps the Layout children check. No, it's simpler to just check in AppContent and use `window.location.hash`.

Let me keep it simple and practical:

```typescript
function AppContent() {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="fqp-loading-screen">
        <div className="fqp-loading-spinner" />
        <p>加载中...</p>
      </div>
    );
  }

  if (!user) {
    // Only allow /login route when not authenticated
    const path = window.location.hash.replace(/^#/, '') || '/';
    if (path !== '/login') {
      window.location.hash = '#/login';
    }
    return <PageOutlet />;
  }

  return (
    <Layout>
      <PageOutlet />
    </Layout>
  );
}
```

This is clean and practical. Let me finalize the App.tsx modifications.

- [ ] **Step 3: Modify `App.tsx`**

Replace the content of `/home/admin/fqp-football-quant/apps/frontend/src/App.tsx`:

```typescript
import { createRouter, navigate as routerNavigate, useRouter } from './core/router';
import { ThemeProvider } from './app/ThemeContext';
import { ToastProvider } from './shared/components/Toast';
import { AuthProvider, useAuth } from './app/AuthContext';
import Layout from './app/layout/Layout';
import LoadingSpinner from './shared/components/LoadingSpinner';
import LoginPage from './pages/LoginPage';

// Lazy-load all pages
import { lazy, Suspense } from 'react';

const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const MatchesPage = lazy(() => import('./pages/MatchesPage'));
const MatchDetailPage = lazy(() => import('./pages/MatchDetailPage'));
const RecommendationDetailPage = lazy(() => import('./pages/RecommendationDetailPage'));
const ModelsPage = lazy(() => import('./pages/ModelsPage'));
const DataHealthPage = lazy(() => import('./pages/DataHealthPage'));
const EventsPage = lazy(() => import('./pages/EventsPage'));
const ModulesPage = lazy(() => import('./pages/ModulesPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const AgentPanel = lazy(() => import('./pages/AgentPanel'));
const BacktestPage = lazy(() => import('./pages/BacktestPage'));
const PoolPage = lazy(() => import('./pages/PoolPage'));
const AnalysisPage = lazy(() => import('./pages/AnalysisPage'));
const BettingCenterPage = lazy(() => import('./pages/BettingCenterPage'));
const OddsMovementPage = lazy(() => import('./pages/OddsMovementPage'));
const UpsetsPage = lazy(() => import('./pages/UpsetsPage'));

function RedirectTo({ path, text = '正在进入页面...' }: { path: string; text?: string }) {
  const { useEffect } = require('react');
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
```

Wait, I used `require('react')` inside a component which is not great. Let me fix the RedirectTo to use the import that's already there.

Looking at the original code, it imports `useEffect` from react at the top of the file. Let me add it back:

```typescript
import { lazy, Suspense, useEffect } from 'react';
```

And the RedirectTo fixed:

```typescript
function RedirectTo({ path, text = '正在进入页面...' }: { path: string; text?: string }) {
  useEffect(() => {
    routerNavigate(path);
  }, [path]);
  return <LoadingSpinner text={text} size="lg" />;
}
```

- [ ] **Step 4: Build frontend**

```bash
cd /home/admin/fqp-football-quant/apps/frontend && npm run build
```

Expected: Build succeeds, output goes to `dist/`.

- [ ] **Step 5: Deploy to web root**

```bash
cp -r /home/admin/fqp-football-quant/apps/frontend/dist/* /var/www/fqp/
```

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/App.tsx apps/frontend/src/pages/LoginPage.tsx
git commit -m "feat(auth): add login page and auth-aware app routing"
```

---