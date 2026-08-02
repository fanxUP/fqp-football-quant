import { type FormEvent, useState, useEffect } from 'react';
import { useAuth } from '../app/AuthContext';
import { useLanguage } from '../app/LanguageContext';

export default function LoginPage() {
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [visible, setVisible] = useState(false);
  const [showPw, setShowPw] = useState(false);
  const { login } = useAuth();
  const { translate } = useLanguage();

  useEffect(() => {
    // Entrance animation
    const t = setTimeout(() => setVisible(true), 100);
    return () => clearTimeout(t);
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!password) {
      setError(translate('请输入访问密码'));
      return;
    }
    setLoading(true);
    try {
      await login(password);
    } catch (err) {
      setError(err instanceof Error ? err.message : translate('登录失败'));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fqp-login-page">
      {/* Background image layer */}
      <div className="fqp-login-bg" />

      {/* Sun glow effect */}
      <div className="fqp-login-sun" />

      {/* Grass overlay */}
      <div className="fqp-login-grass" />

      {/* Login card */}
      <div className={`fqp-login-card${visible ? ' visible' : ''}`}>
        <form onSubmit={handleSubmit} className="fqp-login-form">
          <div className="fqp-login-field">
            <div className="fqp-login-input-wrap">
              <input
                type={showPw ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={translate('请输入访问密码')}
                autoFocus
                disabled={loading}
                className="fqp-login-input"
              />
              <button
                type="button"
                className="fqp-login-pw-toggle"
                onClick={() => setShowPw(!showPw)}
                tabIndex={-1}
              >
                {showPw ? '🙈' : '👁️'}
              </button>
            </div>
          </div>

          {error && <p className="fqp-login-error">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="fqp-login-button"
          >
            {loading ? translate('登录中...') : translate('登录')}
          </button>
        </form>
      </div>
    </div>
  );
}
