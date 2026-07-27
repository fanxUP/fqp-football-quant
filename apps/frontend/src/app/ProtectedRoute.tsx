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
