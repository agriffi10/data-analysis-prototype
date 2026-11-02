---
type: Decision
title: "Usernames"
description: "A username is the S3 prefix, the principal tag and the Glue database name, so the pre-signup Lambda validates it at signup against the catalog-safe rule `^[a-z][a-z0-9_]{2,62}$`."
---

Usernames are the S3 prefix = principal tag = Glue DB name → validated at signup by the pre-signup Lambda; SPEC-033 tightens to catalog-safe `^[a-z][a-z0-9_]{2,62}$`.

## History

### 2026-08-03

- **Settled:** entered the register.
