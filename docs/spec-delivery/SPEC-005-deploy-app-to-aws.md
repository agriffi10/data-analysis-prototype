# Completed Spec - Deploy App to AWS — GitHub Actions Pipeline

## What was completed from this spec?

Two GitHub Actions deploy workflows and a setup README:

- `.github/workflows/deploy-app.yml` — triggers on push to `main`. Installs dependencies from the repo root, builds the SPA with all `VITE_*` environment variables injected from GitHub Actions variables, syncs `apps/portal/dist/` to the static assets S3 bucket with `--delete`, and invalidates the CloudFront distribution. Authenticates to AWS via GitHub OIDC — no stored credentials.

- `.github/workflows/deploy-infra.yml` — triggers only when files under `infra/**` change. On pull requests: runs `tofu init → validate → plan` and posts the plan output as a comment on the PR. On push to `main`: runs `plan` then `apply` automatically (two jobs, `apply` depends on `plan`, no manual gate). Uses `opentofu/setup-opentofu@v1` pinned to `~1.8`. Backend config (`bucket`, `dynamodb_table`, `region`) is passed to `tofu init` via `-backend-config` flags sourced from GitHub secrets and variables.

- `.github/workflows/README.md` — documents every required secret and variable, its purpose, and value source. Includes a first-time setup checklist covering IaC output capture, secret/variable population, and triggering the first deploy.

## What has changed?

- `infra/variables.tf` — added `app_url` variable (type string, default `""`) to properly declare the value injected as `TF_VAR_app_url` in both infra workflow jobs. It has no effect on current IaC resources; it is declared in preparation for Cognito OAuth callback URL configuration in a future spec.
