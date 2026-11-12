# `user-directory` — the username directory builder

One Lambda, one daily schedule, one published JSON object. It lists the user-space bucket's
top-level common prefixes and publishes them, sorted, as the document the browser reads to suggest
usernames.

| File | Holds |
|---|---|
| `../../function-user-directory.tf` | the call to [`scheduled-function`](../../modules/scheduled-function/README.md): names, environment, the daily rule and the invoke grant's statement id |
| `build.json.tftpl` | the builder's one inline policy |

Code: `lambdas/user-directory-build/`. The function's own reasoning is in its module docstring.

## The source is S3, not Cognito

Deliberate, and the transition reverses it: today Cognito is complete and S3 is not. The document is
readable by every authenticated user, accepted knowingly — **usernames only, never emails**.

## The ListBucket grant is unconditioned, and that is a decision

`Delimiter="/"` is a property of the Lambda's **code**, not of the grant. This role can therefore
enumerate every object key under every user's prefix, not merely the top-level common prefixes it
asks for. That is accepted, for three reasons taken **together**:

1. It holds **no `s3:GetObject` anywhere**, so it can list key names and read nothing.
2. Key names are metadata, which this repo's field rule already treats as loggable and
   non-sensitive (`cpcommon.observability`'s module docstring).
3. It is a Lambda execution role with no user-assumable path.

**Check (1) before adding any grant here** — it is the property the other two rest on.

The obvious tightening — an `s3:prefix` condition scoped to the empty string — is **rejected, not
overlooked**. Whether botocore serialises an empty `Prefix` into a condition key at all is an AWS
implementation detail; if it does not, a `StringEquals` on `""` fails closed and this role's only
listing call breaks. And `simulate-custom-policy` agrees with whatever context key the author
supplies, so the check would confirm the assumption rather than test it. If this grant ever becomes
uncomfortable, the sound fix is **a separate bucket for the directory**, not a condition key whose
presence cannot be verified.

## The allowlist takes a constructed role ARN, never the call's output

It goes into the user-space bucket policy's principal allowlist, and an unknown-at-plan ARN inside a
list attribute **silently drops the change** (`infra/info/deploy-role-iam.md` → *unknown ARN inside
`compact()`/a list*). The root passes a **constructed string** instead — `infra/main.tf`'s
`user_directory_build_role_arn` local. `scheduled-function` does export a `role_arn`, so the rule is
that string, never `module.user_directory.role_arn`.

## Naming

Names derive from `{project_name}-{environment}` so the deploy policy (`modules/base`, the
user-directory grant) scopes to the same `{project}-*-user-directory-build` patterns, and so ARNs
referenced inside IAM policy templates are **known at plan time**.

The role name carries **no `-role` suffix**. The repo is inconsistent about this — log-sweep and the
DLQ drain have none, pre-signup does — and the deploy grant is scoped to
`role/${project_name}-*-user-directory-build` with no trailing wildcard, so a `-role` suffix here
would be **denied at CreateRole rather than caught at plan**. The schedule rule is
`{function_name}-schedule` for the same reason: the grant scopes to
`rule/${project_name}-*-user-directory-build-schedule`, and the DLQ drain's sibling rule is named
`-sweep`, so the two are not interchangeable.

## The daily schedule is sufficient, and here is the bound

`rate(24 hours)` rather than a cron expression: nothing depends on the rebuild landing at a
particular hour, and a rate schedule cannot be wrong about a timezone.

The document is rebuilt from scratch every run — no incremental state, so nothing reconciles and a
missed run costs **staleness, never correctness**. A user provisioned just after a run is absent
from the suggestions for up to a day; they can still be added by typing the name, because every
consumer accepts a name that is not in the list. That bound is the whole reason a daily schedule
works.

## Environment variables it does not use

`USER_SPACE_BUCKET` is the one variable the function actually reads. The rest are set because
`cpcommon`'s config requires them of every function that imports it. That read happens on
**first access** rather than at import, so a missing one no longer crashes at cold start — it fails
on whichever branch reads it, which is narrower and no less broken. Still set them: the union is
what any code path in `cpcommon` may demand, and "the function does not use it" is not a reason to
remove one.

`LOGS_QUEUE_URL` is the exception, deliberately: `cpcommon.observability` reads it with
`os.environ.get` and never `config._require`, so a builder that loses it logs to stdout and still
publishes.

`lambdas/user-directory-build/test_build_directory.py` asserts this block against `config.py`'s own
declaration rather than against a hand-kept copy.
