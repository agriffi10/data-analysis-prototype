import {
  getCurrentUser,
  fetchUserAttributes,
  signInWithRedirect,
  signOut,
} from 'aws-amplify/auth';
import type { AuthUser } from './auth.types';
import type { ServiceResult } from '../../types/service.types';

// Wraps Amplify auth calls in the project ServiceResult shape. These functions
// never throw — callers branch on `success`.

function toError(err: unknown, fallback: string): {
  message: string;
  code?: string;
} {
  const e = err as { message?: string; name?: string };
  return { message: e.message ?? fallback, code: e.name };
}

/**
 * Resolves the currently signed-in user, or an error when there is no session.
 * Email is best-effort (from the id token / user attributes) — its absence does
 * not fail the call.
 */
export async function getCurrentAuthUser(): Promise<ServiceResult<AuthUser>> {
  try {
    const { username } = await getCurrentUser();

    let email: string | undefined;
    try {
      const attributes = await fetchUserAttributes();
      email = attributes.email;
    } catch {
      // Attributes are optional; username alone is a valid authenticated user.
    }

    return { success: true, data: { username, email } };
  } catch (err) {
    return { success: false, error: toError(err, 'Not signed in') };
  }
}

/** Begins the Hosted UI sign-in (full-page redirect to Cognito). */
export async function startSignIn(): Promise<ServiceResult<void>> {
  try {
    await signInWithRedirect();
    return { success: true, data: undefined };
  } catch (err) {
    return { success: false, error: toError(err, 'Unable to start sign-in') };
  }
}

/** Signs out locally and through the Hosted UI logout endpoint. */
export async function startSignOut(): Promise<ServiceResult<void>> {
  try {
    await signOut();
    return { success: true, data: undefined };
  } catch (err) {
    return { success: false, error: toError(err, 'Unable to sign out') };
  }
}
