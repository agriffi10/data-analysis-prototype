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
