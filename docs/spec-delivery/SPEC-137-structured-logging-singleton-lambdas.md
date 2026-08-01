# Completed Spec — SPEC-137: Instrument the Singleton Lambdas

## What was completed?

The last three functions outside the pipe, and the only three that are not control-plane verbs:
`notifications-writer` (`service="notifications"`) and the two Cognito triggers
(`service="auth"`). **With this the whole fleet is instrumented.** No behaviour change.

## The layer-attachment premise was verified, not assumed

These functions did not attach `cpcommon`, and attaching it is the exact shape of PR #196:
`cpcommon.config` calls `_require` on six environment variables at **import**, so a function short
of one crashes at cold start — at the entry point, not at the line that would have used it.

Checked empirically, with a completely **empty environment**: `cpcommon.observability` imports and
emits three events, because `cpcommon/__init__.py` has no imports and `clients` lazy-imports
boto3, so `config` is never reached along that path.

**That makes the invariant load-bearing rather than incidental.** One `from cpcommon import
config` added to `__init__.py` later would arm the bomb for these three functions, and nothing
else in the repo would notice.

## Email joins tokens on the never list

Written into the **shared `observability` module docstring**, so the rule lives where every plane
reads it rather than only in this spec.

A username is not sensitive here — it *is* the S3 prefix, the principal tag and the Glue database
name (SPEC-033). An address is: it appears nowhere else in this store, carries no operational
meaning, and would be the only personal contact detail in a prefix retained forever.

**The hazard is mechanical.** A Cognito trigger event carries `request.userAttributes.email`, so a
single `info("signup", event=event)` — the most natural line anyone writes debugging a trigger —
publishes it. `pre-signup` therefore logs the **domain** and never the address: the domain is what
the disposable-provider rule turns on and is shared by every user of that provider; the local part
is what makes an address personal.

The test asserts against the **serialized event**, not a field allowlist, because the leak arrives
*nested* where a field-name check cannot see it — and it asserts the domain **is** present, so it
cannot pass by the verb having simply gone silent.

## `post-confirmation`'s swallowed failure

Provisioning failure is swallowed on purpose (never block sign-up), which means a user who signed
up successfully and has **no Glue database** — the whole reason `backfill.py` exists — previously
left only a CloudWatch line nobody watches. It is now an `error` carrying a `remediation` field.

## A mutation exposed that the denylist was untestable

Deleting SPEC-137's four names from `CONTENTS_DENYLIST` failed **nothing**: a tripwire is dormant
until tripped, so no test notices when it is disarmed. The same hole existed for SPEC-132's
entries and had gone unnoticed since they were written.

The rule is now asserted directly — the denylist's *contents*, not only its effect — so removing a
name a spec put there is a decision made in the open.

## Verification

`ruff check lambdas/` clean; `pytest lambdas/` 1384 passed / 2 skipped. Four mutations, all
observed to fail: logging the address instead of the domain; the domain field holding the whole
address; the verb going silent; a denylist entry deleted.

---

## Correction (2026-08-01): FR-005 shipped only its code half, and it broke sign-up

**What actually landed on 2026-07-23 was the instrumented Python and nothing else.** FR-005's
infra half — the `cpcommon` layer attachment in `deploy-lambdas.yml`, the `logs_queue_url`
variables on `modules/auth` and `modules/notifications`, `LOGS_QUEUE_URL`, and the producer IAM —
was written into the spec's acceptance criteria and never implemented. FR-001's proof (the
scrubbed-environment subprocess test, the AST check, the `__init__.py` comment) did not land
either; the empirical check above was run by hand and then not kept.

So all three functions deployed `from cpcommon import observability` with **no `cpcommon` layer
attached**, and raised `ModuleNotFoundError` at cold start. On `pre-signup` that is a Cognito
trigger, so it failed real sign-ups — reported by a test user on 2026-08-01, nine days later.

**Why nine days.** Every gate that could have caught it was blind to this specific failure, and
each for a reason that still holds:

- `pytest` puts every layer package root on `sys.path` (`lambdas/conftest.py`), so the import that
  fails in Lambda succeeds under test **by design**.
- `update-function-code` succeeds against a function that cannot import; the Deploy Lambdas job
  went green on the very run that broke sign-up.
- `test_instrumentation_coverage.py` asserts these modules **are** instrumented — it was satisfied
  by exactly the import that could not resolve.
- Nothing invokes sign-up on a schedule, and FR-006's Phase 4 live check ("sign up one test user")
  had not been run.

**Also found while fixing it:** neither `modules/auth` nor `modules/notifications` carried
`layers` in `ignore_changes`. Even with the attachment added, the next `tofu apply` would have
stripped it back off — the same break, arriving later and looking unrelated.

### What now guards it

`lambdas/test_deploy_matrix.py` parses the deploy matrix and joins it against what each function
actually imports, so an import of a layer package whose flag is unset fails the suite. It is the
only place where a Lambda's *packaging* is asserted rather than its behaviour, and it covers every
layer, not just `cpcommon`. FR-001's proof landed alongside it as
`test_layer_import_safety.py`.

### The transferable lesson

A spec whose FRs span code and infra can be **half-implemented and still look complete**, because
the code half is what the tests and the delivery doc are written about. The observability arc's
convention — the Lambda code and its layer attachment are owned by different systems (Terraform
vs. `deploy-lambdas.yml`) — is what makes the halves separable in the first place. Where that
split exists, the join has to be asserted somewhere, by something that reads both sides.
