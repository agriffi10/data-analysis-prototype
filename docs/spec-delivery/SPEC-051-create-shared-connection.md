# Completed Spec — SPEC-051: Create Shared Connection

The first per-action verb of the shared-connections arc, and the first arc spec to touch the **app**. Delivered the **create** action end-to-end across 2 PRs (browser flow → pipeline verb).

## What was completed?

- **Browser (Phase 1):** `src/lib/sqsClient.ts` + `getIdToken()` (in `awsCredentials`); `src/features/shared-spaces/` — `enqueueSharedSpaceRequest` (one FIFO `SendMessage`, constant `MessageGroupId` for serial intake, `requestId` dedup, carries the verified ID token, `ServiceResult`, never throws), `CreateSharedConnectionDialog` (reuses `Modal`/`Input`/`Button` + `CATALOG_IDENTIFIER_RE`), `useCreateSharedConnection` (enqueue + optimistic **local** pending), types. New dep **`@aws-sdk/client-sqs`**; new **`VITE_SHARED_SPACE_QUEUE_URL`** (`.env.example` + `deploy-app.yml` + GH repo var).
- **Minimal Connections tab** (user decision): `PrimaryNav` entry + lazy `/connections` route + `ConnectionsPage` shell (New button + dialog + Toast + pending list). SPEC-052 enriches it.
- **Pipeline (Phase 2):** provisioner `create` verb — validate name **globally unique** (atomic conditional `PutObject If-None-Match:*` on the registry) + free slot → create prefix marker + Glue DB → LF-grant the portal role on the DB (DB + tables, mirrors SPEC-033) → assign the creator the next free `custom:shared_space_k` → write registry (`active`) + the creator's per-user cache. Idempotent (replay-safe slot reuse + upsert); a failure records terminal `failed` (registry + cache) with a reason.
- **Infra:** orchestrator policy `+ s3:Get/PutObject` on `user-space/*/user_settings/shared-connections.json`; orchestrator added to the **user-space bucket-policy Deny-exclusion**; one-time LF `DATA_LOCATION_ACCESS` grant for the portal role on the shared bucket; provisioner env `SHARED_SPACE_BUCKET`/`USER_SPACE_BUCKET`/`PORTAL_ROLE_ARN`/`MAX_SHARED_MEMBERSHIPS`.

Deviations (spec "Implementation Decisions"): minimal Connections tab now; ID token in the body (Pipe-robust); `DATA_LOCATION_ACCESS` as a one-time Terraform grant (not per-create); optimistic pending is local (pipeline owns the cache).

## What changed from earlier specs?

- **SPEC-035 `PrimaryNav`**: third tab (Connections). **SPEC-013 user-space bucket policy**: orchestrator added to the Deny-exclusion (privileged cross-user cache write). **SPEC-056 provisioner**: gains the `create` verb (was validate-only). No new deploy-role IAM / resource types.

## Verification

`npm run lint`/`build`/`test` green — **626 tests** (17 new: dialog, service, page integration). 13 Lambda unit tests (happy / collision / replay / slot-full→failed / replay-safe slot / forged-before-verb). **Deployed**; verified live: provisioner env + orchestrator cache-write grant + bucket-policy exclusion all present; a forged `create` → Step Function **FAILED** with no registry written (deployed code loads + validate gate works). The authorized-create live test needs a real user session (the app client allows only SRP/refresh, so no CLI-minted token) — documented in `docs/testing/e2e.md`.
