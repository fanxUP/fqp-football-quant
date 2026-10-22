# P119 Design

## Problem
Password login can fail when an existing session cookie causes Redis cleanup to access a release marker outside the runtime ACL key selector, or when the ACL denies transactional commands.

## Decision
Keep session and release marker keys under `session:*`. Create the session keys atomically with the ACL-permitted `EVAL` script and `SETEX` operations. Keep the change limited to the auth implementation and its regression test.

## Compatibility and rollback
The previous server revision is `657d82d671fe0842c8c7c27c8cd85c9b509caa1e`. There are no database schema or dependency changes. A deployment rollback restores that revision through the approved server deploy runner.

# P120 Design

## Problem
The backend and worker release can succeed while Nginx continues serving the old frontend entry page or lacks the hashed assets referenced by the new entry page.

## Decision
Move the publisher into a small Python module so the filesystem safety rules can be exercised against temporary directories. Keep the production root fixed at `/var/www/fqp`. Validate the source tree and entry point, publish non-entry assets with same-directory temporary files and atomic replacement, verify every local root-relative JavaScript/CSS reference by SHA-256, then switch `index.html` last. Keep old files so browser tabs that still reference older hashed assets continue to work.

## Failure handling
The deployment runner marks publication as attempted before invoking the publisher. On error it checks out and rebuilds the prior revision, republishes its assets, and restores service health. If the old frontend cannot be restored, stop Nginx and report `ROLLBACK_REQUIRED`.

## Compatibility
Only the Nginx static file tree and the deploy runner change. No database migration, application API change or runtime package change is needed. The previous production revision recorded by PR #24 is `f393e9ae1aacae5d145665bf47f402bfb3131ce6`.
