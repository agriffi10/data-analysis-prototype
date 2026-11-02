---
type: Decision
title: "No shared-space directory is published; suggestions come from your own cache (SPEC-158)"
description: "**No shared-space directory is published** — the share dialog suggests only spaces you belong to. A full list would be more useful and is declined as a disclosure with no equivalent."
---

`TableShareDialog`'s space entry suggests only the shared spaces the signed-in user belongs to,
read from the connections cache `useConnections` already fetches. **A complete list of every space
in the organisation would be strictly more useful, and it was declined.**

Strictly more useful because sharing a table to a space does **not** require membership —
`test_recipient_space_membership_not_required` pins that a space the sender does not belong to is a
valid target — so the suggestions cover less than the field accepts, on purpose. Membership is the
only thing that is waived: an emptied space keeps `status: "active"` and is still refused, because
`may_receive_share` wants an owner as well as a status. The cost of closing that gap is a **bulk**
disclosure, and the argument is about the bulk rather than about secrecy: a non-member can already
learn whether one named space exists by attempting a share and reading the refusal, which is the
existence oracle `docs/decisions/control-planes/` records as open on the transfer path and deliberately not
inherited. That is per-name, authenticated, logged, and it copies a table; a directory is every
space name in the organisation, free, to every signed-in user, and space names are user-chosen and
often descriptive (`acme_merger`, `q4_layoffs`). The username directory is not a precedent — a
username is already the S3 prefix, the principal tag and the Glue database name (see the entry
above). The trade was put to the user on 2026-08-05 and **declined in favour of suggesting only what
the user can already see.**

**Do NOT add a space directory "for symmetry with SPEC-146."** The absence is the decision. What
holds the line in the UI is that a space the user does not belong to **stays typeable and still
commits**, with a note that says it may exist and simply not be one of yours — worded that way
because this note is the one place a user could be misled into thinking the target was invalid.

Two consequences worth carrying:

- **The suggestion source is a prop, not a hook call** (`SuggestionSource = {status, search}`).
  `UsernameCombobox` reaching for `useUserDirectory` itself was the right reading with one source
  and the wrong one with two; a near-duplicate component would have been the alternative. A second
  source is the trigger to revisit that kind of deviation, not to fork.
- **A second source costs no request.** The space list is a query the app already makes for the
  Connections page and the Query rail, and the ranking is SPEC-147's `buildIndex`/`search`, which
  were never username-specific. No Lambda, no published document, no IAM, no env var, no new AWS
  call — a test asserts the space path issues none.

## History

### 2026-08-09

- **Settled:** SPEC-158.
