import {envVar} from './env';

/**
 * The user-space bucket name (`VITE_S3_USER_SPACE_BUCKET`), read at call time.
 *
 * Read at call time (not module load) so tests can `vi.stubEnv` it — a module-level
 * `import.meta.env` const is captured before the stub runs. The single source for the
 * bucket every per-user read/write service targets.
 */
export function userSpaceBucket(): string {
  return envVar('VITE_S3_USER_SPACE_BUCKET') as string;
}

/**
 * The shared-space bucket name (`VITE_S3_SHARED_SPACE_BUCKET`), read at call time.
 *
 * Bucket 2 — every shared space's prefix, and where a shared-database query writes its
 * results. Same call-time rule as `userSpaceBucket`.
 */
export function sharedSpaceBucket(): string {
  return envVar('VITE_S3_SHARED_SPACE_BUCKET') as string;
}

/**
 * Both space buckets as a pair, each `undefined` when unset.
 *
 * The honest shape for the callers that must decide what a space RESOLVES to — the
 * data-quality hooks, the file browser page and the query workspace all branch on
 * whether a bucket is configured, and an unset one must read as absent rather than as
 * the string "undefined". The unwrapped getters above stay for the services, which
 * target one known bucket and have nothing to decide.
 */
export function spaceBuckets(): {user?: string; shared?: string} {
  return {
    user: envVar('VITE_S3_USER_SPACE_BUCKET'),
    shared: envVar('VITE_S3_SHARED_SPACE_BUCKET')
  };
}

/**
 * The S3 key of a per-user document in the protected `user_settings/` folder:
 * `{username}/user_settings/{file}`.
 *
 * `user_settings/` is IAM-protected (the browser reads; a pipeline or the user's own
 * scoped writes own each file) and hidden from the file browser. Single-sources the
 * path template shared by saved queries, query history, notifications, and the
 * shared-connections cache.
 *
 * @param username - The signed-in user's prefix (their S3 namespace).
 * @param file - The document basename, e.g. `'notifications.json'`.
 *
 * @example
 * userSettingsKey('alice', 'query-history.json') // 'alice/user_settings/query-history.json'
 */
export function userSettingsKey(username: string, file: string): string {
  return `${username}/user_settings/${file}`;
}
