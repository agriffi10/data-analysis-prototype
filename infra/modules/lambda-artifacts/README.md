# `lambda-artifacts` — the Lambda code staging bucket

One private S3 bucket, and **nothing writes to it or reads it any more.** It staged each function's
zip under `{function}/{git-sha}.zip` while the fleet was zip-packaged; every function now runs a
container image and `deploy-lambdas.yml` uploads nothing at all. SPEC-214 removed the zip and layer
machinery from the repository and **does not touch this bucket** — its objects are the only copies
of the artefacts the pre-container fleet ran, so deleting it is a separate decision with a separate
argument, and no spec owns it yet.

| File | Holds |
|---|---|
| `s3.tf` | the bucket, its four hardening resources, and the lifecycle rules |
| `outputs.tf` | name and ARN |
| `variables.tf` | the module interface |

No public access, no browser CORS — only the deploy role and the Lambda service read it.

## The 60-second sleep is an IAM propagation guard

`depends_on = [module.base]` orders the API calls so the deploy-role policy granting this bucket's
management is written before this module runs. But **IAM is eventually consistent**: the deploy role
using that grant to create the bucket in the same apply can race the propagation and hit a transient
`AccessDenied`. The pause closes that window.

It is **60s, not 30s**, because the first apply saw a later bucket-config call
(`GetLifecycleConfiguration`) still race even after `CreateBucket` had succeeded.

## Artifacts are disposable

Lambda copies the code internally on `update-function-code`, so an expired S3 object never affects a
running function. Packages expire after 30 days to keep the bucket bounded.

The second lifecycle rule aborts incomplete multipart uploads after 7 days (`CKV_AWS_300`). While
CI uploaded a zip per function per deploy, **an interrupted runner was the ordinary way this bucket
acquired orphaned parts** — billed, and invisible to every listing. Nothing uploads now, so the rule
is sweeping up after a pipeline that has stopped running.

## The bucket name comes from the root module

Computed there and passed both here (creation) and to the base module's deploy policy (scoping),
which avoids a `base` ⇄ `lambda-artifacts` dependency cycle.
