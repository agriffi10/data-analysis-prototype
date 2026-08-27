/**
 * The `VITE_*` surface, and the only place it survives.
 *
 * A deployed portal reads `/config.json`; these variables are what answers a
 * `configValue` call in a dev build, where nothing renders that document. Every
 * reference below sits behind an `import.meta.env.DEV` branch at its call site, so a
 * production build deletes these tables outright — which is what stops one environment's
 * values being inlined into an artifact promoted to another.
 *
 * EVERY READ IS AT CALL TIME, never at module load: a module-level const captures the
 * value before `vi.stubEnv` runs, so a test would silently exercise the deployed names
 * instead of its own.
 */
import {REQUIRED_CONFIG} from '../types/runtimeConfig.types';
import type {RuntimeConfigKey} from '../types/runtimeConfig.types';

/**
 * Which `VITE_*` variable stands in for each runtime-configuration key, in a dev build.
 *
 * `null` means the key has no dev fallback at all. Every required key has one: the boot
 * warning below is driven from the classification, so a required key with no variable
 * would name nothing when it is missing — `[null].join()` is the empty string, and the
 * warning would fire forever saying nothing at all.
 *
 * `satisfies` rather than an annotation, so this is the SINGLE list of variable names —
 * `PortalEnvVar` is derived from it below, and `readEnv`'s table is then exhaustive
 * against it by the compiler. Two tables are unavoidable (see `readEnv`), but two lists
 * of names are not.
 *
 * The dev-unauth variables are deliberately absent: they are read behind an
 * `import.meta.env.DEV` guard at their own call sites, and a sweep asserts that the set
 * of modules naming those flags is exactly those sites — so this module must not name
 * them either.
 */
export const VITE_NAME = {
  appUrl: 'VITE_APP_URL',
  awsRegion: 'VITE_AWS_REGION',
  userSpaceBucket: 'VITE_S3_USER_SPACE_BUCKET',
  athenaWorkgroup: 'VITE_ATHENA_WORKGROUP',
  cognitoUserPoolId: 'VITE_COGNITO_USER_POOL_ID',
  cognitoUserPoolClientId: 'VITE_COGNITO_USER_POOL_CLIENT_ID',
  cognitoDomain: 'VITE_COGNITO_DOMAIN',
  apiBaseUrl: 'VITE_API_BASE_URL',
  environment: 'VITE_ENVIRONMENT',
  maxUploadBytes: 'VITE_MAX_UPLOAD_BYTES',
  sharedSpaceBucket: 'VITE_S3_SHARED_SPACE_BUCKET',
  cognitoIdentityPoolId: 'VITE_COGNITO_IDENTITY_POOL_ID',
  sharedSpaceQueueUrl: 'VITE_SHARED_SPACE_QUEUE_URL',
  notificationsQueueUrl: 'VITE_NOTIFICATIONS_QUEUE_URL',
  tableBuildQueueUrl: 'VITE_TABLE_BUILD_QUEUE_URL',
  tableShareQueueUrl: 'VITE_TABLE_SHARE_QUEUE_URL',
  dataQualityQueueUrl: 'VITE_DATA_QUALITY_QUEUE_URL',
  fileSendQueueUrl: 'VITE_FILE_SEND_QUEUE_URL',
  archiveQueueUrl: 'VITE_ARCHIVE_QUEUE_URL',
  fileOpsQueueUrl: 'VITE_FILE_OPS_QUEUE_URL'
} as const satisfies Record<RuntimeConfigKey, string | null>;

/** Every variable a dev fallback can read, derived from the table above. */
export type PortalEnvVar = Exclude<(typeof VITE_NAME)[RuntimeConfigKey], null>;

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
    VITE_API_BASE_URL: import.meta.env.VITE_API_BASE_URL as string | undefined,
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

/**
 * One configuration key's value from the local `.env`, for a dev build only.
 *
 * A container renders the runtime document from its task environment; a laptop has no
 * container, so `npm run dev` and the test suite answer from `import.meta.env` instead.
 * EVERY CALLER MUST GATE THIS ON `import.meta.env.DEV` AT THE CALL SITE — not inside,
 * and not in the consumer beyond. That gate is what lets the bundler delete this
 * function, `readEnv` and `VITE_NAME` from a production build, and their deletion is
 * what a production bundle's freedom from build-time configuration rests on.
 *
 * An empty string reads as unset: an unset repository variable interpolates to `""`.
 *
 * @param key - The configuration key to answer.
 * @returns The local value, or `undefined` when it is unset or the key has no variable.
 */
export function devFallbackValue(key: RuntimeConfigKey): string | undefined {
  const name = VITE_NAME[key];
  if (name === null) return undefined;
  const value = readEnv()[name];
  return value === '' ? undefined : value;
}

/**
 * Name the missing variables at boot, in dev only.
 *
 * Driven by the runtime classification rather than a list of its own, so a key that
 * becomes required stays covered here. Production has its own hard failure and prints
 * nothing but the key names.
 *
 * @returns None.
 */
export function warnIfMisconfigured(): void {
  if (!import.meta.env.DEV) return;
  const missing = REQUIRED_CONFIG.filter((key) => devFallbackValue(key) === undefined).map((key) => VITE_NAME[key]);
  if (missing.length > 0) {
    console.warn(`[env] missing required variables: ${missing.join(', ')} — see apps/portal/.env.example`);
  }
}
