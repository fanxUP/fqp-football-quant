# Task 3 Report: Backend Tests for Auth Module

## Test Results

**7 passed, 0 failed**

| Test | Status |
|------|--------|
| `TestPasswordVerification::test_random_hash_rejects_wrong_password` | PASSED |
| `TestPasswordVerification::test_wrong_password` | PASSED |
| `TestPasswordVerification::test_empty_hash` | PASSED |
| `TestPasswordVerification::test_known_hash` | PASSED |
| `TestAuthEndpoints::test_auth_mode_none_bypasses_all` | PASSED |
| `TestAuthEndpoints::test_health_accessible_without_session` | PASSED |
| `TestAuthEndpoints::test_protected_route_requires_session` | PASSED |

## Adjustments Made

1. **Renamed `test_correct_password` to `test_random_hash_rejects_wrong_password`** — the original name was misleading since the test verifies a random hash rejects "wrong", not that a correct password matches.

2. **Fixed import path** — the brief's test code imported `from apps.backend.src.main import app`, but the `main.py` module lives at the project root, not inside `apps/backend/src/`. Changed to `from main import app`, which works with pytest's `pythonpath = ["."]` config.

3. **Installed `pytest-asyncio`** — required for the `@pytest.mark.asyncio` decorator used by `TestAuthEndpoints`.

## Issues Encountered

- `pytest-asyncio` was not installed; had to install it via `pip install pytest-asyncio`.
- Built-in `apps` module cannot be found as `apps.backend.src.main` since that path doesn't exist.

## Commit Hash

`9a91728fe1aafc1eb071c766eff81f4c24a55b45`

STATUS: DONE
