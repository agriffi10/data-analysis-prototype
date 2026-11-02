---
type: Decision
title: "File ops = filesystem UX"
description: "File operations present filesystem UX over S3, which has no move or rename: each is `CopyObject` + `DeleteObject`, folder operations are recursive and non-atomic, and collisions warn and confirm because versioning is off."
---

Download/upload/folder/metadata/delete/move/rename/copy. S3 has no move/rename → `CopyObject`+`DeleteObject` (folder ops recursive + non-atomic). Collisions = warn-and-confirm (versioning is off). Detail: architecture.md → *Constraints that shape the system*.

## History

### 2026-08-03

- **Settled:** entered the register.
