---
type: Decision
title: "A `TF_VAR_` variable reaches Terraform only if a run hands it over, so none renames the deployment"
description: "**An empty `TF_VAR_` is not an unset one.** It satisfies a required variable *and* overrides a default; an unset repo variable renders as exactly that. Guard with `validation`, not with the absence of a default. **And a set one is configuration only if a run hands it over** — no workflow builds a name from one Terraform is not given, a set one fails the plan and apply, and renaming the deployment is a reviewed change to `infra/` and the deploy, never a variable."
---

`TF_VAR_project_name` and `TF_VAR_environment` were documented as settable "if this deployment
does not use the defaults", and six workflows built resource names from them behind `|| 'dat'` and
`|| 'prod'` fallbacks — the registries, the functions, the migration's buckets and workgroup. No
plan or apply was ever handed either. Setting one would have pointed every workflow at
`<project>-<env>-*` while Terraform kept building `dat-prod-*`, with nothing red in between. The
migration workflow read four name overrides, `TF_VAR_user_space_bucket_name` among them, on the
same terms.

**The choice was to stop reading them, not to wire them through.** Wiring them through renames
every resource they touch, which is a product decision rather than a fix, and it would not even be
complete: `infra/main.tf` builds several names, the user-space bucket and the Athena workgroup
among them, with a literal `-prod-` instead of `var.environment`. So the workflows write
`infra/variables.tf`'s defaults out, a test holds the two equal, and the variables are read nowhere.

**Two halves guard it, because the failure is silent from either side.** A workflow that reads a
`TF_VAR_*` Actions variable not handed to Terraform under its own name in both the plan and the
apply fails `lambdas/test_config_workflows.py`. A variable that is SET and not handed over fails the
plan and the apply themselves: `.github/scripts/tf_var_guard.py` is the first line of both `tofu`
steps, reads `toJSON(vars)`, and compares it against the environment Terraform is about to inherit
and the module it runs in, rather than a second description of either. A variable counts as handed
over only under an environment key whose suffix is EXACTLY a declared variable, and only with the
same value. The spelling matters because OpenTofu matches it case-sensitively and ignores the rest
without a word, while GitHub shows the variable's name upper-cased — a key copied from the settings
page hands over nothing, and a first draft that case-folded both sides passed exactly that. The
value matters because `TF_VAR_max_upload_bytes` reaches Terraform from `VITE_MAX_UPLOAD_BYTES`, so
a variable named for it would pass a name check while Terraform used something else. It exits 2
rather than passing when it has no `REPO_VARS`, when nothing named `TF_VAR_` is in its environment,
or when its working directory declares no variable — each would otherwise read as clean. The static
half refuses a `TF_VAR_` key naming no declared variable too, so a misspelt key fails at review
rather than on the first run someone sets the variable.

**Do NOT reintroduce a `|| 'default'` read of a name variable** to keep a rename possible later.
That fallback is what hid the drift: unset, it agrees with Terraform by coincidence, and set, it
disagrees with no symptom.

Guard a required variable with `validation`, not with the absence of a default: an empty `TF_VAR_` satisfies a required variable and overrides a default, and an unset repository variable renders as exactly that.

## History

### 2026-09-14

- **Settled:** entered the register.
