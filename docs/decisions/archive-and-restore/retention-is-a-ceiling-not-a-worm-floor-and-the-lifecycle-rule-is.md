---
type: Decision
title: "Retention is a CEILING, not a WORM floor — and the lifecycle rule is unfiltered on purpose"
description: "Archived objects expire after 2557 days by one unfiltered bucket-wide rule, and earlier deletes stay allowed; Object Lock is out, and a second content class means revisiting the rule, never adding a filter."
---

Every object expires 2557 days (7 years) after creation. Nothing prevents an earlier delete, and
nothing may: SPEC-171's restore deletes the archived copy once it has been put back.

The expiry rule is **bucket-wide with no prefix filter**, and it is the exact **inverse** of the
admin bucket's `admin_lifecycle_rules_are_prefix_scoped` check. That check exists because *that*
bucket mixes `logs/` (retained forever) with expiring content, so an unfiltered expiring rule there
would silently delete the logs. This bucket holds exactly one class of object, so the risk runs the
other way: a prefix filter would be a silent way to leave some archived data unexpired past the
retention the feature promises. **S3 lifecycle can include a prefix but never exclude one**, so if a
second content class is ever put in this bucket the repair is *not* to add a filter — that would
leave the new class unexpired and this rule looking correct. It is to revisit the rule, and probably
to give the new class its own bucket.

**S3 Object Lock is out of scope for two independent reasons.** It requires bucket versioning, which
this project deferred by decision (2026-08-03); and in compliance mode nothing can delete an object,
not even root, which would make SPEC-171's cleanup of a restored archive impossible.

## History

### 2026-08-12

- **Settled:** entered the register.
