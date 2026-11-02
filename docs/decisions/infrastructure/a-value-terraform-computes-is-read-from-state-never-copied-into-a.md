---
type: Decision
title: "A value Terraform computes is read from state, never copied into a settings page (SPEC-215)"
description: "A value Terraform computes is read from state through `.github/config-outputs.json`, and the job refuses an absent or empty output. Only a genuine input stays a repository variable, and no second copy of the values (SSM, generated tfvars, cached outputs) is allowed."
---

The publishing workflows init the same backend `deploy-infra.yml` uses and read
**one** `tofu output -json` per job, mapping output names to configuration keys through
`.github/config-outputs.json`. The values had been repository variables a person read out of `tofu
output` once and typed into a settings page, which made a human the transport between the thing that
computes a value and the thing that serves it.

**The failure that arrangement has, this repo had already met twice.** An unset repository variable
interpolates to the **empty string**, which satisfies a required Terraform variable *and* overrides
its default — `deploy-config.yml` carried a hand-written guard for exactly that, because the symptom
was an `s3:///_config/…` copy failing far from its cause. And a value that moved in infrastructure
stayed wrong in the browser until somebody re-copied it, which is precisely what the runtime
configuration document exists to prevent: a repoint should not be a rebuild, and it should not be a
settings page either.

**What decides whether a key belongs in the map or stays a variable is not convenience — an input
cannot be read from the thing it configures.** `AWS_REGION` names where the state lives, so it is
needed to assume the role *before* an output can be resolved. `VITE_APP_URL` feeds `TF_VAR_app_url`,
from which Cognito's callback list is built. `environment` and `maxUploadBytes` are policy, not
resource attributes. Everything else is derived, and a derived value in the settings page is a second
copy that nothing reconciles. **A surviving variable with no such reason is one that should have been
retired**, which is why the reasons are written per-variable in `.github/workflows/README.md` rather
than asserted collectively.

**The refusal is loud and it is one refusal.** `resolve-config.sh` fails the job on an output that is
absent **or empty**, naming both the configuration key and the output, and reporting every fault at
once rather than one per deploy cycle. Emptiness is the thing checked because it is what satisfies
every presence test there is. It is deliberately stricter than the served document's own `REQUIRED`
list: every mapped output is a value Terraform always computes, so an empty one means the state is
not what the deploy assumes, whatever the browser's degraded path for that key would be. The
document's `REQUIRED` guard stays, unchanged, answering the different question of what may be
published. The hand-written empty-variable guard in `deploy-config.yml` was **replaced**, not kept
beside it.

**Do NOT introduce a second copy of the values** — SSM Parameter Store, a generated tfvars, a cached
outputs artifact. State already holds them; writing them somewhere else to read them back adds a
resource type, its deploy-role IAM, and a second thing that can be stale. **No new grant was needed
and none was added:** the deploy role has held `s3:GetObject` and `s3:ListBucket` on the state bucket
since the backend existed, and `lambdas/test_config_outputs.py` asserts that rather than assuming it.

**Two couplings the change creates, both guarded because both fail silently.** Resolving `appUrl`
from `cloudfront_domain` while `TF_VAR_app_url` stays a variable makes them two independent
statements of one origin; before, they could not disagree. A divergence sends a sign-in started on
the portal back to an origin Cognito does not allow — a broken sign-in with nothing red anywhere — so
the app deploy compared them and refused. The comparison lived there rather than in a
Terraform `precondition` on purpose: being wrong there costs a skipped deploy with the live document
untouched, where a precondition would put the same claim in front of every infrastructure apply.
**(SPEC-202, 2026-09-02: the coupling is gone with `cloudfront_domain`, `var.app_url` and
`deploy-app.yml`. `appUrl` resolves from the `spa_origin` output and the Cognito callback and logout
lists are built from `var.spa_origin` — one statement of one origin, so there is nothing left to
compare. The reasoning is kept because the next two-statements-of-one-origin will look exactly like
this one.)**
Second, `deploy-config.yml`'s matrix names a configuration **key** rather than a variable, and
nothing checked that the key was resolvable — a typo would resolve to the empty string and target
`s3:///_config/…`, the exact failure the old guard existed to catch. `validate_feature_flags.py`
cross-checks it against the map, before any AWS call.

**The version agreement is derived on "declares an OpenTofu version", not on "runs `tofu init`".**
A workflow can read an output through the resolver without an init of its own — SPEC-214 does exactly
that — so an init-based predicate would exclude the consumer the derivation was widened for. The
assertion compares the constraint strings **as declared**, because `~1.8` is a constraint and not a
version, and "they resolve to one version" is not something a workflow file can state.

## History

### 2026-09-02

- **Changed:** SPEC-202 removed the `appUrl` and `TF_VAR_app_url` coupling: `appUrl` resolves from `spa_origin` and the Cognito lists from `var.spa_origin`, so the deploy's comparison went too.

### 2026-08-28

- **Settled:** SPEC-215.
