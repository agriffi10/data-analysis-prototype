# Completed Spec — SPEC-106: User-Facing Error Messaging

Raw AWS/Cognito/Athena error text is no longer shown to users anywhere. Every message is now
either a one-sentence fix or "Contact the Administrator." Shipped in two PRs: SPA (#216) + Lambda
sanitization (#217).

## What was completed?

- **One SPA mapping module** — `lib/errorMessages.ts` `toUserMessage(error) → {title?, message}`
  resolves app `code` → AWS/Cognito `name` → Athena engine-message pattern → generic fallback;
  never echoes raw input (except `passthrough` app codes our services author, e.g. `Collision`).
  Original error is console-logged in **dev builds only** (`import.meta.env.DEV`). Each rule carries
  a trigger comment + `userFixable`.
- **Unified surfacing** — app-level `ToastProvider`/`useToast` (hook in `toastContext.ts`) +
  `ErrorBanner`; the four per-page toasts (Query/Connections/CreateTable/Notifications) and the
  inline raw-error sites (`UploadList`, `DatabaseNode` schema-load, `Header` auth, file-browser +
  connections banners) all render mapped text. Errors are mapped at the **code-in-scope boundary**
  (service-call site / hook / provider), not by rendering `result.error.message`.
- **Query + missed-info wording** — the FAILED banner (now prose, not a raw `<code>` block),
  Create-view/Drop toasts, and `getTableDdl` map common Athena failures; the unqualified-table case
  (SPEC-077, no active DB) → *"Add a database to each table, like `mydb.sales`."* Raw
  `stateChangeReason` stays in history + the dev log.
- **FR-002 plumbing** — `deleteObjects` per-key + move/copy per-key/summary errors carry a `code`
  the surface maps; `ServiceResult` shape unchanged. Credential helpers carry a `NotAuthenticated`
  code → "Sign in to continue."
- **FR-007** — `CATALOG_IDENTIFIER_RULE` exported next to `CATALOG_IDENTIFIER_RE`; five hand-copied
  dialog strings now import it.
- **Lambda sanitization (FR-008/009)** — `tbcommon`/`tscommon` `messages.py` drop the raw Athena
  `{detail}` from the four DDL-failure bodies (`failure_message` no longer takes `detail`);
  shared-space `create_space.py`/`delete_space.py` replace `str(exc)` in the notification **and**
  the cache `reason` with friendly text (create keeps deliberate `ProvisioningError` wording via
  `_user_reason`). Raw text stays in logs + the SFN terminal / registry `failed` record.

Deviation: client-side validation strings already authored by us (e.g. the Create-view
target-database derivation) stay as-is — the mapper is for service/AWS errors, not our own copy.

## What changed from earlier specs?

- `ServiceResult` error `message` is now treated as **technical (logged, not rendered)**; surfaces
  read `code` via the mapper. The four per-page `useState<ToastState>` toasts are replaced by the
  app-level provider. `useNotifications` `onMutationError` now receives the error object, not a
  pre-extracted string. No user-facing docs (Help & guides, SPEC-074) changed — error wording isn't
  a documented guide topic, so the completion-ritual Help sweep is a no-op here.

## Verification

`tsc -b`, ESLint, 1060 SPA tests, and the prod build green locally (#216); 322 lambda tests + `ruff`
green (#217). Error paths need real AWS/Cognito to trigger live, so verification is the
integration-style test suite (real components rendering mapped text end-to-end), not a dev preview.
