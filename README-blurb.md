# Data Quarry

A web portal where authenticated users bring their own data, manage it, and query it with SQL — mostly straight from the browser. A React + TypeScript SPA talks directly to AWS using short-lived, scoped credentials, with an HTTP API and eight async control planes behind it for the work a browser session must not be trusted with.

## What users can do

- **Upload & manage files** in their own private S3 space — download, move, rename, copy, delete, and organize into folders, with a familiar filesystem-style UX.
- **Define tables over their data** — register schemas in the Glue Data Catalog and create views directly from the app.
- **Query with SQL through Amazon Athena** — an in-app query workspace (Monaco editor, schema browser, multi-tab, multi-statement scripts) runs interactive, cross-database queries and saves results back to their own files.
- **Share tables and workspaces** — push a table into another user's or a shared space's catalog, or collaborate in shared connections, all driven by serverless control planes rather than a server you have to run.

## Security model — tenancy enforced at the IAM layer, not in app code

Every user is confined to their own data by AWS, not by application logic. The API stamps a verified `username` principal tag **server-side** onto the session it assumes for each request (ABAC), and a single shared IAM role scopes S3 prefixes, Glue databases/tables, and Athena results to `${aws:PrincipalTag/username}` — so tenancy can't be spoofed by the client. Lake Formation registers the user-space bucket in **hybrid mode** to extend the exact same isolation model to the analytics catalog. Because isolation lives in the trust policy and IAM conditions, there's no application code path that can accidentally leak one tenant's data to another.

## Everything is Infrastructure as Code

The entire stack — auth, storage, static hosting, the analytics catalog, the async control planes, and every per-user IAM policy — is provisioned with **OpenTofu**. Nothing is clicked together by hand in the console.

- **Bounded-context modules.** Infrastructure is split into focused modules (`auth`, `data`, `analytics`, `app`, `base`, `notifications`, and the `shared-spaces` / `table-builder` / `table-share` control planes) so each concern owns its own resources and blast radius.
- **IAM as templates.** Access policies are `.tftpl` templates rendered with `templatefile()`, so the ABAC rules that enforce tenancy are themselves version-controlled, reviewed, and diffable — not ambient console state.
- **Managed remote state.** State lives in an S3 backend with a DynamoDB lock table, so concurrent applies are serialized and state is never corrupted.
- **Async control planes as code.** The mutation-heavy operations (creating shared spaces, building tables, sharing tables) run as fully declarative serverless pipelines — FIFO SQS → EventBridge Pipes → Step Functions orchestrating single-task Lambdas — all defined in OpenTofu alongside the rest of the stack.

## Shipped through GitHub Actions — with real quality gates

Deployment is OIDC-based end to end: GitHub Actions assumes an AWS role via short-lived tokens, so **there are no long-lived cloud keys stored anywhere**. Three pipelines keep app, infra, and Lambda code independently deployable, and nothing reaches `main` without passing the gates.

**On every pull request, the frontend CI must pass:**

- **TypeScript strict build** (`tsc -b && vite build`) — a type error is a failed build.
- A **bundle assertion** that no `VITE_` name survives into the production output.

**The rest of the gates moved to a mandatory local pre-push run**, to keep CI minutes down: **ESLint** and **Prettier**, **Vitest** integration-style tests with **V8 coverage** (mocking only the AWS service boundary, so real hooks and components are exercised), the **`vitest-axe`** accessibility assertions, and the Python Lambdas' **`ruff`**, **`mypy`** and **`pytest`** — the latter with the real `polars` runtime, so schema-inference logic is tested for real rather than mocked away. They gate every pull request; they are enforced by the session that pushes rather than by a workflow.

**Infrastructure changes are gated too:** OpenTofu `fmt -check`, `validate`, and `plan` run on every infra PR, and the plan is **posted straight back to the PR as a comment** for review before anything is applied. Merges to `main` trigger `apply` automatically.

---

**Stack:** React 19 · Vite · TypeScript (strict) · TanStack Query · Cognito / Amplify · API Gateway + Lambda · Athena + Glue + Lake Formation · SQS + EventBridge Pipes + Step Functions · S3 · ECS Fargate + ALB · OpenTofu · GitHub Actions (OIDC)
