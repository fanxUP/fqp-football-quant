# Pi model access

STANDARD implementation with STRICT credential boundaries. User chose direct Pi integration.

Python remains the authenticated application boundary and encrypted PostgreSQL credential owner. A server-only Node 24 JSON-lines subprocess imports pinned pi-ai 1.1.0 for provider/model catalogs, completion, OAuth login and refresh. Credentials travel over stdin/stdout pipes, never command arguments, browser storage or files. No public Node service or coding-agent tools are installed.

Existing provider codes, encrypted API keys, base URLs and agent bindings remain valid. Additive SQL extends provider configs with API choice, auth mode and encrypted OAuth credential. Pi built-ins supply model metadata; custom compatible endpoints retain explicit protocol selection. OAuth availability comes from Pi provider capabilities. Login sessions are short lived, limited, cancellable, bound to the initiating authenticated session, and require the user to complete upstream login. Token refresh serializes on the provider database row.

UI follows connect -> choose model -> verify -> bind. Search suppliers and models, show context/input/reasoning capabilities, expose supported login choices and progress. Existing visual tokens and mobile layout retained.

No financial changes, automatic model purchases, backup changes, betting agent activation or production deployment in this implementation task. Adding one server package is required to use Pi itself; existing Python HTTP transport cannot provide its runtime or catalog. MIT package, exact version and lockfile; removal reverts transport and additive fields can remain.
