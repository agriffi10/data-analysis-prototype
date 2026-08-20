/**
 * The `VITE_*` surface, in one place.
 *
 * Vite inlines `import.meta.env.VITE_*` as a literal at build time, so a variable that
 * was not set when the bundle was built is `undefined` forever — the failure surfaces
 * far from its cause, as a generic SDK error about a bucket named "undefined". This
 * module names the set, classifies it, and (in dev) says so out loud at boot.
 *
 * EVERY READ IS AT CALL TIME, never at module load: a module-level const captures the
 * value before `vi.stubEnv` runs, so a test would silently exercise the deployed names
 * instead of its own. That is why `isPortalConfigured` is a function where
 * `lib/amplify.ts`'s `isAmplifyConfigured` is a const — Amplify configures itself at
 * import, this does not.
 */

/**
 * Variables the portal cannot work at all without: the region every SDK client needs,
 * the four Cognito values that make sign-in possible, and the bucket every read and
 * write targets.
 *
 * The queue URLs are NOT here — each enqueue path degrades on its own through
 * `enqueueFifo`'s `notConfiguredMessage`, which disables one feature rather than the
 * app. Nor is the shared-space bucket (a user may belong to no shared space), nor
 * `VITE_COGNITO_IDENTITY_POOL_ID` (sign-in works without it; only credentials don't),
 * which is the same line `isAmplifyConfigured` draws. The test for membership is
 * whether SOMETHING catches its absence and says so — not whether the app is useful
 * without it.
 */
export const REQUIRED_ENV = [
  'VITE_AWS_REGION',
  'VITE_COGNITO_USER_POOL_ID',
  'VITE_COGNITO_USER_POOL_CLIENT_ID',
  'VITE_COGNITO_DOMAIN',
  'VITE_APP_URL',
  'VITE_S3_USER_SPACE_BUCKET',
  // Required because it has NO degraded path: `query.service.ts` passes it straight to
  // Athena, and an unset workgroup silently falls back to the account default — which
  // the portal role cannot use, so every query fails with a raw AccessDenied. That is
  // exactly the far-from-its-cause failure this module exists to name.
  'VITE_ATHENA_WORKGROUP'
] as const;

/** Set in a working deployment, but each with its own degraded path when absent. */
export const OPTIONAL_ENV = [
  // Which block of the feature-flag document this build resolves. Optional
  // because its degraded path is total: an unset value resolves to the document's own
  // `defaults` and still reports 'ready'. Nothing is unavailable without it, so it fails
  // the REQUIRED_ENV membership test above — but a build that ships it unset silently
  // ignores every per-environment override, which is why the flags feature owes a live
  // check that reads 'ready' rather than merely looking right.
  'VITE_ENVIRONMENT',
  'VITE_COGNITO_IDENTITY_POOL_ID',
  'VITE_S3_SHARED_SPACE_BUCKET',
  'VITE_MAX_UPLOAD_BYTES',
  'VITE_SHARED_SPACE_QUEUE_URL',
  'VITE_NOTIFICATIONS_QUEUE_URL',
  'VITE_TABLE_BUILD_QUEUE_URL',
  'VITE_TABLE_SHARE_QUEUE_URL',
  'VITE_DATA_QUALITY_QUEUE_URL',
  'VITE_FILE_SEND_QUEUE_URL',
  'VITE_ARCHIVE_QUEUE_URL',
  'VITE_FILE_OPS_QUEUE_URL'
] as const;

export type RequiredEnvVar = (typeof REQUIRED_ENV)[number];
export type OptionalEnvVar = (typeof OPTIONAL_ENV)[number];
export type PortalEnvVar = RequiredEnvVar | OptionalEnvVar;

/**
 * One typed read of one `VITE_*` variable. An empty string reads as unset — an unset
 * GitHub repository variable interpolates to `""` in the build, which is the deploy
 * mistake this whole module exists to name.
 *
 * The dev-unauth variables are deliberately absent from `PortalEnvVar`: they are read
 * behind an `import.meta.env.DEV` guard at their own call sites, and the bypass
 * guard asserts that the set of modules naming that flag is exactly those sites — so
 * this module must not name it either.
 */
export function envVar(name: PortalEnvVar): string | undefined {
  const value = readEnv()[name];
  return value === '' ? undefined : value;
}

/**
 * Every read here is a LITERAL `import.meta.env.VITE_X` member expression, and that is
 * load-bearing rather than verbose.
 *
 * Vite can only substitute what it can see statically: a computed index
 * (`import.meta.env[name]`) makes it emit the WHOLE env object into the bundle — every
 * `VITE_*` variable present at build time, including ones this app never names. That
 * would silently void the guarantee `lib/s3Client.ts` documents and depends on, which is
 * that a dev-only access key cannot reach a production bundle even though a `DEV` branch
 * references it. Measured, not assumed: with a computed index, a
 * `VITE_AWS_SECRET_ACCESS_KEY` set at build time appears verbatim in `dist/assets/`.
 *
 * Built inside the function, never at module load, so `vi.stubEnv` is still seen.
 */
function readEnv(): Record<PortalEnvVar, string | undefined> {
  return {
    VITE_AWS_REGION: import.meta.env.VITE_AWS_REGION as string | undefined,
    VITE_COGNITO_USER_POOL_ID: import.meta.env.VITE_COGNITO_USER_POOL_ID as string | undefined,
    VITE_COGNITO_USER_POOL_CLIENT_ID: import.meta.env.VITE_COGNITO_USER_POOL_CLIENT_ID as string | undefined,
    VITE_COGNITO_DOMAIN: import.meta.env.VITE_COGNITO_DOMAIN as string | undefined,
    VITE_APP_URL: import.meta.env.VITE_APP_URL as string | undefined,
    VITE_S3_USER_SPACE_BUCKET: import.meta.env.VITE_S3_USER_SPACE_BUCKET as string | undefined,
    VITE_ATHENA_WORKGROUP: import.meta.env.VITE_ATHENA_WORKGROUP as string | undefined,
    VITE_ENVIRONMENT: import.meta.env.VITE_ENVIRONMENT as string | undefined,
    VITE_COGNITO_IDENTITY_POOL_ID: import.meta.env.VITE_COGNITO_IDENTITY_POOL_ID as string | undefined,
    VITE_S3_SHARED_SPACE_BUCKET: import.meta.env.VITE_S3_SHARED_SPACE_BUCKET as string | undefined,
    VITE_MAX_UPLOAD_BYTES: import.meta.env.VITE_MAX_UPLOAD_BYTES as string | undefined,
    VITE_SHARED_SPACE_QUEUE_URL: import.meta.env.VITE_SHARED_SPACE_QUEUE_URL as string | undefined,
    VITE_NOTIFICATIONS_QUEUE_URL: import.meta.env.VITE_NOTIFICATIONS_QUEUE_URL as string | undefined,
    VITE_TABLE_BUILD_QUEUE_URL: import.meta.env.VITE_TABLE_BUILD_QUEUE_URL as string | undefined,
    VITE_TABLE_SHARE_QUEUE_URL: import.meta.env.VITE_TABLE_SHARE_QUEUE_URL as string | undefined,
    VITE_DATA_QUALITY_QUEUE_URL: import.meta.env.VITE_DATA_QUALITY_QUEUE_URL as string | undefined,
    VITE_FILE_SEND_QUEUE_URL: import.meta.env.VITE_FILE_SEND_QUEUE_URL as string | undefined,
    VITE_ARCHIVE_QUEUE_URL: import.meta.env.VITE_ARCHIVE_QUEUE_URL as string | undefined,
    VITE_FILE_OPS_QUEUE_URL: import.meta.env.VITE_FILE_OPS_QUEUE_URL as string | undefined
  };
}

/** Which required variables are missing right now — empty when the portal is configured. */
export function missingRequiredEnv(): RequiredEnvVar[] {
  return REQUIRED_ENV.filter((name) => envVar(name) === undefined);
}

/** True when every `REQUIRED_ENV` variable is set. */
export function isPortalConfigured(): boolean {
  return missingRequiredEnv().length === 0;
}

/**
 * Name the missing variables at boot, in dev only.
 *
 * Production stays silent on purpose: the deployed app must not print its own
 * configuration to a user's console, and the place a missing variable is actually
 * caught in production is the deploy workflow's build env (the `VITE_*` gotcha the
 * `.env.example` notes call out per queue).
 */
export function warnIfMisconfigured(): void {
  if (!import.meta.env.DEV) return;
  const missing = missingRequiredEnv();
  if (missing.length > 0) {
    console.warn(`[env] missing required variables: ${missing.join(', ')} — see apps/portal/.env.example`);
  }
}
