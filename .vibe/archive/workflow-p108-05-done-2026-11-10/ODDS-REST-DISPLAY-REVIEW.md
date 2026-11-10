# Odds movement during sales rest review

Date: 2026-11-10

Independent read-only review of the odds movement changes on main.

## Result

PASS. No blocker, major issue, or release-stopping security finding.

## Findings

- Rest-time results require a future kickoff, an eligible pre-match status, and at least one saved snapshot for a canonical play type. Cancelled and already-started fixtures stay out of the current list.
- The odds index and the movement endpoint share the same current-match predicate, so the date selector count matches the displayed set.
- Open-sales filtering remains tied to the official selling status and open market. Historical dates keep their date filter and hourly sampling.
- The endpoint remains a read-only GET. SQL values remain bound parameters and the static play-type list comes from the project registry.
- The page labels the official rest window and shows the latest source snapshot time for each listed fixture.

## Scope

No schema migration, dependency, new service, scheduler change, or production data write.
