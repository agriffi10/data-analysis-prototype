/**
 * The `VITE_*` surface, and the only place it survives: the test runner's configuration.
 *
 * A deployed portal and `next dev` both read `/config.json`, which the Next.js server renders;
 * these variables are what answers a `configValue` call under Vitest, where no server runs and a
 * test stubs a value with `vi.stubEnv('VITE_…')`. Every reference below sits behind an
 * `import.meta.env.MODE === 'test'` branch at its call site, so a production build deletes these
 * tables outright, which is what stops one environment's values being inlined into an artifact
 * promoted to another. Turbopack supplies no custom `VITE_*` names at all, so outside Vitest the
 * branch could only ever read nothing.
 *
 * EVERY READ IS AT CALL TIME, never at module load: a module-level const captures the
 * value before `vi.stubEnv` runs, so a test would silently exercise the deployed names
 * instead of its own.
 */
import type {RuntimeConfigKey} from '../types/runtimeConfig.types';

/**
 * Which `VITE_*` variable stands in for each runtime-configuration key, under the test runner.
 *
 * `null` means the key has no fallback at all. Every key has one today, so a test can stub any
 * key the browser reads.
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
  cognitoUserPoolId: 'VITE_COGNITO_USER_POOL_ID',
  cognitoUserPoolClientId: 'VITE_COGNITO_USER_POOL_CLIENT_ID',
  cognitoDomain: 'VITE_COGNITO_DOMAIN',
  apiBaseUrl: 'VITE_API_BASE_URL',
  environment: 'VITE_ENVIRONMENT',
  maxUploadBytes: 'VITE_MAX_UPLOAD_BYTES',
  sharedSpaceBucket: 'VITE_S3_SHARED_SPACE_BUCKET'
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
 * would emit every `VITE_*` present at build time into the artifact, named or not. Measured, not
 * assumed: with a computed index, a `VITE_AWS_SECRET_ACCESS_KEY` set at build time appeared
 * verbatim in `dist/assets/`. That variable is gone now, along with the dev-only S3 client whose
 * `DEV` branch referenced it — but the property is about the SUBSTITUTION, not about that one
 * secret, and it holds for whatever the next build-time value happens to be.
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
    VITE_ENVIRONMENT: import.meta.env.VITE_ENVIRONMENT as string | undefined,
    VITE_S3_SHARED_SPACE_BUCKET: import.meta.env.VITE_S3_SHARED_SPACE_BUCKET as string | undefined,
    VITE_MAX_UPLOAD_BYTES: import.meta.env.VITE_MAX_UPLOAD_BYTES as string | undefined
  };
}

/**
 * One configuration key's value from the test runner's environment.
 *
 * The Next.js server renders the runtime document from its environment, in a container and under
 * `next dev` alike; only the test suite, where no server runs, answers from `import.meta.env`.
 * EVERY CALLER MUST GATE THIS ON `import.meta.env.MODE === 'test'` AT THE CALL SITE — not inside,
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
