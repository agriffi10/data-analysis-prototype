---
type: Decision
title: "A persistent in-flight surface is NEW scope, with no precedent here (SPEC-190)"
description: "Async file operations show a session-scoped in-flight surface, never persisted, whose entries settle on a notification with their `requestId`, on dismissal, or at the machine's own timeout."
---

The three async planes already in the file browser — send, archive, restore — have **no in-flight
surface at all**. They push a toast and hand off to notifications, which is survivable for an action
the user chose to fire and forget. The upload queue is not the precedent it looks like either: its
provider is session-scoped at the shell so uploads survive navigation, but its list renders inside a
drawer that exists only while it is open.

This one is justified on its own merits, because these gestures **replaced synchronous ones**. A
user who copies a folder and watches nothing happen has no way to tell "accepted, running in the
background" from "the click missed" — where before, the listing simply updated. That is the
regression the surface exists to prevent, and it is the reason a citation would not have done.

It is session-scoped and **not persisted**. The notification is the durable channel; a stored queue
would be a second writer to state the plane owns, and it would outlive the only thing that can
settle it. Three bounds keep it from wedging the per-space submit gate: an entry settles when a
notification carrying its `requestId` arrives, every entry is user-dismissible, and every entry
expires at the machine's own `TimeoutSeconds` (mirrored in the browser and pinned to `locals.tf` by
a test). The dismiss is load-bearing rather than tidy — a request whose notification never reaches
the inbox has nothing to correlate against, so short of the three-hour expiry it is the only thing
that frees that space.

## History

### 2026-08-23

- **Settled:** SPEC-190.
