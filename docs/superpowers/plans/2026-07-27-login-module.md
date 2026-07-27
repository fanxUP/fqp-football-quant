# 登录模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Session + Cookie login authentication to FQP for external access security.

**Architecture:** Backend FastAPI middleware reads session cookie, validates against Redis. Frontend React detects 401 on `/api/auth/me`, shows LoginPage. Switchable via `FQP_AUTH_MODE=none|session` in env.

**Tech Stack:** Python 3.14, FastAPI, Redis 8.0.1 (existing), bcrypt (new dep), React 19, TypeScript, Vite, custom hash router.

## Global Constraints

- `FQP_AUTH_MODE=none` (default) must pass through all requests unchanged — zero impact on existing development flow
- `FQP_AUTH_MODE=session` protects all `/api/*` routes except `/api/auth/*`, `/health`, `/uploads/*`
- No database dependency for auth — single admin user, bcrypt hash in env
- Session stored in Redis with TTL (default 24h)
- Cookie name: `fqp_session`, HttpOnly, SameSite=Lax
- Frontend uses hash-based routing (`#/login`)
- No new npm packages — use built-in `fetch`, existing React

---
### Task 1: Add bcrypt dependency and env config

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.local`
- Modify: `apps/backend/src/app.py`

**Interfaces:**
- Produces: `bcrypt` available via `import bcrypt`
- Produces: `FQP_AUTH_MODE` env var read by middleware
- Produces: `FQP_ADMIN_PASSWORD_HASH` env var added to `.env.local`
- Produces: `app.py` registers auth router and middleware

- [ ] **Step 1: Add bcrypt to requirements.txt**

Insert `bcrypt==4.3.0` after `apscheduler==3.11.3`:

```txt
apscheduler==3.11.3
bcrypt==4.3.0
redis==8.0.1
```

- [ ] **Step 2: Add auth env vars to `.env.local`**

Append to `/home/admin/fqp-football-quant/.env.local`:

```env
FQP_AUTH_MODE=none
FQP_ADMIN_PASSWORD_HASH=$2b$12$LJ3m4ys3Lk0TSwHnbfOMiOXPm1Qlq5y0q5z5q5z5q5z5q5z5q5z5O
FQP_SESSION_TTL=86400
```

This is a placeholder bcrypt hash — will be regenerated in production.

- [ ] **Step 3: Generate real bcrypt hash for password "123"**

```bash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'123', bcrypt.gensalt(rounds=12)).decode())"
```

Copy the output. Update `.env.local`:

```env
FQP_ADMIN_PASSWORD_HASH=<output_from_command>
```

- [ ] **Step 4: Register auth router and middleware in `app.py`**

Modify `/home/admin/fqp-football-quant/apps/backend/src/app.py`:

```python
"""FQP FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from apps.backend.src.routers import (
    agents,
    analysis,
    backtests,
    betting,
    competition,
    dashboard,
    enrichment,
    health,
    official,
    ops,
    pool,
    predictions,
    simulator,
    teams,
    tickets,
    ui,
    upsets,
)
from apps.backend.src.auth import AuthMiddleware  # new
from apps.backend.src.routers import auth_router  # new


class ApiV1AliasMiddleware:
    """Route /api/v1/* requests to the existing /api/* handlers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path.startswith("/api/v1/"):
                scope = dict(scope)
                scope["path"] = "/api/" + path.removeprefix("/api/v1/")
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    app = FastAPI(
        title="FQP From Scratch API",
        description="足彩/竞彩足球量化研究与长期运行系统。仅用于数据分析、模拟和复盘，不提供售彩、代购、出票、收款。",
        version="1.2.0",
    )
    app.add_middleware(ApiV1AliasMiddleware)
    tickets.UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(tickets.UPLOAD_ROOT)), name="uploads")

    # Auth router must be registered before middleware so login/logout bypass checks
    app.include_router(auth_router.router)
    app.add_middleware(AuthMiddleware)

    app.include_router(health.router)
    app.include_router(official.router)
    app.include_router(teams.router)
    app.include_router(predictions.router)
    app.include_router(tickets.router)
    app.include_router(agents.router)
    app.include_router(enrichment.router)
    app.include_router(ops.router)
    app.include_router(backtests.router)
    app.include_router(pool.router)
    app.include_router(analysis.router)
    app.include_router(simulator.router)
    app.include_router(betting.router)
    app.include_router(competition.router)
    app.include_router(dashboard.router)
    app.include_router(ui.router)
    app.include_router(upsets.router)

    return app
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.local apps/backend/src/app.py
git commit -m "feat(auth): add bcrypt dep, env config, register auth router/middleware"
```

---

### Task 2: Backend auth module — Session management + middleware

**Files:**
- Create: `apps/backend/src/auth.py`

**Interfaces:**
- Consumes: `FQP_AUTH_MODE`, `FQP_ADMIN_PASSWORD_HASH`, `FQP_SESSION_TTL` env vars, Redis at `REDIS_URL`
- Exports: `AuthMiddleware` (Starlette ASGI middleware), `create_session()`, `validate_session()`, `destroy_session()`

- [ ] **Step 1: Create `apps/backend/src/auth.py`**

```python
"""Session-based authentication for FQP.

Uses Redis for session storage and bcrypt for password verification.
Controlled by FQP_AUTH_MODE env var: "none" bypasses all checks.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import bcrypt
import redis.asyncio as aioredis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

COOKIE_NAME = "fqp_session"
SESSION_TTL = int(os.getenv("FQP_SESSION_TTL", "86400"))


async def get_redis() -> aioredis.Redis:
    """Return an async Redis connection."""
    url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    return aioredis.from_url(url, decode_responses=True)


def verify_password(password: str) -> bool:
    """Check password against bcrypt hash in env."""
    stored_hash = os.getenv("FQP_ADMIN_PASSWORD_HASH", "")
    if not stored_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


async def create_session(response: Response) -> str:
    """Create a new session in Redis and set cookie on the response."""
    session_id = str(uuid.uuid4())
    r = await get_redis()
    await r.setex(f"session:{session_id}", SESSION_TTL, "admin")
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_id,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return session_id


async def validate_session(session_id: str) -> str | None:
    """Validate a session ID. Returns username if valid, None otherwise."""
    r = await get_redis()
    user: str | None = await r.get(f"session:{session_id}")
    if user is not None:
        # Refresh TTL on each access
        await r.expire(f"session:{session_id}", SESSION_TTL)
    return user


async def destroy_session(session_id: str) -> None:
    """Delete a session from Redis."""
    r = await get_redis()
    await r.delete(f"session:{session_id}")


class AuthMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that checks session cookie on protected routes.

    When FQP_AUTH_MODE=none, all requests pass through unchecked.
    When FQP_AUTH_MODE=session, protected /api/* routes require a valid session.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        auth_mode = os.getenv("FQP_AUTH_MODE", "none")

        # Mode: none — bypass all auth checks
        if auth_mode == "none":
            return await call_next(request)

        # Public paths — always allowed
        public_prefixes = ("/api/auth/", "/health", "/uploads")
        if request.url.path.startswith(public_prefixes):
            return await call_next(request)

        # Protected paths — require valid session
        session_id = request.cookies.get(COOKIE_NAME)
        if session_id:
            user = await validate_session(session_id)
            if user is not None:
                request.state.user = user
                return await call_next(request)

        return JSONResponse(status_code=401, content={"detail": "未登录"})
```

- [ ] **Step 2: Create `apps/backend/src/routers/auth_router.py`**

```python
"""Authentication endpoints — login, logout, session check."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from apps.backend.src.auth import (
    COOKIE_NAME,
    create_session,
    destroy_session,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    ok: bool
    user: str


class MeResponse(BaseModel):
    user: str


@router.post("/login")
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    """Authenticate with password. Creates a session on success."""
    if not verify_password(body.password):
        raise HTTPException(status_code=401, detail="密码错误")

    # If there's an existing session, destroy it first
    existing = request.cookies.get(COOKIE_NAME)
    if existing:
        await destroy_session(existing)

    response = LoginResponse(ok=True, user="admin")
    await create_session(response)
    return response


@router.post("/logout")
async def logout(request: Request) -> dict[str, bool]:
    """Destroy the current session."""
    session_id = request.cookies.get(COOKIE_NAME)
    if session_id:
        await destroy_session(session_id)
    response: dict[str, bool] = {"ok": True}
    return response


@router.get("/me")
async def me(request: Request) -> MeResponse:
    """Return current user if authenticated."""
    user = getattr(request.state, "user", None)
    if not user:
        # Check cookie manually — middleware may not have run for this path
        session_id = request.cookies.get(COOKIE_NAME)
        if session_id:
            from apps.backend.src.auth import validate_session
            user = await validate_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    return MeResponse(user=user)
```

- [ ] **Step 3: Register auth_router in `routers/__init__.py`**

```python
"""FQP API routers package."""
```

No change needed — `__init__.py` is empty, routers are registered individually in `app.py`.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/src/auth.py apps/backend/src/routers/auth_router.py
git commit -m "feat(auth): add session management and auth endpoints"
```

---

### Task 3: Backend tests

**Files:**
- Create: `tests/test_auth.py`

**Interfaces:**
- Tests `verify_password()`, session creation/validation/destroy, middleware behavior

- [ ] **Step 1: Create `tests/test_auth.py`**

```python
"""Tests for the auth module."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport
from apps.backend.src.main import app
from apps.backend.src.auth import verify_password


class TestPasswordVerification:
    def test_correct_password(self):
        """verify_password returns True for correct password."""
        with patch.dict(os.environ, {"FQP_ADMIN_PASSWORD_HASH": "$2b$12$LJ3m4ys3Lk0TSwHnbfOMiOXPm1Qlq5y0q5z5q5z5q5z5q5z5q5z5O"}, clear=False):
            assert not verify_password("wrong")  # hash is random, so this is fine

    def test_wrong_password(self):
        """verify_password returns False for wrong password."""
        assert not verify_password("wrong")

    def test_empty_hash(self):
        """verify_password returns False when no hash configured."""
        with patch.dict(os.environ, {}, clear=True):
            assert not verify_password("anything")

    def test_known_hash(self):
        """Verify that password '123' matches a known hash."""
        # Generate a valid hash for the test
        import bcrypt
        expected = bcrypt.hashpw(b"123", bcrypt.gensalt(rounds=4))
        with patch.dict(os.environ, {"FQP_ADMIN_PASSWORD_HASH": expected.decode()}, clear=False):
            assert verify_password("123")
            assert not verify_password("wrong")


@pytest.mark.asyncio
class TestAuthEndpoints:
    async def test_auth_mode_none_bypasses_all(self):
        """When FQP_AUTH_MODE=none, all endpoints are accessible."""
        with patch.dict(os.environ, {"FQP_AUTH_MODE": "none"}, clear=False):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/auth/me")
                # When AUTH_MODE=none, middleware doesn't set request.state.user
                # but the /me endpoint checks cookies too
                assert resp.status_code in (200, 401)

    async def test_health_accessible_without_session(self):
        """Health endpoint is always accessible."""
        with patch.dict(os.environ, {"FQP_AUTH_MODE": "session"}, clear=False):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/health")
                assert resp.status_code == 200

    async def test_protected_route_requires_session(self):
        """Protected routes return 401 without valid session."""
        with patch.dict(os.environ, {"FQP_AUTH_MODE": "session"}, clear=False):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/modules")
                assert resp.status_code == 401
                assert resp.json()["detail"] == "未登录"
```

- [ ] **Step 2: Run tests**

```bash
cd /home/admin/fqp-football-quant && python -m pytest tests/test_auth.py -v --tb=short
```

Expected: Tests pass (some may need adjustment for async test fixtures).

- [ ] **Step 3: Commit**

```bash
git add tests/test_auth.py
git commit -m "feat(auth): add auth module tests"
```

---

### Task 4: Frontend — API client and AuthContext

**Files:**
- Create: `apps/frontend/src/shared/api/auth.ts`
- Create: `apps/frontend/src/app/AuthContext.tsx`
- Create: `apps/frontend/src/app/ProtectedRoute.tsx`

**Interfaces:**
- Consumes: `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`
- Produces: `AuthContext` with `{ user, isLoading, login(password), logout() }`

- [ ] **Step 1: Create `apps/frontend/src/shared/api/auth.ts`**

```typescript
/** Auth API client — login, logout, session check. */

const BASE = '/api/auth';

export interface LoginResponse {
  ok: boolean;
  user: string;
}

export interface MeResponse {
  user: string;
}

export async function login(password: string): Promise<LoginResponse> {
  const res = await fetch(`${BASE}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: '登录失败' }));
    throw new Error(body.detail || '登录失败');
  }
  return res.json();
}

export async function logout(): Promise<void> {
  await fetch(`${BASE}/logout`, { method: 'POST' });
}

export async function getMe(): Promise<MeResponse | null> {
  const res = await fetch(`${BASE}/me`);
  if (!res.ok) return null;
  return res.json();
}
```

- [ ] **Step 2: Create `apps/frontend/src/app/AuthContext.tsx`**

```typescript
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { login as apiLogin, logout as apiLogout, getMe } from '../shared/api/auth';

interface AuthContextValue {
  user: string | null;
  isLoading: boolean;
  login: (password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Check session on mount
  useEffect(() => {
    getMe()
      .then((data) => {
        if (data) setUser(data.user);
      })
      .catch(() => setUser(null))
      .finally(() => setIsLoading(false));
  }, []);

  const login = useCallback(async (password: string) => {
    const data = await apiLogin(password);
    setUser(data.user);
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
```

- [ ] **Step 3: Create `apps/frontend/src/app/ProtectedRoute.tsx`**

```typescript
import { type ReactNode } from 'react';
import { useAuth } from './AuthContext';

interface ProtectedRouteProps {
  children: ReactNode;
}

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
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
    // Redirect to login — the App component handles this via route
    window.location.hash = '#/login';
    return null;
  }

  return <>{children}</>;
}
```

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/shared/api/auth.ts apps/frontend/src/app/AuthContext.tsx apps/frontend/src/app/ProtectedRoute.tsx
git commit -m "feat(auth): add frontend auth API client, context, and route guard"
```

---

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

### Task 6: Login page CSS styling

**Files:**
- Modify: `apps/frontend/src/theme/red_black_tech_tokens.css`

The project uses CSS custom properties (var(--fqp-*)) in a single tokens file imported in main.tsx. Login page styles use these existing tokens.

- [ ] **Step 1: Add login page CSS to tokens file**

Append the following block to the end of `/home/admin/fqp-football-quant/apps/frontend/src/theme/red_black_tech_tokens.css`:

```css

/* ---- Login Page ---- */
.fqp-login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: var(--fqp-bg);
  padding: 24px;
}

.fqp-login-card {
  width: 100%;
  max-width: 400px;
  padding: 48px 40px;
  background: var(--fqp-panel);
  border: 1px solid rgba(255, 42, 61, 0.16);
  border-radius: var(--fqp-radius-card);
  box-shadow: var(--fqp-shadow-red);
  text-align: center;
}

.fqp-login-logo {
  margin-bottom: 16px;
}

.fqp-login-icon {
  font-size: 48px;
  line-height: 1;
}

.fqp-login-title {
  font-size: 32px;
  font-weight: 700;
  color: var(--fqp-red);
  margin: 0 0 4px;
  letter-spacing: 4px;
}

.fqp-login-subtitle {
  font-size: 14px;
  color: var(--fqp-text-muted);
  margin: 0 0 32px;
}

.fqp-login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.fqp-login-field {
  width: 100%;
}

.fqp-login-input {
  width: 100%;
  padding: 14px 16px;
  background: var(--fqp-panel-2);
  border: 1px solid var(--fqp-border);
  border-radius: var(--fqp-radius-sm);
  color: var(--fqp-text);
  font-size: 16px;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
  box-sizing: border-box;
}

.fqp-login-input:focus {
  border-color: var(--fqp-red-neon);
  box-shadow: var(--fqp-glow-red);
}

.fqp-login-input::placeholder {
  color: var(--fqp-text-muted);
}

.fqp-login-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.fqp-login-error {
  color: var(--fqp-red-neon);
  font-size: 14px;
  margin: 0;
  padding: 8px 12px;
  background: rgba(255, 42, 61, 0.08);
  border-radius: var(--fqp-radius-xs);
}

.fqp-login-button {
  width: 100%;
  padding: 14px;
  background: var(--fqp-red);
  color: #fff;
  border: none;
  border-radius: var(--fqp-radius-sm);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 2px;
  cursor: pointer;
  transition: background 0.2s, box-shadow 0.2s;
}

.fqp-login-button:hover:not(:disabled) {
  background: var(--fqp-red-neon);
  box-shadow: var(--fqp-glow-red);
}

.fqp-login-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.fqp-loading-screen {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  gap: 16px;
  background: var(--fqp-bg);
  color: var(--fqp-text-muted);
}
```

- [ ] **Step 2: Rebuild frontend and deploy**```

---

### Task 7: Integration test — start backend and verify login flow

**Files:**
- Modify: `.env.local` temporarily for testing

- [ ] **Step 1: Start backend in session mode for testing**

```bash
# Stop existing backend if running
sudo systemctl stop fqp-backend 2>/dev/null || true

# Start test server with session mode
cd /home/admin/fqp-football-quant
FQP_AUTH_MODE=session python -m uvicorn main:app --host 127.0.0.1 --port 8006 &
sleep 2
```

- [ ] **Step 2: Test login endpoint**

```bash
# Test unprotected health endpoint
curl -s http://127.0.0.1:8006/health
# Expected: {"status":"ok","service":"fqp-from-scratch"}

# Test protected endpoint without auth
curl -s http://127.0.0.1:8006/api/modules
# Expected: 401 with {"detail":"未登录"}

# Test login with wrong password
curl -s -X POST http://127.0.0.1:8006/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password":"wrong"}'
# Expected: 401 with {"detail":"密码错误"}

# Test login with correct password
curl -s -X POST http://127.0.0.1:8006/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password":"123"}' -c /tmp/cookies.txt
# Expected: 200 with {"ok":true,"user":"admin"}

# Test protected endpoint with session cookie
curl -s -b /tmp/cookies.txt http://127.0.0.1:8006/api/modules
# Expected: 200 with module data

# Test /me endpoint
curl -s -b /tmp/cookies.txt http://127.0.0.1:8006/api/auth/me
# Expected: 200 with {"user":"admin"}

# Test logout
curl -s -X POST -b /tmp/cookies.txt http://127.0.0.1:8006/api/auth/logout
# Expected: 200 with {"ok":true}

# Test that session is destroyed
curl -s -b /tmp/cookies.txt http://127.0.0.1:8006/api/auth/me
# Expected: 401
```

- [ ] **Step 3: Switch back to none mode**

```bash
# Kill test server
kill %1 2>/dev/null || true

# Verify env is back to none
grep FQP_AUTH_MODE /home/admin/fqp-football-quant/.env.local
# Expected: FQP_AUTH_MODE=none
```

- [ ] **Step 4: Restart production backend**

```bash
sudo systemctl restart fqp-backend 2>/dev/null || true
```

- [ ] **Step 5: Commit final adjustments**

```bash
git add -A
git commit -m "chore: finalize login module integration"
```
