# Module Maintenance Contract

These are maintenance rules for the current registry based application; they do not require a Python ModuleContract class.

1. Use the existing final module and panel registries for identities, dependencies and navigation. Reason: the runtime UI endpoints read those files.
2. Check real API, job, storage and frontend consumers before changing a module. Reason: modules are not independently discovered plugin packages.
3. Keep registry routes aligned with the explicit frontend route table. Reason: registry entries do not create React components or routes.
4. Respect required modules, safe-disable settings and active dependents. Reason: the module status endpoint rejects unsafe transitions.
5. Preserve historical snapshots, model references, tickets and audit records unless their data change is explicitly authorized. Reason: removing code does not remove the need to explain historical results.
6. Describe actual verification and applicable rollback steps. Reason: the repository has no universal per-module schema/API/job version or automatic rollback mechanism.
7. Preserve authentication and implemented recommendation review checks. Reason: hiding a panel or validating a manifest does not enforce backend access or publication approval.
