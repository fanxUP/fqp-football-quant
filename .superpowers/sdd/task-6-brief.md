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