---
type: Decision
title: "The deployed session key names who may use it, and the dev store's key delegates (SPEC-270)"
description: "**The deployed session table's key policy names its principals and does not delegate**: the deploy role administers it and uses it only through DynamoDB, the web task role uses it only through DynamoDB for the session table's name, and the account root may read its metadata and nothing else, so no identity policy can widen it: an administrator who cannot become the deploy role cannot read a refresh token. The task role is matched by `aws:PrincipalArn` on a `\"*\"` principal, because KMS does not check that principal exists and the role is gone whenever the web tier is off. **No `Deny`**: DynamoDB's own grants on the key have a service principal, and a negated `aws:PrincipalArn` on a call that may carry no such key could deny DynamoDB itself. **Among the IaC's principals, only the deploy role may create, re-trust or pass a role**, or someone could become the task role by name; outside the IaC, rewriting the deploy role's trust or passing the task role to a task still reaches the key. **Local dev servers use their own table and key, which delegate**, because a developer signs in with their own credentials. Item reads are closed; whether DynamoDB's control plane can re-key the table without the key is not yet measured."
---

The portal server keeps each browser's session in DynamoDB, and each item holds the user's Cognito
refresh token, which mints that user's bearer for 30 days. The table was always under a
customer-managed key, but the key's policy handed every decision to the account's IAM, so any
principal IAM allowed to read the table and use KMS could read every token. The client's security
review needs the table to have tightly scoped access (`docs/transition_plan.md` §4.7).

**The key's own policy decides.** It has five statements: the deploy role's administration (no
cryptographic action), the deploy role's use through DynamoDB (AWS's documented minimum for the
principal that puts a table under a customer-managed key), the task role's use and `DescribeKey`
through DynamoDB, and the account root's four metadata reads. A key policy that does not delegate
ignores identity policies, so the task role carries no KMS statement of its own: two places naming
one grant drift. `lambdas/test_session_infrastructure.py` holds the rendered policy whole — the
statement list, the principal set and every condition — because Checkov cannot read a
`templatefile()` policy.

**The deploy role is the trust root.** Its `PutKeyPolicy` lets it grant itself anything, as for any
key it administers. The account root is not given `PutKeyPolicy` as a break-glass: that would hand
the key to every principal an identity policy allows `kms:PutKeyPolicy` on `*`, a wider set than
those who can rewrite the deploy role's trust. Losing the deploy role loses administration of the key,
because KMS stores a named role by its unique id; the recovery is a new store under new names, which
costs every user one sign-in.

**The task role is matched by name, so naming must be held.** While the web tier is off the role does
not exist, and a principal that could create a role under its name, rewrite its trust or pass it to a
service could read sessions. Among the IaC's principals only the deploy role may do any of the three;
`lambdas/test_only_the_deploy_role_can_become_another_role.py` refuses any other policy naming an
action that matches them, wildcards, case variants, escapes, AWS-managed policy ARNs and files read
from outside `infra/` included. **That test sees only the IaC.** In an account, a principal outside it
(an SSO administrator permission set, say) that may `iam:UpdateAssumeRolePolicy` on the deploy role
controls the key, and one that may `iam:PassRole` on the task role and `ecs:RunTask` can run a task as
that role while the web tier is on. Both are the account's IAM to govern, and a security review of
the client account must read them there. The task role itself carries exactly one inline policy and
nothing attached, held by `test_the_task_role_holds_one_inline_policy_and_nothing_attached`.

**No `Deny`, unlike the identity-context sealing key's design.** A policy that does not delegate
already refuses every principal it does not name, so a Deny adds no narrowing, and one conditioned
on a negated `aws:PrincipalArn` risks denying DynamoDB's own service-principal calls, without which
AWS says DynamoDB cannot protect and maintain the table.

**The dev store delegates.** A local dev server signs in with the developer's credentials, whatever
role that is, so naming them is not possible. Its sessions never serve the deployed server, because a
session serves only the client that created it.

**What it does not close.** DynamoDB returns no item to a caller the key refuses, which closes item
reads. Whether `UpdateTable` to an AWS-owned key, or a backup restored with an encryption override,
needs the caller to hold the key or runs on DynamoDB's own grant is undocumented and unmeasured.
Inside the IaC only the deploy role holds those actions. `ExportTableToPointInTime` needs
point-in-time recovery, which is off on both tables; turning it on would add a third such path. If the
path is real, the answer is a DynamoDB resource policy on the table, which SPEC-270 set aside.

Do NOT build: a `Deny` on this key; `PutKeyPolicy` for the account root; a KMS statement on the task
role beside the key's grant; a named principal for the dev store.

## History

### 2026-11-17

- **Settled:** SPEC-270 (#1038 narrowed the key and moved dev servers; the completion PR removed the
  task role's KMS statements). Reverses SPEC-257's acceptance criterion that the key's only
  principal is the account root, marked in place in that spec.
