import type { ServiceResult } from '../types/service.types';

// SDK error names that mean the temporary credentials have expired mid-session
// (SPEC-011/013). On these, an authenticated operation is retried once after a
// forced credential refresh before the error is surfaced.
export const EXPIRY_ERROR_CODES = new Set([
  'ExpiredToken',
  'ExpiredTokenException',
  'CredentialsProviderError',
  'InvalidToken',
]);

export function isExpiryError(code?: string): boolean {
  return code !== undefined && EXPIRY_ERROR_CODES.has(code);
}

// Run a service operation with an authenticated client, transparently refreshing
// the credentials and retrying ONCE if they expired mid-session (the SPEC-011/013
// pattern, extracted here in SPEC-034 FR-001 so the S3, Athena, and Glue clients
// share one implementation). `getClient(forceRefresh?)` returns a
// `ServiceResult<Client>`; `op(client)` performs the call and must surface a
// credential-expiry failure via its error `code` so this helper knows to refresh
// and retry. Never throws — propagates the ServiceResult error shape.
export async function withCredentialRetry<C, T>(
  getClient: (forceRefresh?: boolean) => Promise<ServiceResult<C>>,
  op: (client: C) => Promise<ServiceResult<T>>,
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
