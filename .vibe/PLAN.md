# P107 aggregate candidate release readiness

This workflow verifies the already reconciled local P107/P138 candidate on the single `main` branch. It does not enlarge any completed slice budget.

- Baseline: `main` at `4a7a37aa57b885cc3ae332731b6a6e273dd49bff`.
- Scope: 51 mapped product/test paths. `uv.lock` is count-only, unowned, and excluded from staging.
- Candidate: accumulated P107 consumers/resource limits, prediction statistics rollup migration 131, and P138 prediction input cutoff changes.
- Release remains blocked until exact-head CI and a current production schema/data-copy migration rehearsal pass.
- Deployment is followed by read-only health, query/runtime evidence, and natural scheduled-run observation.
- No ordinary-model probability improvement is claimed; P104 exact-value consumption remains unproven.
