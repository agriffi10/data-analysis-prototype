---
type: Decision
title: "The notification sender bounds every dedup id, by digest rather than by dropping it (control-plane-wide)"
description: "`emit_notification` sends a dedup id the queue accepts unchanged and any other as its SHA-256, so the bound holds for every composition; it never drops the id to None, which would hand the send to content-based deduplication."
---

Every `emit_notification` caller that passes a dedup id composes it from the request id —
`{requestId}:{step}` through `cpcommon.notify.dedup_id`, `{requestId}:{tag}:{recipient}` in the
shared-space verbs, `dlq:{requestId}` in the DLQ drain — and the API admits a caller's id at up to
128 characters, which is the queue's whole limit on a key. Anything added carried a long id past it:
SQS refused the send, `emit_notification` logged and swallowed the refusal, and the notification was
lost, success and failure alike, with nothing going red. Portal-minted UUIDs never come close, so
only a direct API caller could hit it, but the loss was not only their own. The shared-space verbs
key what they send the member removed, the member added, the new owner and every member of a deleted
space on the caller's id, so an owner choosing a long id could do each of those without the people
affected hearing of it. Length was not the only trigger either: `{requestId}:add-unknown:{member}`
carries a member name the caller typed, which nothing server-side holds to ASCII, so a short id
beside a name like `josé` was refused too.

**The bound sits in the sender, not in each composition**, because the compositions are an open
population: fixing the sites that exist leaves the next one unfixed. The member-name case was found
only after the bound was in place, and the bound had already closed it. `emit_notification` sends a
key the queue accepts as it is and any other as its SHA-256, so every valid key is byte-identical to
before and nothing changes for an id the portal mints.

**A digest, never None.** None would hand the send to the queue's content-based deduplication, which
collapses only byte-identical bodies, so two emits a plane keys alike on purpose — data-quality's two
reports of one failure — would collapse only if they were also worded alike. The same key always
digests to the same value, so every collapse a producer chose survives the bound.

## History

### 2026-09-13

- **Settled:** entered the register.
