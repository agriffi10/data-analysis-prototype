---
type: Decision Area
title: "Identity, access and the name that ties them together"
governs: [lambdas/api/**, lambdas/pre-signup/**, lambdas/post-confirmation/**, lambdas/user-directory-build/**, infra/modules/api/**, infra/modules/auth/**, infra/function-user-directory.tf, infra/functions/user-directory/**, infra/modules/verification/**, apps/portal/src/features/auth/**, apps/portal/src/server/session/**, infra/modules/session-store/**, apps/portal/src/features/feature-flags/**, apps/portal/src/features/user-directory/**]
---

The register's decisions on Cognito, the one shared role and its principal tags, the API's verifier and credential planes, the username that is also a prefix and a database name.

Cognito **User Pool**, ABAC — the Identity Pool is RETIRED (SPEC-202) and the API is the only thing
that turns a token into credentials; retiring it changed **nobody's sign-in**, which is the
conflation to head off. The `username` principal tag is stamped **server-side from
the verified claim**, so it cannot be spoofed; one shared role, isolation by
`${aws:PrincipalTag/username}`; a SHARED space adds a per-space role-level LF grant, retired
**with** the tag scoping or not at all. Hosted UI is **Managed Login v2** — the classic one broke the
post-signup redirect. The API verifies the bearer the portal server sends on the browser's behalf,
and assumes that same role for it.

**One string is four things:** username = S3 prefix = principal tag = Glue database name, so it is
catalog-safe by construction (`^[a-z][a-z0-9_]{2,62}$`) — pre-signup applies the rule, which is what
"by construction" rests on. **A shared space's NAME is the same four things and one more**, the
table-build and table-share `MessageGroupId`, and it was catalog-safe by nothing until the create
path took the rule: the browser's create dialog held it and no server path did, so a space could be
created that can never build a table
([control-planes](../control-planes/a-spaces-name-is-held-to-the-catalog-rule-where-it-is-chosen-and-the.md)).
The username directory is built from **S3,
not Cognito** — today Cognito is complete and S3 is not, and the client transition reverses exactly
that. It is readable by every authenticated user, accepted deliberately: usernames only, never
emails.
