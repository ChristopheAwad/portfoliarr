# Roadmap status bookkeeping for #18 and #22

## Status and scope

Roadmap status correction only. No app code, tests, or Android changes.
#18 (Ledger Quick Sell) shipped as PR #65 on 2026-09-21. #22 (In-App
Version Display) shipped as PR #72 on 2026-09-22. PR #72 stamped #18
with its own PR number when it added #22, and left #22 as
`Status: in progress`. This fix corrects both rows.

## Approved behavior

- #18 reads `shipped 2026-09-21 (PR #65)`.
- #22 reads `shipped 2026-09-22 (PR #72)`.
- No IDs are renumbered or deleted; no other roadmap rows change.

## Verification and shipping

Both status lines are corrected. The full `python -m pytest` suite passed
(903 tests). No GUI check is needed for this docs-only change. The user
approved the plan and requested a PR; commit and push are authorized.

## Files

`feature.md`, `roadmap.md`.
