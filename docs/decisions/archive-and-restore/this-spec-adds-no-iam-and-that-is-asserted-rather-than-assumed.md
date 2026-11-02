---
type: Decision
title: "This spec adds no IAM, and that is asserted rather than assumed"
description: "The restore guard adds no IAM: its heads rest on the existing `s3:GetObject` grant rather than `ListBucket`, and a test pins that distinction."
---

FR-006's additions were already in place: `SourceDataRead` grants the `s3:GetObject` a `HeadObject`
authorizes against, and `ArchiveVaultList`/`ArchiveVaultWrite` cover the vault — all SPEC-169's. So
there was no grants-first PR split to make, unlike 168 and 169.

The `GetObject`-not-`ListBucket` distinction is nonetheless pinned by a test, because the failure
mode of the wrong grant is a **false pass**: a role holding only the bucket-level listing permission
gets a 403 on every head, and a guard that read 403 as "clear" would then report every destination
clear and overwrite the lot. Both directions of that mistake come back to one statement existing.

## History

### 2026-08-12

- **Settled:** entered the register.
