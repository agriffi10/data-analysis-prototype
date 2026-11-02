---
type: Decision
title: "The write gate mirrors each bucket's own Deny, and averaging them gets one case wrong"
description: "`isWriteLockedPrefix` takes the space kind, because personal Denies only the caller's root archive folder and shared Denies `archive` at any depth; the query-results and data-quality-reports refusals are separate exceptions."
---

`isWriteLockedPrefix` is the app's first rule about the prefix the user is STANDING in, as opposed
to a rule about a folder's name. It exists because IAM already denies writes beneath `archive/`, and
without a browser counterpart every attempt produces a bare `AccessDenied` for a rule this
application authored — the situation `undeletableRootFolderRefusal` exists to prevent for
`athenaresults/`.

**The two space buckets are denied differently**, and that asymmetry is structural rather than an
oversight:

- personal: `{bucket}/${aws:PrincipalTag/username}/archive/*` — anchored at the caller's own root,
  because in that bucket the prefix IS the principal tag;
- shared: `{bucket}/*/archive/*` — where the wildcard is the space slot, and **an S3 resource
  wildcard matches `/`**, so it reaches an `archive` folder at any depth.

Anchoring both at the root offers writes into a nested shared `archive/` that IAM refuses; applying
the any-depth rule to both refuses writes into a user's own `alice/backups/archive/` that IAM
permits. FR-004's criterion is both directions — "must not offer a write the policy refuses, and
must not refuse one it permits" — so the predicate takes the space kind. `archiveWriteLock.test.ts`
turns each `Resource` into a key matcher and runs the app's own predicate over the same keys;
deleting the shared branch reddens it (measured).

**The query results folder is the one deliberate exception to the second half, and it is a separate
predicate beside this one.** IAM permits a write beneath `system_settings/athenaresults/` and denies
the delete, so whatever a user writes there can never be removed — the folder marker's reason,
applied to a whole folder. `writeLockRefusal` refuses those writes in its own words and
`protected.assert_writable` refuses them at the object routes, which nothing legitimate writes
through: Athena delivers its results itself, under whichever role ran the query, and the browser
only copies them out. `isWriteLockedPrefix` and
`is_write_locked` still refuse only what the policy refuses, and the results rule is held against
its `DeleteObject` Deny by the same matchers, in both trees. **The data-quality reports folder is a
second exception, and it mirrors no Deny at all**: the plane reads its manifest back between verbs
from a key a caller can predict, so `assert_writable` refuses the root-anchored
`_data-quality-reports/` at the object routes, where only reads were ever legitimate.

**The refusal is `aria-disabled`, not `disabled`.** A `disabled` control is skipped by the tab order,
so its reason is reachable only by hovering — which is how "it's greyed out and I can't find out
why" happens. `Button.disabledReason` renders the reason as the accessible DESCRIPTION and swallows
the click, and deliberately does not put the text inside the button: content becomes part of the
accessible NAME, which every `GATED_SURFACES` row and journey test queries by.

## History

### 2026-08-12

- **Settled:** entered the register.
