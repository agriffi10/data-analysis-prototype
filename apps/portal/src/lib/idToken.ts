import type {ServiceResult} from '../types/service.types';

/**
 * Ask the portal server to refresh the session's ID token now, so a membership granted a moment ago
 * reaches the API without a sign-out.
 *
 * The browser holds no token: the server keeps the session and attaches its ID token to every API
 * call, refreshing it first when it is near expiry. So an unforced call has nothing to do, and a forced
 * one posts `/auth/refresh`, which refreshes whatever the token's expiry. The name and the
 * `forceRefresh` argument are kept for the callers, which call it after a grant and ignore the result.
 * Never throws.
 *
 * @param forceRefresh - Refresh now, rather than leave it to the server's own schedule.
 * @returns Success, or the failure the server's answer maps to.
 */
export async function getIdToken(forceRefresh = false): Promise<ServiceResult<void>> {
  if (!forceRefresh) return {success: true, data: undefined};
  let response: Response;
  try {
    response = await fetch('/auth/refresh', {method: 'POST', credentials: 'same-origin'});
  } catch {
    return {success: false, error: {message: '', code: 'ApiUnavailable'}};
  }
  if (response.status === 204) return {success: true, data: undefined};
  const code = response.status === 401 ? 'SessionExpired' : response.status === 403 ? 'AccessDenied' : 'ApiUnavailable';
  return {success: false, error: {message: '', code}};
}
