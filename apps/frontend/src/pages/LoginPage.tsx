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
