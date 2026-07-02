import type {ServiceResult} from '../types/service.types';

/** SDK error names that mean the temporary credentials expired mid-session. */
export const EXPIRY_ERROR_CODES = new Set([
  'ExpiredToken',
  'ExpiredTokenException',
  'CredentialsProviderError',
  'InvalidToken'
]);

/** Whether a ServiceResult error code is a credential-expiry error. */
export function isExpiryError(code?: string): boolean {
  return code !== undefined && EXPIRY_ERROR_CODES.has(code);
}

/**
 * Runs a service operation with an authenticated client, transparently
 * refreshing the credentials and retrying ONCE if they expired mid-session.
 * Shared by the S3, Athena, Glue, and SQS call sites.
 *
 * `op(client)` must surface a credential-expiry failure via its error `code`
 * so this helper knows to refresh and retry. Never throws — propagates the
 * ServiceResult error shape.
 *
 * @param getClient - Client factory; called with `true` to force a refresh.
 * @param op - The authenticated call to run (and possibly re-run).
 *
 * @example
 * const result = await withCredentialRetry(getS3Client, (s3) => listObjects(s3, prefix));
 */
export async function withCredentialRetry<C, T>(
  getClient: (forceRefresh?: boolean) => Promise<ServiceResult<C>>,
  op: (client: C) => Promise<ServiceResult<T>>
): Promise<ServiceResult<T>> {
  const clientResult = await getClient();
  if (!clientResult.success) return clientResult;

  const result = await op(clientResult.data);
  if (result.success || !isExpiryError(result.error.code)) return result;

  // Credentials expired mid-session — refresh once and retry transparently.
  const refreshed = await getClient(true);
  if (!refreshed.success) return refreshed;
  return op(refreshed.data);
}
