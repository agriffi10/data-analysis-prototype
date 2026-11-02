---
type: Decision
title: "An unreadable settings document is quarantined, never deleted and never overwritten (SPEC-159)"
description: "**An unreadable settings document is quarantined, never deleted and never overwritten**, and a **newer** schema is refused untouched — the parse is three-way, version checked before shape."
---

A `user_settings/` read-modify-write that cannot read the live body **copies it aside and then
writes**, rather than refusing forever (the previous behaviour) or committing the empty document
over it (the behaviour before that). The copy is a **precondition**: if it fails the write is
refused exactly as before. **A failed quarantine must never become a silent overwrite.**

The refusal it replaces had no way out. `user_settings/` denies `s3:DeleteObject`, the bucket is
unversioned, there is no admin UI and there never will be (out of scope) — so one unreadable
document permanently disabled saving queries and recording history for that user, and the only
honest advice was "Contact the Administrator", whose only tool is the AWS console.

**A newer schema is not corruption, and quarantining one would BE the data loss this prevents.**
The classifier (`lib/s3Json.classifyDocument`) reports three outcomes, not two, and checks the
version **before** the shape — a `version: 2` document is newer whatever else it contains, because a
newer schema is free to have renamed the field this build validates. A newer document is refused
untouched and answered with "reload the page"; only `unparseable` is ever copied.

**The quarantine key carries a random token as well as a timestamp, and that is load-bearing.**
`CopyObject` copies whatever is live at copy time and nothing binds the copy to the body that was
classified. Two tabs finding the same corrupt document in the same second, keyed on a clock alone,
would collide: the first sets the corrupt bytes aside and repairs the document, the second copies
the now-**repaired** document over the first one's quarantine object — destroying the only surviving
copy, on a folder that denies delete. The token makes the loser write a redundant object instead.
Do **not** "simplify" the key back to a bare timestamp. (The ordinary last-writer-wins race on the
document itself is untouched and still accepted; `IfMatch` writes are a separate, complementary fix
that this neither needs nor blocks.)

**No IAM change, deliberately.** Everything is `GetObject` + `PutObject` inside the user's own
prefix — which is why the quarantine key is a sibling of its source rather than a separate folder.
Two consequences follow and are recorded here rather than discovered later:

- **Quarantine objects are themselves undeletable.** They inherit the `user_settings/` delete deny,
  so neither the app nor the user can remove one — only an administrator working directly in the
  console can. Accepted: one object per genuine corruption event is a smaller problem than the
  evidence being destroyed.
- **Accumulation is not a loop.** The document written after a quarantine is one the app serialized
  itself, so a second quarantine requires a second, independent corruption.

**Rejected, and recorded in the spec so they are not re-proposed:** granting the portal role
`DeleteObject` under `user_settings/` (trades away a standing safety property for convenience, and
destroys the only copy of what the user had); "click Save again to replace" (reintroduces the loss
behind a confirmation the user cannot make informed, since they cannot see the document); repairing
the document in place (a guess presented as a recovered library); writing the copy from bytes
already in memory (carries an unbounded untrusted body out through the parse contract, and costs a
second `GetObject`); and a fixed quarantine key overwritten each time.

## History

### 2026-08-10

- **Settled:** SPEC-159.
