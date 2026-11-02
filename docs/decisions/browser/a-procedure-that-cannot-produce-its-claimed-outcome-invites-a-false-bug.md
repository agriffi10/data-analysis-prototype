---
type: Decision
title: "A procedure that cannot produce its claimed outcome invites a false bug report"
description: "A live-check script must describe a procedure that can produce its outcome, and one needing a raw ID token says so up front and keeps it out of shell commands; schema inference samples only the first key listed."
---

Two live-check scripts described impossible procedures, and one of them was followed and read as a
defect until the code was checked.

**Schema inference samples exactly ONE object — the first key in listing order**
(`sample_by_format.setdefault(fmt, key)`, and S3 lists lexicographically). A column added in a file
that sorts *later* is invisible **by design** and the refresh correctly says `already up to date`.
The fixture must name a file that **sorts first**.

**Two UI submits cannot contend for SPEC-157's lock.** Two submits 2 s apart — the floor two
pre-armed tabs allow — both returned independently, because a small table's refresh completes inside
that window. The check needs an SQS double-send or a several-hundred-object folder.

**And SPEC-173's marker check was unrunnable as written**, which is the third instance: the portal
issues **zero** `DeleteObject` against the marker (hidden by basename, folder refused client-side),
so the bucket-policy Deny — the layer the check exists to prove — was never exercised. Split into
two separately-numbered checks, because neither layer's result says anything about the other's.

**Any procedure needing a raw ID token says so up front**, says where it is read from, and says it
must not be pasted into a shell command — it is a live credential and it lands in history.

## History

### 2026-08-14

- **Settled:** entered the register.
