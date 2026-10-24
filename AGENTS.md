# FQP Agent Instructions

These rules apply to automated coding agents working in this repository.

## Git branch policy

1. `main` is the only permitted project branch. Perform project changes sequentially in the existing `main` checkout. Reason: this is a single-developer project, and parallel topic branches have created avoidable integration work.
2. Do not create, switch to, or push feature, fix, release, or task branches. Do not create additional worktrees to isolate implementation branches. Reason: keeping one development line avoids branch drift and repeated merges.
3. If the current checkout is not `main`, do not create another branch or rewrite history. Inspect and report the checkout state, then continue only from the existing `main` checkout. Reason: an unexpected checkout must not silently expand the branch set.
4. Keep implementation work sequential and scoped; parallel agents may perform read-only research or review, but only one writer may modify the project checkout at a time. Reason: shared edits in a single branch need one clear owner.
5. Existing non-`main` branch references are legacy cleanup items, not permission to use them. Do not delete local or remote branches unless branch cleanup is explicitly requested. Reason: deleting a reference can discard reachable work and is a separate operation from setting the development policy.
6. Before editing, check the current branch and working-tree changes. Preserve user changes and do not switch branches to get around them. Reason: uncommitted work may belong to the user.

## Project changes

- Read the relevant implementation and current project documentation before changing behavior.
- Follow the user's task-specific authorization for tests, commits, pushes, merges, and deployments.
- Report actual changes, verification evidence, and any remaining limitations.
