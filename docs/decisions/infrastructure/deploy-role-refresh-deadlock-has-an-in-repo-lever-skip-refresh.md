---
type: Decision
title: "Deploy-role refresh deadlock has an in-repo lever (`skip_refresh`)"
description: "**The deploy role can lock itself out**: tighten or widen one of its own grants and plan, apply and **revert** all fail alike. `Deploy Infrastructure` takes `skip_refresh` to break it — always follow with a normal run. A green plan is not proof; IAM is eventually consistent. **Deploy-role IAM is in-scope work for any spec that provisions new infra**, and **grants land in their own PR before the resources that need them** — every grants-only PR in Arc B applied green first run. That is the whole claim: it does **not** prevent a red main, which this arc hit three times afterwards on things no grant review would have found."
---

`deploy-infra.yml`'s `workflow_dispatch` takes an off-by-default `skip_refresh` boolean that adds `-refresh=false` to the apply. It exists because **the deploy role can lock itself out**: tighten (or widen) one of its own grants and the next refresh needs the permission the pending change would restore, so plan, apply **and revert** all fail on the same `AccessDenied`. Applying from cached state installs the fix and unblocks normal runs. **Deliberately unreachable from `push`** — skipping refresh means drift is not detected, so it must be a conscious act; the step emits a warning telling the operator to follow up with an ordinary run, and that follow-up is not optional (an apply that skipped refresh has proved nothing about drift). It replaces the out-of-band `aws iam put-role-policy` break-glass as the *preferred* escape, because it needs no AWS access outside CI — that break-glass stays as the fallback. First use: 2026-08-02, recovering from the SPEC-139 follow-up (`lambda:ListTags` removed from an event-source-mapping statement on the false assumption that the function-scoped grant covered it — a mapping ARN and a function ARN are different resource types). **Caveat worth knowing before trusting any single run:** during that incident `plan` passed twice while `apply` failed on the identical call with no policy change between them, so IAM's eventual consistency can make the deadlock look intermittent — a green plan is not evidence the permission problem is fixed. Full trap list: `infra/info/deploy-role-iam.md`.

**Deploy-role IAM is in-scope work for any spec that provisions new infra, and grants land in their own PR before the resources that need them.** Every grants-only PR in Arc B applied green first run. That is the whole claim: it does not prevent a red main, which that arc hit three times afterwards on things no grant review would have found.

## History

### 2026-08-03

- **Settled:** entered the register.
