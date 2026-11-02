---
type: Decision
title: "Analytics (SPEC-032→036)"
description: "Per-user isolation is the `username` IAM principal tag on the Glue database and table ARN, never LF-Tags, under one shared role, and query results land in the delete-denied `{username}/system_settings/athenaresults/`."
---

In-app Athena/Glue/Lake Formation query workspace. Per-user isolation = the **`username` IAM principal tag** on the Glue DB/table ARN (DB name = username), **not LF-Tags**; single shared role; user-space bucket registered in LF **hybrid** mode; results in `{username}/athenaresults/` (delete-denied). Detail: SPEC-032, architecture.md.

## History

### 2026-06-17

- **Settled:** SPEC-032→036.
