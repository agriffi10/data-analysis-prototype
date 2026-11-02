---
type: Decision
title: "A space named after a user finds that user's database, and a teardown touches only its own (2026-09-26)"
description: "**A space's Glue database and a user's personal one share ONE namespace under the bare name**, and a space may be named after a user. So the create **marks** the database it makes, refuses a name whose database exists unmarked as taken, and the teardown revokes on and drops **only a marked one** — `teardown.owns_database` is the one test all three read."
---

**Found by a data-loss audit of the control planes.** Post-confirmation makes a user's personal
Glue database under the username, and create-space makes a space's under the space name — one
namespace, and nothing stops a space being named after a user (the archive and table-share record
the same hazard for their own keys). The create treated `AlreadyExistsException` as a retry of
itself, so a space called `alice` adopted alice's personal database: tagged it and granted the
portal role on it. If that create then failed, or its owner deleted or forgot it while it was still
provisioning, the never-usable teardown revoked those grants and dropped **every table in alice's
catalog**, then the database. Anyone could aim it at any username; a user could do it to themselves.

**The create now marks its database** (`config.DATABASE_MARKER_KEY`, a Glue database parameter
naming the space), and on `AlreadyExistsException` reads it back: marked for this space is the
create's own earlier attempt and carries on; anything else refuses `name already taken`, before the
database is tagged or granted on. **The revoke and the drop read the same test**, and leave an
unmarked database exactly as it is. The one test is `teardown.owns_database`, for the same reason
`is_destroyable` is one predicate: complements written twice drift.

**The cost, accepted:** a space created before the marker is unmarked, so tearing one of those down
leaves its database behind as residue — against the alternative of guessing whose it is. A create
that FAILED before the marker existed is the sharp end of it: its database is unmarked, so the
owner's retry is refused as taken, and forgetting it leaves that database behind, so no later
create can take the name either. With no users on the plane yet that is a name, not data. **Not
closed here, and Andrew chose to split it off:** the entry doors (a space name that is a username,
and a username that is a space name, the second of which has post-confirmation adopt a space's
database and grant the new user on it), and whether a space tag naming a user's database reaches
that catalog through the portal role's shared-space Glue statement. Those are a security spec's.

## History

### 2026-09-26

- **Settled:** entered the register.
