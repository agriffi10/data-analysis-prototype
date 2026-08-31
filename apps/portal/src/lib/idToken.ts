import {fetchAuthSession} from 'aws-amplify/auth';
import type {ServiceResult} from '../types/service.types';

/**
 * Fetches the signed-in user's Cognito ID token (JWT).
 *
 * The API verifies this token and derives the actor from its `cognito:username` claim, so
 * the caller's identity is never client-asserted. `forceRefresh` re-mints it, which is how a
 * newly-granted shared-space claim reaches the API without a sign-out. Never throws —
 * returns a ServiceResult.
 */
export async function getIdToken(forceRefresh = false): Promise<ServiceResult<string>> {
  try {
    const session = await fetchAuthSession({forceRefresh});
    const idToken = session.tokens?.idToken?.toString();
    if (!idToken) {
      return {
        success: false,
        error: {message: 'No ID token — sign in required', code: 'NotAuthenticated'}
      };
    }
    return {success: true, data: idToken};
  } catch (err) {
    const e = (typeof err === 'object' && err !== null ? err : {}) as {message?: string; name?: string};
    return {
      success: false,
      error: {
        message: e.message ?? 'Failed to obtain ID token',
        code: e.name
      }
    };
  }
}
