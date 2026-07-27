import { useState } from 'react';
import Card from '../../shared/components/Card';
import { toast } from '../../shared/components/Toast';

export default function PasswordChangePanel() {
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const reset = () => {
    setOldPassword('');
    setNewPassword('');
    setConfirmPassword('');
  };

  const handleSubmit = async () => {
    if (newPassword !== confirmPassword) {
      toast.warning('两次输入的新密码不一致');
      return;
    }
    if (newPassword.length < 4) {
      toast.warning('密码至少4位');
      return;
    }
    setLoading(true);
    try {
      const res = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
      });
      if (!res.ok) {
        const data = await res.json();
        toast.warning(data.detail || '修改失败');
        return;
      }
      toast.success('密码已修改');
      reset();
    } catch {
      toast.warning('网络错误，请重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="local-settings-panel" aria-labelledby="password-change-title">
      <div className="local-settings-heading">
        <h2 id="password-change-title">修改密码</h2>
        <p>更新管理员登录密码。</p>
      </div>
      <div className="local-settings-grid">
        <Card title="管理员密码">
          <label className="fqp-label" htmlFor="old-password">原密码</label>
          <input
            id="old-password"
            className="fqp-input"
            type="password"
            value={oldPassword}
            onChange={(e) => setOldPassword(e.target.value)}
            placeholder="输入原密码"
          />
          <label className="fqp-label" htmlFor="new-password" style={{ marginTop: 12 }}>新密码</label>
          <input
            id="new-password"
            className="fqp-input"
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="至少4位"
          />
          <label className="fqp-label" htmlFor="confirm-password" style={{ marginTop: 12 }}>确认新密码</label>
          <input
            id="confirm-password"
            className="fqp-input"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder="再次输入新密码"
          />
          <div className="local-settings-actions" style={{ marginTop: 16 }}>
            <button type="button" className="fqp-btn fqp-btn-primary" onClick={handleSubmit} disabled={loading}>
              {loading ? '修改中…' : '修改密码'}
            </button>
          </div>
        </Card>
      </div>
    </section>
  );
}
