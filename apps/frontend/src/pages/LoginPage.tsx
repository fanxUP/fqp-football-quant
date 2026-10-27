import { type FormEvent, useState } from 'react';
import { useAuth } from '../app/AuthContext';
import { useLanguage } from '../app/LanguageContext';

export default function LoginPage() {
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showPw, setShowPw] = useState(false);
  const { login } = useAuth();
  const { translate } = useLanguage();

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
      <div className="fqp-login-bg" aria-hidden="true" />
      <div className="fqp-login-intro">
        <span className="fqp-login-wordmark">FQP</span>
        <h1>{translate('足球量化研究工作台')}</h1>
        <p>{translate('聚合比赛、模型与赛前证据，让每一次判断都有据可循。')}</p>
        <div className="fqp-login-caption">FOOTBALL · DATA · INSIGHT</div>
      </div>
      <div className="fqp-login-card">
        <h2>{translate('登录工作台')}</h2>
        <p>{translate('输入访问密码，继续你的足球研究。')}</p>
        <form onSubmit={handleSubmit} className="fqp-login-form">
          <div className="fqp-login-field">
            <label className="fqp-label" htmlFor="access-password">{translate('访问密码')}</label>
            <div className="fqp-login-input-wrap">
              <input
                id="access-password"
                type={showPw ? 'text' : 'password'}
                autoComplete="current-password"
                aria-invalid={Boolean(error)}
                aria-describedby={error ? 'login-error' : undefined}
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
                aria-label={translate(showPw ? '隐藏密码' : '显示密码')}
                aria-pressed={showPw}
              >
                <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" />
                  {showPw && <path d="m3 3 18 18" />}
                </svg>
              </button>
            </div>
          </div>

          {error && <p id="login-error" role="alert" className="fqp-login-error">{error}</p>}

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
