---
type: Decision
title: "A build stamp belongs to the artefact; an environment name belongs to the environment"
description: "Tofu sets `ENV_NAME` on every Lambda from `var.environment`; `BUILD_VERSION` travels in the artefact, never in Tofu's environment map, and is read once at import, where a missing or unreadable stamp degrades to the sentinel and never raises."
---

Every structured log record shipped `"version": "0.0.0"` and `"env": ""` — fields that exist to
correlate a record to a deploy and filter by environment, both inert.

`ENV_NAME` is Tofu's to set and now ships on **every** Lambda from `var.environment`, the same
source of truth as the feature-flag document's `environments` keys. `BUILD_VERSION` is **not**:
Tofu owns the environment map, `update-function-configuration --environment` REPLACES it whole (so
a workflow write would race an apply or be reverted by the next one), and Deploy Infrastructure is
path-filtered to `infra/**` — so a Tofu-set sha would name the last *infra* commit rather than the
code that is running. The stamp travels **in the package** instead, written into every zip by
Deploy Lambdas and read once at import. A missing or unreadable stamp degrades to the sentinel and
**never raises**: this module is on the layer every control-plane verb attaches, and PR #196 is what
an import-time failure there costs.

> **Mechanism superseded by SPEC-212/213/214; the decision stands.** There are no zips and no
> layers: one container image carries the stamp for all 86 functions, and `cpcommon` reaches them
> from `/opt/python`. The reasoning is unchanged and the degrade-never-raise rule is now *more*
> load-bearing, since a single artefact means one import-time failure is the whole fleet's. Full
> entry: *A guard is retired by proving its replacement, then deleting*, below.

## History

### 2026-08-14

- **Settled:** entered the register.
