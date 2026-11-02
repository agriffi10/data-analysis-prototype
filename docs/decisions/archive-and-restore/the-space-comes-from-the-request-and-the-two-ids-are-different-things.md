---
type: Decision
title: "The space comes from the request, and the two ids are different things"
description: "Restore authorization uses the space the route names, so another space's archive is plain `archive_not_found`; `requestId` must differ from `archiveId`, and the pasted id passes the one UUID regex and is lowercased."
---

Authorization is a question about the space the user's route names (SPEC-113's rule), never about
whatever the archive claims — so an archive belonging to another space resolves to an empty prefix
and is simply **not found**. `archive_not_found` therefore never distinguishes "never existed" from
"not yours"; the difference is an existence oracle over other people's archives.

`requestId` ≠ `archiveId` is enforced rather than conventional. The run and the archive are
different things: a refused restore must be re-submittable under a new run id, and a second attempt
at one archive is a new request rather than a duplicate of the first. A producer that conflates them
will do it on every request, and the symptom would surface only under a retry.

The pasted id is matched against `arcommon.paths`' **one** UUID regex before it is concatenated into
anything — the same rule `validated_request_id` uses, differing only in the refusal's wording,
because a second and laxer copy would be a second door into the same key. It is lowercased, so a
receipt retyped in capitals still resolves the prefix the archive was written under.

## History

### 2026-08-12

- **Settled:** entered the register.
