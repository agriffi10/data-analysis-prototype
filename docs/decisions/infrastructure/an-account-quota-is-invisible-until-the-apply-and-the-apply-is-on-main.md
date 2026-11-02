---
type: Decision
title: "An account quota is invisible until the apply, and the apply is on `main` (SPEC-222)"
description: "**An ACCOUNT QUOTA is invisible to every local gate, so the APPLY is the only thing that knows — and it finds out on `main`, with a partial apply behind it.** `tofu validate` type-checks, `docker-lambda`'s validation block enforces the range AWS *documents*, and a plan never calls `CreateFunction`; a value inside the documented range and outside the account's passes all three and is refused at create. Measured: a Lambda at Lambda's documented 10,240 MB, against an account whose un-raised quota is 3,008. The write grant, the log groups and the sibling function had already applied. `Deploy Lambdas` then names the wreckage precisely — *\"planned but never pointed at this commit's code\"* — which is the reconcile gate's signature for a refused create rather than a generic failure. `test_fleet_derivation.py` holds every module's declaration against what this account will actually create; it is fleet-wide because the next author will have the same information the last one did, which is none. **These constants are account quotas and therefore MOVE** — unlike a documented maximum, which is a service limit — so raising the AWS quota and raising the constant are one change, and the guard is wrong in the *denying* direction until both happen."
---

The converter asked for Lambda's documented maximum memory, 10,240 MB. `CreateFunction` refused
it: `'MemorySize' value failed to satisfy constraint: Member must have value less than or equal
to 3008`. That 3,008 is this account's un-raised quota, and nothing in the repository could see
it — `tofu validate` type-checks the value, the `docker-lambda` module's own `validation` block
enforces 512–10,240 because that is what AWS documents, and a plan never calls `CreateFunction`
at all. Every gate was green and the trunk went red.

**What makes it expensive is that the apply is partial.** By the time the converter was refused,
the execution role's new write grant, both new log groups and the sibling `notify` function had
already been created. So the failure is not "nothing happened" but "half a plane exists", and
recovery is a second apply rather than a retry. `Deploy Lambdas` failed alongside it with the
reconcile gate's message — *"these functions were planned but never pointed at this commit's
code"* — which is worth recognising on sight: it is what a refused create looks like one workflow
over, and it reads like a packaging problem rather than a quota one.

**The guard is fleet-wide and lives in `lambdas/test_fleet_derivation.py`**, not on the module
that hit it, because the next function to want more memory will be in a different module and its
author will have exactly the information this one had. It reads every `.tf` in a module that
DEPLOYS a Lambda — asked with `fleet`'s own module-source test, not a substring, because that
helper's docstring already records a suffix test silently dropping a plane's verbs over a legal
trailing slash — and refuses a declaration above what this account is known to create, on both
dimensions a quota can bite.

**Its file population is the part that was wrong first, and the repo had already learned why.**
It began at `infra/modules/*/locals.tf` — the per-module fleet map — and was green over ten
declarations, because a module deploying ONE function passes `memory_mb` straight to the shared
`docker-lambda` block in its own `lambda.tf` and builds no map. `fleet.py`'s `_locals_bodies`
carries the general lesson in its own docstring — read all of a module's files, not `locals.tf`
alone — for a different specific reason: a `locals` block that sits beside the resource using it,
which `api/lambda.tf` and `auth/lambda.tf` both have. Two facts about the same two modules, and
the reason the lesson transfers rather than the reason it was written.

**A new sweep over an existing tree should read what the existing sweeps say about that tree
before choosing its glob** — and read it for both things it can be. True prose nobody read is one
failure; prose that has been false long enough for work to be built beside it is the other, and a
false docstring is indistinguishable from a true one until somebody tries to rely on it. This one
was checked rather than quoted: `api/lambda.tf` and `auth/lambda.tf` do carry those blocks, and
`_locals_bodies` does glob `*.tf`.

It owes a corpus rather than a green run — a gate run against the thing it guards proves the
artifact passes and never that a check still fires — so it carries fixture cases at both
boundaries of both dimensions, in BOTH declaring shapes, and half of them assert SILENCE, because
a check that refuses the value it was written to allow is as broken as one that allows what it
must refuse. The count is not stated here; the corpus is the population and a number beside it
goes stale.

**Two numbers, two different kinds of fact.** Memory's 3,008 is a ceiling: `CreateFunction` named
it. Ephemeral storage's 2,048 is only what has been observed to be ACCEPTED — the converter runs
at it — which is not knowledge of where that ceiling is, and somebody writing 4,096 later is back
where this started. The distinction is in the constants' own comments because the guard would
otherwise read as two ceilings.

**Re-derive rather than re-check.** Both are account quotas and move on a support request, unlike
a documented maximum. `aws service-quotas list-service-quotas --service-code lambda` shows what is
adjustable, but `CreateFunction`'s refusal is the authority — it names the ceiling verbatim, which
is how 3,008 was learned. Raising the AWS quota and raising the constant are one change: apart,
the fleet keeps refusing a value the account would now accept, with nothing to explain why.

## History

### 2026-09-06

- **Settled:** SPEC-222.
