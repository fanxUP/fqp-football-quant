import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LoginPage from './LoginPage';

const { login } = vi.hoisted(() => ({ login: vi.fn() }));
vi.mock('../app/AuthContext', () => ({ useAuth: () => ({ login }) }));

describe('LoginPage', () => {
  beforeEach(() => login.mockReset());

  it('labels the password and supports keyboard access to visibility', async () => {
    const user = userEvent.setup();
    render(<LoginPage />);
    const password = screen.getByLabelText('访问密码');
    expect(password).toHaveAttribute('autocomplete', 'current-password');
    await user.type(password, 'local-fixture');
    await user.tab();
    expect(screen.getByRole('button', { name: '显示密码' })).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(password).toHaveAttribute('type', 'text');
    expect(password).toHaveValue('local-fixture');
    expect(screen.getByRole('button', { name: '隐藏密码' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('keeps authentication errors associated with the field and allows retry', async () => {
    const user = userEvent.setup();
    login.mockRejectedValueOnce(new Error('样本登录错误')).mockResolvedValueOnce(undefined);
    render(<LoginPage />);
    const password = screen.getByLabelText('访问密码');
    await user.type(password, 'local-fixture');
    await user.click(screen.getByRole('button', { name: /^登录$/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('样本登录错误');
    expect(password).toHaveAttribute('aria-invalid', 'true');
    expect(password).toHaveAttribute('aria-describedby', 'login-error');
    await user.click(screen.getByRole('button', { name: /^登录$/ }));
    expect(login).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
