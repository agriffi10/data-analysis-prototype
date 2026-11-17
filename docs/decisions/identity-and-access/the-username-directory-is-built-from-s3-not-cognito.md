---
type: Decision
title: "The username directory is built from S3, not Cognito (SPEC-146)"
description: "The username directory comes from a daily builder over the user-space bucket's top-level prefixes, with no Cognito call and no Cognito union; it is advisory and never an authorization input, so existence checks stay `admin_get_user`."
---

The daily builder enumerates the user-space bucket's **top-level common prefixes**. It makes **no
Cognito call**, and a test asserts the module never names `cognito` in any import, attribute or call.

**The reasoning inverts the obvious answer, which is why it is written down.** *Today* Cognito is the
complete record of who exists and S3 is not: the personal prefix is created **by the browser**, by
`ensurePrefixMarker` on the first visit to `/files` (SPEC-014, a deliberate no-backend decision), so a
confirmed user who has never opened the file browser has no prefix. On that reading Cognito wins.

*After the client transition it reverses.* `transition_plan.md` §2 item 7 settles that **sign-in
provisions nothing** — and §3.12 (2026-09-04) settles what provisions instead: a **portal-owned
provisioner** creates every known user's space **before anyone signs in**, and `ensurePrefixMarker`
is deleted outright (§6.3), its write moving to that provisioner. *This paragraph previously said the
sync pre-creates the spaces and the client's own automation creates them for new users; the
conclusion below is unchanged and strengthened — S3 becomes complete for **every** known user rather
than for everyone who has been synced.* At the same
time federated login makes `cognito:username` a **synthetic `identitycenter_<subject>` value** rather
than the catalog-safe username (§6.1), and users appear in the User Pool only after their first
sign-in. So S3 becomes complete and Cognito becomes both incomplete **and wrong-keyed**.

Choosing the source that is right on the far side of a migration already in flight beats the one that
is right today, particularly when today's gap is bounded: pre-production, no production users, and the
failure mode is a name missing from a suggestion list that still accepts free text.

**Do NOT add Cognito as a union "to be safe."** A second source with different completeness properties
is a second thing to reason about every time the directory looks wrong.

**The directory is advisory and is never an authorization input.** No control plane reads it; every
existence check stays `admin_get_user` against the User Pool (`shared-space-common/membership.py`,
`tscommon/cognito.py`), and an unknown name is still reported to the user as a notification. A
tripwire in `user-directory-build/test_build_directory.py` fails if any production Lambda module
other than the builder and the API route that serves the document names the path, the prefix or the
key constants, and a second check fails if that route reaches for an authorization helper. Test
modules are exempt by shape: a suite that names the key is asserting which object is opened or
denied, not reading it.

Full account: `docs/spec-delivery/SPEC-146-username-directory-daily-builder.md`.

## History

### 2026-11-17

- **Corrected:** The tripwire this decision cites had been deleted in a suite cut and nothing replaced it; it is restored, with test modules exempt by shape rather than by a per-file allowlist.

### 2026-09-04

- **Changed:** Transition plan section 3.12 moved provisioning to a portal-owned provisioner for every known user, which strengthens the choice of S3.

### 2026-08-03

- **Settled:** SPEC-146.
