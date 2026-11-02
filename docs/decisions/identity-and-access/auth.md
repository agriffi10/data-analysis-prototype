---
type: Decision
title: "Auth"
description: "Cognito User Pool with ABAC: one shared IAM role, per-user isolation by `${aws:PrincipalTag/username}`, and the tag is stamped server-side from the verified token claim, never client-asserted."
---

Cognito User Pool, ABAC: the `username` principal tag is stamped from the verified token claim
**server-side** (unspoofable; never client-asserted). One shared IAM role for all users; per-user
isolation via `${aws:PrincipalTag/username}`. (SPEC-011; reversed the earlier "no Identity Pool".)

**What stamps it changed in SPEC-202; the model did not.** The Identity Pool stamped it from
SPEC-011 until 2026-08-31, exchanging the ID token for credentials in the browser. The API now reads
the same claims out of the same token and assumes the same role with the same tags — one computation
over one input, which is why no policy was rewritten and why the role is reused rather than minted.
The pool is deleted and the browser holds no AWS credentials at all. Full entry:
[The Identity Pool is retired, and no one's sign-in changed](the-identity-pool-is-retired-and-no-ones-sign-in-changed.md).

## History

### 2026-08-31

- **Changed:** The API replaced the Identity Pool as what stamps the principal tag; the model and the role did not change.

### 2026-06-08

- **Settled:** entered the register.
