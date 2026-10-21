# P119 Design

## Problem
Password login can fail when an existing session cookie causes Redis cleanup to access a release marker outside the runtime ACL key selector, or when the ACL denies transactional commands.

## Decision
Keep session and release marker keys under `session:*`. Create the session keys atomically with the ACL-permitted `EVAL` script and `SETEX` operations. Keep the change limited to the auth implementation and its regression test.

## Compatibility and rollback
The previous server revision is `657d82d671fe0842c8c7c27c8cd85c9b509caa1e`. There are no database schema or dependency changes. A deployment rollback restores that revision through the approved server deploy runner.
