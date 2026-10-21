import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import {
  DeploymentChangedError,
  getDeploymentVersion,
  login as apiLogin,
  logout as apiLogout,
  getMe,
} from '../shared/api/auth';

const RELEASE_CHECK_INTERVAL_MS = 30_000;
const RELEASE_RELOAD_PARAM = '_fqp_release';

interface AuthContextValue {
  user: string | null;
  isLoading: boolean;
  deploymentUpdateRequired: boolean;
  isUpdatingForDeployment: boolean;
  login: (password: string) => Promise<void>;
  logout: () => Promise<void>;
  confirmDeploymentUpdate: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [deploymentUpdateRequired, setDeploymentUpdateRequired] = useState(false);
  const [isUpdatingForDeployment, setIsUpdatingForDeployment] = useState(false);
  const observedReleaseId = useRef<string | null>(null);
  const latestReleaseId = useRef<string | null>(null);
  const updatingRef = useRef(false);

  const requireDeploymentUpdate = useCallback((releaseId: string | null) => {
    if (releaseId) latestReleaseId.current = releaseId;
    setUser(null);
    setDeploymentUpdateRequired(true);
  }, []);

  // Check the current release and session before mounting protected pages.
  useEffect(() => {
    let mounted = true;
    const pageUrl = new URL(window.location.href);
    if (pageUrl.searchParams.has(RELEASE_RELOAD_PARAM)) {
      pageUrl.searchParams.delete(RELEASE_RELOAD_PARAM);
      window.history.replaceState(
        window.history.state,
        '',
        `${pageUrl.pathname}${pageUrl.search}${pageUrl.hash}`,
      );
    }

    async function initialize() {
      try {
        const deployment = await getDeploymentVersion();
        if (mounted) {
          observedReleaseId.current = deployment.releaseId;
          latestReleaseId.current = deployment.releaseId;
        }
      } catch {
        // Authentication still gets checked if the release endpoint is temporarily unavailable.
      }

      try {
        const data = await getMe();
        if (mounted) setUser(data?.user ?? null);
      } catch (error) {
        if (mounted && error instanceof DeploymentChangedError) {
          requireDeploymentUpdate(latestReleaseId.current);
        } else if (mounted) {
          setUser(null);
        }
      } finally {
        if (mounted) setIsLoading(false);
      }
    }

    void initialize();
    return () => {
      mounted = false;
    };
  }, [requireDeploymentUpdate]);

  // Poll while signed in so an already-open page notices a server deployment.
  useEffect(() => {
    if (isLoading || !user || deploymentUpdateRequired) return;
    let active = true;
    let checking = false;

    const checkRelease = async () => {
      if (!active || checking || document.visibilityState === 'hidden') return;
      checking = true;
      try {
        const deployment = await getDeploymentVersion();
        if (!active) return;
        const releaseId = deployment.releaseId;
        latestReleaseId.current = releaseId;

        if (observedReleaseId.current && releaseId !== observedReleaseId.current) {
          requireDeploymentUpdate(releaseId);
          return;
        }

        if (!observedReleaseId.current) {
          try {
            const session = await getMe();
            if (!active) return;
            observedReleaseId.current = releaseId;
            if (!session) setUser(null);
          } catch (error) {
            if (active && error instanceof DeploymentChangedError) {
              requireDeploymentUpdate(releaseId);
            }
            // Keep the baseline unset on transient errors so the next poll
            // retries the session check before accepting this release.
          }
        }
      } catch {
        // A failed version check does not log users out; the next poll retries.
      } finally {
        checking = false;
      }
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') void checkRelease();
    };
    const timer = window.setInterval(() => void checkRelease(), RELEASE_CHECK_INTERVAL_MS);
    document.addEventListener('visibilitychange', onVisibilityChange);
    void checkRelease();

    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [deploymentUpdateRequired, isLoading, requireDeploymentUpdate, user]);

  const login = useCallback(async (password: string) => {
    const data = await apiLogin(password);
    // The initial version may have been read before deployment on a login page
    // left open in another tab. Recheck this session against the live release.
    observedReleaseId.current = null;
    latestReleaseId.current = null;
    setUser(data.user);
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  const confirmDeploymentUpdate = useCallback(async () => {
    if (updatingRef.current) return;
    updatingRef.current = true;
    setIsUpdatingForDeployment(true);
    try {
      await apiLogout();
    } catch {
      // The server already rejects this session; continue to the refreshed login page.
    }

    setUser(null);
    const nextUrl = new URL(window.location.href);
    nextUrl.searchParams.set(RELEASE_RELOAD_PARAM, latestReleaseId.current ?? String(Date.now()));
    nextUrl.hash = '/login';
    window.location.replace(nextUrl.toString());
  }, []);

  return (
    <AuthContext.Provider value={{
      user,
      isLoading,
      deploymentUpdateRequired,
      isUpdatingForDeployment,
      login,
      logout,
      confirmDeploymentUpdate,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
