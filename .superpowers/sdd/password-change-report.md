# Password Change Feature Report

## Summary
Added a password change feature to the FQP login module with a backend API endpoint and frontend UI.

## Backend Changes
- **File**: `apps/backend/src/routers/auth_router.py`
- Added `import os`
- Added `ChangePasswordRequest` Pydantic model (fields: `old_password`, `new_password`)
- Added `POST /api/auth/change-password` endpoint
  - Validates old password against the stored bcrypt hash
  - Requires new password to be at least 4 characters
  - Hashes new password with bcrypt (12 rounds)
  - Updates `.env.local` file directly with the new hash
  - Returns `{"ok": true}` on success

## Frontend Changes
- **New file**: `apps/frontend/src/pages/settings/PasswordChangePanel.tsx`
  - Three fields: old password, new password, confirm password
  - Uses existing `Card`, `fqp-label`, `fqp-input`, `fqp-btn` classes for theme consistency
  - Shows toast notifications for success/error
  - Calls `POST /api/auth/change-password`
- **Modified**: `apps/frontend/src/pages/SettingsPage.tsx`
  - Added import and rendering of `PasswordChangePanel`

## Testing
- Endpoint returns `401` with `"原密码错误"` for incorrect old password
- Endpoint returns `400` with `"密码至少4位"` for short new passwords
- Successful password change confirmed: `.env.local` updated with new bcrypt hash
- TypeScript compilation: clean (no errors)

## Commit
- Hash: `50c4d9d`
- Message: `feat(auth): add password change endpoint and UI`
