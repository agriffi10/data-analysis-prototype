# S3 File Portal

A web portal that lets authenticated users upload and download files to/from their own
private space in AWS S3. Authentication is handled by **AWS Cognito**; per‑user isolation is
enforced at the **IAM layer**, not in application code. There is **no backend server** — the
single‑page app talks to AWS directly from the browser using short‑lived, scoped credentials.

> **New here?** Start with this README for the big picture and setup, then read
> [`docs/architecture.md`](docs/architecture.md) for the design and
> [`CLAUDE.md`](CLAUDE.md) for conventions and the decision log.

---

## How it works (in one minute)

```
Browser (React SPA)
  │  1. Sign in  ──────────────►  Cognito User Pool (Hosted UI, username + password)
  │                                     │ JWT (id/access/refresh)
  │  2. Token exchange  ─────────►  Cognito Identity Pool (enhanced flow)
  │                                     │ stamps  username  principal tag (server-side, ABAC)
  │                                     ▼
  │                               Temporary IAM credentials (1 hr) for ONE shared role
  │  3. S3 calls (AWS SDK v3) ──►  S3 user-space bucket, scoped to  {username}/  by
  │                               ${aws:PrincipalTag/username} in the role policy
```

- **One shared IAM role** for all users. Isolation comes from the Identity Pool mapping the
  verified `username` claim to a principal tag — the browser never asserts its own identity,
  so it can't be spoofed.
- **No backend / API layer.** Uploads, downloads, listing, delete, move/rename all run in the
  browser against S3. Move/rename are copy‑then‑delete (S3 has neither); folders are zero‑byte
  marker objects.
- Full detail, diagrams, the two‑bucket model, and known constraints live in
  [`docs/architecture.md`](docs/architecture.md).

---

## Repository layout

This is an **npm workspaces monorepo**.

```
/
├── README.md                  ← you are here
├── CLAUDE.md                  ← project memory: conventions, tech stack, decision log
├── package.json               ← workspace root (workspaces: apps/*, packages/*)
├── apps/
│   └── portal/                ← the React SPA (all app code lives here)
│       ├── src/               ← components, features, hooks, lib, routes, types
│       ├── .env.example       ← every VITE_* var, documented
│       └── package.json
├── infra/                     ← OpenTofu IaC (S3 + CloudFront, Cognito, IAM, data buckets)
│   ├── main.tf · variables.tf · outputs.tf
│   ├── bootstrap/             ← one-time remote-state setup (S3 + DynamoDB)
│   └── modules/               ← app/ (hosting) · base/ (OIDC + deploy role) · auth/ · data/
├── lambdas/
│   └── pre-signup/            ← Cognito pre-signup trigger (Python)
├── docs/                      ← architecture, design system, specs, delivery records
└── .github/workflows/         ← CI + deploy pipelines (OIDC, no stored AWS keys)
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite |
| Language | TypeScript (strict mode) |
| Styling | TailwindCSS v4 (`@theme` design tokens — no `tailwind.config`) |
| Routing | `react-router-dom` v7 (library mode) |
| Server state | TanStack Query (`@tanstack/react-query`) |
| UI state | React Context + `useReducer` (no Redux) |
| AWS SDK | `@aws-sdk/client-s3` v3, `@aws-sdk/s3-request-presigner`, `@aws-sdk/lib-storage` |
| Auth | AWS Cognito + Amplify v6 (`aws-amplify`) |
| Testing | Vitest + React Testing Library |
| Linting | ESLint + Prettier |
| IaC | OpenTofu (`~1.8`), AWS provider, S3 remote state + DynamoDB lock |
| Lambdas | Python 3.12 |
| CI/CD | GitHub Actions (OIDC to AWS) |
| Monorepo | npm workspaces |

---

## Local development

### Prerequisites

- **Node.js 24** and npm — the version lives in `.nvmrc`, which is the single source of truth:
  every workflow reads it via `node-version-file`, and `nvm use` / `fnm use` picks it up locally.
  Matching it keeps `package-lock.json` stable, since npm's major writes different lockfile
  metadata.
- For IaC work: **OpenTofu `~1.8`** and the **AWS CLI** (configured with credentials for the
  target account)
- For Lambda work: **Python 3.12**

### Install & run

```bash
npm install                      # installs all workspaces from the repo root
npm run dev      -w apps/portal  # Vite dev server → http://localhost:5173
```

App scripts (run from `apps/portal/`, or from the root with `-w apps/portal`):

```bash
npm run dev        # start the dev server
npm run build      # production build → apps/portal/dist/
npm run preview    # serve the production build locally
npm run test       # Vitest (unit + component)
npm run lint       # ESLint
npm run format     # Prettier
```

### Two dev modes

`apps/portal/.env.example` documents every variable. Copy it to `apps/portal/.env.local` and
choose one:

1. **Unauthenticated dev** (no AWS account needed) — browse a public/test bucket with
   anonymous S3 requests. Set `VITE_S3_DEV_UNAUTH=true` and `VITE_S3_BUCKET_NAME=…`. This path
   is **dev‑only** and stripped from production builds.
2. **Full authenticated flow** — point the `VITE_COGNITO_*` and `VITE_S3_USER_SPACE_BUCKET`
   vars at a deployed environment's `tofu output` values and leave `VITE_S3_DEV_UNAUTH` unset.

---

## Deploying to a fresh AWS account

The app deploys as static files to S3 behind CloudFront; all other resources (Cognito, the
shared IAM role, the user‑space bucket, the GitHub Actions OIDC role, Lambda infra) are
provisioned by OpenTofu. The runbook below stands up the whole thing in a **new AWS account**.

> Detailed, step‑by‑step references: [`infra/bootstrap/README.md`](infra/bootstrap/README.md)
> (remote state) and [`.github/workflows/README.md`](.github/workflows/README.md) (CI/CD config).

### 1. Bootstrap remote state (once per account)

OpenTofu stores state in S3 with a DynamoDB lock table. These are created **manually** and are
**not** managed by the IaC. Follow [`infra/bootstrap/README.md`](infra/bootstrap/README.md) to
create the state bucket and lock table, then:

```bash
cd infra
cp bootstrap/backend.conf.example backend.conf   # fill in bucket/table names (gitignored)
```

### 2. Configure IaC inputs

```bash
cp terraform.tfvars.example terraform.tfvars      # gitignored
```

Set at least `aws_region`, `project_name`, `github_repo` (as `owner/repo`), `state_bucket`, and
`state_lock_table`. Other inputs (`environment`, `cognito_domain_prefix`,
`user_space_bucket_name`, `portal_role_name`) have sensible defaults — see
[`infra/variables.tf`](infra/variables.tf). Resource names follow `{project_name}-{environment}-*`.

### 3. First apply (locally, with admin credentials)

The first apply must run locally because it *creates* the GitHub Actions OIDC role that CI uses
for every subsequent apply (chicken‑and‑egg). Authenticate the AWS CLI to the target account,
then:

```bash
cd infra
tofu init -backend-config=backend.conf
tofu plan          # review
tofu apply
tofu output        # capture the values needed for the next step
```

This provisions: static‑assets bucket + CloudFront (OAC), the GitHub Actions OIDC deploy role,
the Cognito User Pool + SPA client + Hosted UI domain + Identity Pool, the shared portal IAM
role, the user‑space S3 bucket, and the pre‑signup Lambda's infrastructure (placeholder code).

### 4. Configure GitHub Actions (Settings → Secrets and variables → Actions)

Populate from `tofu output` (see [`.github/workflows/README.md`](.github/workflows/README.md)
for the full table and notes).

**Secrets**

| Secret | Source |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | `tofu output github_actions_role_arn` |
| `S3_STATIC_BUCKET` | `tofu output s3_static_assets_bucket_name` |
| `CLOUDFRONT_DISTRIBUTION_ID` | `tofu output cloudfront_distribution_id` |
| `TF_VAR_state_bucket` | your bootstrap state bucket name |
| `TF_VAR_state_lock_table` | your bootstrap lock table name |

**Variables**

| Variable | Source |
|---|---|
| `AWS_REGION` | e.g. `us-east-1` (must match all resources) |
| `VITE_APP_URL` | `tofu output cloudfront_domain` (placeholder on first deploy — see step 7) |
| `TF_VAR_github_repo` | `owner/repo` (must match exactly; scopes OIDC trust) |
| `VITE_COGNITO_USER_POOL_ID` | `tofu output cognito_user_pool_id` |
| `VITE_COGNITO_USER_POOL_CLIENT_ID` | `tofu output cognito_user_pool_client_id` |
| `VITE_COGNITO_DOMAIN` | `tofu output cognito_domain` |
| `VITE_COGNITO_IDENTITY_POOL_ID` | `tofu output cognito_identity_pool_id` |
| `VITE_S3_USER_SPACE_BUCKET` | `tofu output s3_user_space_bucket_name` |
| `TF_VAR_project_name` / `TF_VAR_environment` | only if you overrode the Terraform defaults (`dat` / `prod`) |

### 5. Deploy the Lambda code

The IaC creates the Lambda *infrastructure* with placeholder code; the real Python is shipped by
CI. Trigger **Deploy Lambdas** — run it manually (`workflow_dispatch`) or push a change under
`lambdas/**` to `main`.

### 6. Deploy the app

Push to `main` (or merge a PR). **Deploy App** builds the SPA with the injected `VITE_*`
variables, syncs `apps/portal/dist/` to the static bucket, and invalidates CloudFront. The app
loads at the CloudFront domain once the invalidation finishes.

### 7. Close the URL loop

On the first deploy the CloudFront domain isn't known yet. After it's live: set the `VITE_APP_URL`
variable to `tofu output cloudfront_domain`, set the same value as `app_url` in `terraform.tfvars`
and re‑apply infra (so Cognito's OAuth callback URLs include the real domain), then redeploy the
app. A custom domain additionally needs an ACM certificate in `us-east-1` (DNS‑validated) — see
[`docs/architecture.md`](docs/architecture.md) Deployment.

---

## CI/CD pipelines

All deploy workflows authenticate to AWS via **GitHub OIDC** — no long‑lived AWS keys are stored.
See [`.github/workflows/README.md`](.github/workflows/README.md) for the full configuration.

| Workflow | Trigger | Purpose |
|---|---|---|
| `ci.yml` | push (any branch) · PR → `main` | Lint, unit/component tests, production build |
| `deploy-app.yml` | push → `main` | Build SPA with `VITE_*` vars, sync to S3, invalidate CloudFront |
| `deploy-infra.yml` | PR / push → `main` (paths `infra/**`) | `tofu fmt -check` + `plan` (posts plan to the PR); `apply` on merge |
| `deploy-lambdas.yml` | push → `main` (paths `lambdas/**`) · manual | Build each Python Lambda, upload artifact, `update-function-code` |

---

## Environment & configuration reference

- **App build vars (`VITE_*`)** — every variable, with its `tofu output` source, is documented
  in [`apps/portal/.env.example`](apps/portal/.env.example) and mapped in
  [`docs/architecture.md`](docs/architecture.md) (Environment Variables).
- **IaC inputs** — [`infra/variables.tf`](infra/variables.tf) /
  [`infra/terraform.tfvars.example`](infra/terraform.tfvars.example).
- **IaC outputs** (the values you wire into GitHub Actions) —
  [`infra/outputs.tf`](infra/outputs.tf).
- **GitHub Actions secrets & variables** — tables above and in
  [`.github/workflows/README.md`](.github/workflows/README.md).

---

## Documentation index

| Document | What's in it |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Project memory (always loaded, kept lean): tech stack, code conventions, a one-line **Key Decisions** digest, session workflow |
| [`docs/process.md`](docs/process.md) | How we work: where truth lives, the spec lifecycle, the reviewer contract, the completion ritual |
| [`docs/decisions.md`](docs/decisions.md) | The **Key Decisions register in full** — reasoning + the "do NOT build" fences |
| [`docs/architecture.md`](docs/architecture.md) | System design: auth flow, authorization model, the bucket model, control planes, env vars, deployment, known constraints |
| [`docs/transition_plan.md`](docs/transition_plan.md) | The client-environment transition — IdC federation, de-provisioning, Lake Formation re-keying |
| [`docs/lambda-rationale.md`](docs/lambda-rationale.md) | The long-form *why* behind `lambdas/` — sizing evidence, rejected designs, the traps |
| [`docs/component-inventory.md`](docs/component-inventory.md) | **Router** to the per-area inventories in [`docs/component-inventory/`](docs/component-inventory/) (reusable services / hooks / components / types / utilities) |
| [`docs/best-practices/INDEX.md`](docs/best-practices/INDEX.md) | Router to the domain rulebooks — React, Python, lambdas, accessibility |
| [`docs/specs/`](docs/specs/) | Feature specs — what each feature should do; [`INDEX.md`](docs/specs/INDEX.md) is status, [`ARCS.md`](docs/specs/ARCS.md) is arc narrative |
| [`docs/spec-delivery/`](docs/spec-delivery/) | Delivery records — what was actually built per spec, plus later-change amendments |
| [`docs/testing/e2e.md`](docs/testing/e2e.md) | **The** end-to-end validation guide; [`owed.md`](docs/testing/owed.md) is what it cannot settle, [`sessions.md`](docs/testing/sessions.md) is what has been run |
| [`docs/security-baseline.md`](docs/security-baseline.md) | Every scanner finding with a disposition, and the gate thresholds |
| [`docs/design/design-system.md`](docs/design/design-system.md) | Design tokens, typography, component patterns (the source of truth for the UI) |
| [`docs/templates/`](docs/templates/) | Spec + spec-completion templates |
| [`infra/bootstrap/README.md`](infra/bootstrap/README.md) | One-time remote-state (S3 + DynamoDB) bootstrap |
| [`.github/workflows/README.md`](.github/workflows/README.md) | CI/CD workflows + first-time GitHub Actions configuration |

---

## Conventions & where to find things

- **Code conventions** (TypeScript strict, named exports, `ServiceResult<T>` from services that
  never throw, feature‑folder structure, file‑naming) are defined in [`CLAUDE.md`](CLAUDE.md).
- **Feature code** lives in `apps/portal/src/features/<feature>/`; shared UI primitives in
  `apps/portal/src/components/`; AWS clients in `apps/portal/src/lib/`.
- **Before reusing code**, check [`docs/component-inventory.md`](docs/component-inventory.md) and
  open the area file(s) it routes you to.
- **Infrastructure** is organized as bounded‑context modules under `infra/modules/`; IAM policies
  are `.tftpl` templates rendered with `templatefile()`. New resource types must also be granted
  to the deploy role (`infra/modules/base/`).
