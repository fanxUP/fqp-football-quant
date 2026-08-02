"""FQP API entry point — thin wrapper around the app factory.

The app object is created at module level so uvicorn can discover it:
    uvicorn main:app --host 127.0.0.1 --port 8080
"""

from __future__ import annotations

from apps.backend.src.app import create_app

app = create_app()
