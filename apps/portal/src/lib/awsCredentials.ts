import {fetchAuthSession} from 'aws-amplify/auth';
import type {ServiceResult} from '../types/service.types';

// The Cognito Identity Pool credentials Amplify holds for the signed-in user.
type SessionCredentials = NonNullable<Awaited<ReturnType<typeof fetchAuthSession>>['credentials']>;

/**
 * Fetches the signed-in user's scoped Identity Pool credentials.
 *
 * Shared by the Athena/Glue/SQS client builders. `forceRefresh` drives the
 * credential-expiry retry path. Never throws — returns a ServiceResult.
 */
export async function getSessionCredentials(forceRefresh = false): Promise<ServiceResult<SessionCredentials>> {
  try {
    const session = await fetchAuthSession({forceRefresh});
    if (!session.credentials) {
      return {
        success: false,
        error: {message: 'No AWS credentials — sign in required', code: 'NotAuthenticated'}
      };
    }
    return {success: true, data: session.credentials};
  } catch (err) {
    const e = err as {message?: string; name?: string};
    return {
      success: false,
      error: {
        message: e.message ?? 'Failed to obtain AWS credentials',
        code: e.name
      }
    };
  }
}

/**
 * Fetches the signed-in user's Cognito ID token (JWT).
 *
 * Control-plane requests carry this token so the backend can verify it and
 * derive the actor from the `cognito:username` claim — the caller's identity
 * is never client-asserted. Never throws — returns a ServiceResult.
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
    const e = err as {message?: string; name?: string};
    return {
      success: false,
      error: {
        message: e.message ?? 'Failed to obtain ID token',
        code: e.name
      }
    };
  }
}
