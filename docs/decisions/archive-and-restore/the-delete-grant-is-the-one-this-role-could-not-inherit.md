---
type: Decision
title: "The delete grant is the one this role could not inherit"
description: "The archive role may delete only on the two space buckets, with an explicit Deny on `system_settings/athenaresults/`, `user_settings/`, `system_settings/archive/` and any `DO_NOT_DELETE.txt`; `assert_deletable` checks the whole list first and fails loudly."
---

Every other plane's execution role carries a blanket `Deny s3:DeleteObject` from its first apply.
This one cannot, so the narrower property is written out: `DeleteObject` on the two SPACE buckets
only, plus an explicit **Deny** under `athenaresults/`, `user_settings/`, `archive/` and on any
`DO_NOT_DELETE.txt` at any depth (`*` matches `/`). A Deny rather than a narrower Allow, because an
explicit Deny beats every Allow — including one a later spec adds without reading the file.

IAM is the SECOND line of defence. The first is the gate; the third is
`arcommon.delete.assert_deletable`, which checks the whole list **before issuing anything**, so a
key the policy would refuse fails the run rather than stopping a deletion half way through — after
some of the user's data has already gone. It fails loudly rather than filtering: a silent filter
would delete a source the archive is missing objects from.

Review found that check accepting `alice/../bob/secrets.csv`, which starts with `alice/` and passed
a prefix-only test. S3 resolves nothing, so no cross-tenant delete followed; it is closed because a
containment rule that holds only while every consumer stays careful is not a rule, and this
consumer is the one that deletes. **Containment is both of `cpcommon.paths`' rules, everywhere.**

## History

### 2026-08-12

- **Settled:** entered the register.
