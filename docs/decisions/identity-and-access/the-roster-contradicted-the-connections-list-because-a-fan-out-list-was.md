---
type: Decision
title: "The roster contradicted the connections list because a fan-out list was missing one verb"
description: "`acknowledge-membership` fans the roster out like add, remove and leave, and that fan-out cannot fail the run because the registry write has already committed; the browser renders the reader's own row `Active` regardless."
---

For one membership, at one moment, the app stated two things: the connections row read
`livecheck_0814a | Member | Active`, and the roster one click away read `agriffith | Pending` under
*"A Pending member has been invited but hasn't signed in yet."* The reader of that sentence **was**
the member, and they **had** signed in.

Neither settled decision is wrong. SPEC-073's `acknowledge-membership` flips pending→active and
writes the **owner's** projection; SPEC-075's `cache.write_roster_to_all` fans out on
**add/remove/leave** — a list that does not include acknowledge. So every member's copy, including
the acknowledging member's own, stayed frozen at add time, and the roster is the **only**
member-facing view of who is in a space.

Closed on both sides. The verb now fans out, and **the fan-out cannot fail the run**: the registry
write is the consistency point and has already committed, so a raise would fail the execution, and
the retry would find the member already acknowledged, no-op, and never write the caches at all —
turning a recoverable stale roster into a permanent one. In the browser, `displayedMemberStatus`
renders the reader's own row `Active` regardless, and the explanatory sentence renders **only when a
row it describes is on screen**, which closes the window before the fan-out lands.

## History

### 2026-08-14

- **Settled:** entered the register.
