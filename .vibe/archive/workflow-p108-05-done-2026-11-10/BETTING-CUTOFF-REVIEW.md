# Betting-center cutoff fallback review

- Scope: `apps/backend/src/routers/simulator.py` and `tests/test_api/test_simulator_matches.py`.
- Result: independent read-only follow-up review passed; no blocking finding remains.
- Initial minor finding: cutoff evidence could be present only in a nested odds or pool node.
- Resolution: the query rejects a match if a nonempty `poolCloseDate` or `poolCloseTime` occurs anywhere in official raw JSON; JSONPath edge regressions cover `oddsList` and direct pool nodes.
- Guardrails reviewed: parameterized, read-only SQL; recent official selling status; future kickoff; recent same-source odds; live pool status; existing single/pass permissions retained.
