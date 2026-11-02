---
type: Decision
title: "Member roster for members (SPEC-075)"
description: "Every member sees a read-only roster, owner first, fanned out to each member's cache with the same join-status projection the owner sees; non-owners get no management power and no new IAM."
---

SPEC-053's member-privacy stance is **reversed** — every member sees a **read-only** roster (owner tagged + first, same `Member[]` join-status projection the owner sees), via "View members" on their Connections card. `cache.write_roster_to_all` fans the roster out to the owner + every member on add/remove/leave (best-effort per member, CAS-safe); member entries now carry `members` too. No management power for non-owners; no new IAM (orchestrator already writes every user's cache). Legacy member entries backfill on the next membership change.

## History

### 2026-07-03

- **Settled:** SPEC-075.
