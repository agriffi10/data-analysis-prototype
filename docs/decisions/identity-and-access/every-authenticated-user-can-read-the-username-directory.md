---
type: Decision
title: "Every authenticated user can read the username directory (SPEC-146)"
description: "`_directory/usernames.json` is readable by every authenticated user, deliberately, and holds usernames only, never display names or emails; the daily builder is its only writer."
---

`_directory/usernames.json` is readable by **every authenticated portal user**, through one
`s3:GetObject` statement on the portal role. That disclosure is **intended and accepted**, not
incidental, and it is recorded here rather than left implicit because the object is a single file
listing everyone in the organisation.

What makes it acceptable is that the set is already disclosed several ways: a username **is** the S3
prefix, the `username` principal tag and the Glue database name (SPEC-033); it is visible on every
shared-space roster to every member (SPEC-075); and a prefix-search feature discloses the set by
construction — a typeahead that would not confirm whether `bob` exists is not a typeahead. The
document holds **usernames and nothing else**: no display names, no email addresses. An email is not
metadata under this repo's field rule and has no place in a document every user can read.

**What was deliberately NOT granted:** ~~no `ListBucket` widening (the portal role's grant stays
conditioned on the caller's own prefix, so `_directory/` is invisible to the file browser and the file
browser needed no change),~~ no `PutObject`, no `DeleteObject`. The user reads; the daily builder is the
only writer. **— Superseded in part (2026-08-30, #555):** the portal role may now list `_directory/*`
and `_config/*`; what keeps both out of the file browser is the API, which lists only a space the
caller's claims authorize.

**The accepted POPULATION changes at the transition, and the acceptance above is weakest for exactly
the people it adds.** `transition_plan.md` §3.12 provisions every known user's prefix ahead of use,
so the document stops listing "everyone who has used the portal" and starts listing everyone the
client has. Two of the three arguments above still hold for a never-signed-in user — the username is
still the prefix, and a typeahead still discloses the set by construction — but the shared-space
roster one does not, because they are on no roster. The decision is recorded there as deliberate;
what would retire it is a liveness rule in the builder, not a change to this grant.

**The builder's own `s3:ListBucket` is unconditioned**, and what that grants is stated rather than
minimised: `Delimiter="/"` is a property of the *code*, not the grant, so the role can enumerate every
object key under every user's prefix. Accepted because it holds **no `s3:GetObject` anywhere** (it can
list names and read nothing), because key names are metadata under the field rule, and because it is a
Lambda role with no user-assumable path. The obvious tightening — an `s3:prefix` condition on the
empty string — is **rejected, not overlooked**: whether botocore serialises an empty `Prefix` into a
condition key at all is an implementation detail, and if it does not the grant fails closed and the
builder's only listing call breaks. `simulate-custom-policy` would agree with whatever context key the
author supplied, so it would confirm the assumption rather than test it. If the grant ever becomes
uncomfortable, the sound fix is a separate bucket, not an unverifiable condition key.

## History

### 2026-08-30

- **Changed:** The portal role may now list `_directory/*` and `_config/*`; the API, not the grant, keeps both out of the file browser (#555).

### 2026-08-03

- **Settled:** SPEC-146.
