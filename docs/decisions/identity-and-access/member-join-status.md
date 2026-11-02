---
type: Decision
title: "Member join status (SPEC-073)"
description: "Join status is an `acknowledged` list beside `members`, flipped to active by the member-only `acknowledge-membership` verb; it is display and bookkeeping only, because access is granted at add time."
---

The owner projection carries a per-member `pending`/`active` chip. Membership stays `members: string[]` (source of truth in the registry); join status is a separate `acknowledged: string[]` list — a legacy record without it reads as all-active (back-compat). A **seventh verb `acknowledge-membership`** (member-only, idempotent, same shared `orchestrator` role) flips pending→active; the browser enqueues it once/session when a member resolves a shared space (`useAcknowledgeMembership` from `FilesPage`). Display + bookkeeping only — access is still granted at add time.

## History

### 2026-07-03

- **Settled:** SPEC-073.
