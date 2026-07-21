# Foundations (`apps/portal/src/lib/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `getS3Client(forceRefresh?)` | `lib/s3Client.ts` | Authenticated S3 client from Amplify/Identity-Pool creds; `ServiceResult<S3Client>`. Pass `true` to force a credential refresh on expiry. |
| `s3Client` | `lib/s3Client.ts` | Dev-only unsigned/static-cred S3 client singleton (SPEC-002 dev-unauth path). |
| `getAthenaClient(forceRefresh?)` / `getGlueClient(forceRefresh?)` | `lib/athenaClient.ts` / `lib/glueClient.ts` | Authenticated Athena/Glue clients from the same scoped Identity-Pool creds (SPEC-034); `ServiceResult<...Client>`. |
| `getSessionCredentials(forceRefresh?)` / `getIdToken(forceRefresh?)` | `lib/awsCredentials.ts` | Fetch the signed-in user's scoped Identity-Pool credentials (shared by the Athena/Glue/SQS client builders, SPEC-034); `getIdToken` returns the Cognito ID token JWT for server-side trusted-actor binding (SPEC-051/056). |
| `getSqsClient(forceRefresh?)` | `lib/sqsClient.ts` | Authenticated SQS client from Identity-Pool creds; `ServiceResult<SQSClient>`. The browser's only shared-space write is `sqs:SendMessage` to the control queue (SPEC-051). |
| `withCredentialRetry(getClient, op)` / `isExpiryError(code?)` | `lib/credentialRetry.ts` | Run an authenticated op with one transparent refresh-and-retry on credential-expiry; shared by the S3/Athena/Glue/SQS services (SPEC-034). |
| `queryClient` | `lib/queryClient.ts` | App-wide TanStack `QueryClient` (staleTime 30s, retry 1, no refetch-on-focus). |
| `invalidateListing(client, bucket, prefix)` | `lib/queryClient.ts` | Invalidate one prefix listing so the next read refetches (call after a mutation). |
| `isAmplifyConfigured` | `lib/amplify.ts` | Boolean — whether Cognito/Amplify env is configured. |
| `setReturnPath(path)` / `setReturnPathIfAbsent(path)` / `takeReturnPath()` | `lib/returnPath.ts` | Stash (always / only-if-empty) + consume a post-login return path. `IfAbsent` seeds a default (e.g. `/files`) at sign-in/up without clobbering an auth-gate-captured path. |
| `useCopyToClipboard(resetMs?)` | `lib/useCopyToClipboard.ts` | `{copied, copy(text)}` — writes to the clipboard and flags a transient confirm; never throws (insecure-context/denied = silent no-op). |
| `toUserMessage(error)` | `lib/errorMessages.ts` | Maps any caught value / `ServiceResult` error `{message, code}` → friendly `{title?, message}` (app code → AWS/Cognito name → Athena pattern → generic "Contact the Administrator"). **The single source of error wording** — never surface `error.message` directly; route it here. Dev-only original-error console log (SPEC-106). |
| `toServiceError(err, fallback)` / `unwrap(result)` | `lib/serviceResult.ts` | The `ServiceResult` adapters shared by every service/hook: `toServiceError` maps a caught value → the failure branch (`{message, code}`); `unwrap` returns a result's data or throws its error (with `.code` preserved) — the one bridge for TanStack query/mutation fns. |
| `isNotFound(err)` | `lib/s3Errors.ts` | True when an AWS SDK v3 error means "the S3 object doesn't exist" (`NoSuchKey` / `NotFound` / 404) — treat a missing settings/cache/history file as an empty default rather than an error. |
| `enqueueFifoRequest({queueUrl, notConfiguredMessage, build})` | `lib/enqueueFifo.ts` | The shared FIFO-SQS enqueue skeleton: guards the (call-time) queue URL, fetches the ID token and hands it to `build(idToken)` for the body + group/dedup + success data, sends via `withCredentialRetry`, maps failures via `toServiceError`. Backs every control-plane enqueue (table-builder / table-share / shared-spaces / notifications / data-quality). |
| `userSpaceBucket()` / `userSettingsKey(username, file)` | `lib/userSpace.ts` | The user-space bucket env read (call-time) + the protected `{username}/user_settings/{file}` key template — single source for the per-user read/write services. |

