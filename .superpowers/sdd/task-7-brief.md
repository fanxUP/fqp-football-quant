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