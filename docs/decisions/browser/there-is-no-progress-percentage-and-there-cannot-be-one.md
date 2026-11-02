---
type: Decision
title: "There is no progress percentage, and there cannot be one (SPEC-190)"
description: "Async file operations show what is running and since when, never a percentage: the plane reports only at the end of a run, and polling the execution for progress would be a second read path."
---

`onProgress` went with the browser's own copy loop: the plane reports outcomes at the END of a run
and nothing in between, so any percentage the browser drew would be invented. The surface says
**what** is running and **since when** instead. This is not a gap to fill later by polling the
execution — that would be a second read path to state the notification already reports, on a plane
whose whole point is that the browser stops watching.

## History

### 2026-08-23

- **Settled:** SPEC-190.
