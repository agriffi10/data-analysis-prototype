---
type: Decision
title: "The byte formatters share a unit ceiling, and it goes to TB (SPEC-155 FR-007)"
description: "`formatSize` and `formatBytes` stay separate for their `undefined` handling but share one unit table whose ceiling is TB, so one number reads the same on every screen."
---

`fileBrowser.format.formatSize` and `query.format.formatBytes` are documented as "deliberately not
merged", and on `undefined` handling that is defensible. On the **unit ceiling** it was not: a 3 TB
object read `3072.0 GB` in the file browser and `3.0 TB` in the query status bar, from the same
number, on two screens of one app.

**Decided: unify the ceiling at TB.** This is a **user-visible change**, which is why it is a
decision and not a refactor — SPEC-155's scope otherwise forbids one. The two functions stay
separate for their `undefined` handling; only the unit table is now shared. Silently keeping both was
explicitly not an outcome the spec allowed.

## History

### 2026-08-06

- **Settled:** SPEC-155 FR-007.
