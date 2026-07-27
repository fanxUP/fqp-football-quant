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