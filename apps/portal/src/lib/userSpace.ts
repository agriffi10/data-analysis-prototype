/**
 * The user-space bucket name (`VITE_S3_USER_SPACE_BUCKET`), read at call time.
 *
 * Read at call time (not module load) so tests can `vi.stubEnv` it — a module-level
 * `import.meta.env` const is captured before the stub runs. The single source for the
 * bucket every per-user read/write service targets.
 */
export function userSpaceBucket(): string {
  return import.meta.env.VITE_S3_USER_SPACE_BUCKET as string;
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
 * userSettingsKey('alice', 'saved-queries.json') // 'alice/user_settings/saved-queries.json'
 */
export function userSettingsKey(username: string, file: string): string {
  return `${username}/user_settings/${file}`;
}
