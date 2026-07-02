import {getCurrentUser, fetchAuthSession, signInWithRedirect, signOut} from 'aws-amplify/auth';
import type {AuthUser} from './auth.types';
import type {ServiceResult} from '../../types/service.types';

// Wraps Amplify auth calls in the project ServiceResult shape. These functions
// never throw — callers branch on `success`.

function toError(
  err: unknown,
  fallback: string
): {
  message: string;
  code?: string;
} {
  const e = err as {message?: string; name?: string};
  return {message: e.message ?? fallback, code: e.name};
}

/**
 * Resolves the currently signed-in user, or an error when there is no session.
 * Email is best-effort (from the id token / user attributes) — its absence does
 * not fail the call.
 */
export async function getCurrentAuthUser(): Promise<ServiceResult<AuthUser>> {
  try {
    const {username} = await getCurrentUser();

    // Email comes from the ID token's claims, NOT fetchUserAttributes()/GetUser:
    // the Hosted UI access token lacks the `aws.cognito.signin.user.admin` scope
    // GetUser requires, so calling it 400s. Email stays best-effort.
    let email: string | undefined;
    try {
      const session = await fetchAuthSession();
      const claim = session.tokens?.idToken?.payload?.email;
      email = typeof claim === 'string' ? claim : undefined;
    } catch {
      // The session/claim is optional; username alone is a valid authenticated user.
    }

    return {success: true, data: {username, email}};
  } catch (err) {
    return {success: false, error: toError(err, 'Not signed in')};
  }
}

/** Begins the Hosted UI sign-in (full-page redirect to Cognito). */
export async function startSignIn(): Promise<ServiceResult<void>> {
  try {
    await signInWithRedirect();
    return {success: true, data: undefined};
  } catch (err) {
    return {success: false, error: toError(err, 'Unable to start sign-in')};
  }
}

/**
 * Begins Hosted UI account creation via the same Amplify-managed
 * `signInWithRedirect` flow as sign-in (the Hosted UI login page links to
 * "Sign up"). Amplify must initiate the redirect itself — otherwise it holds no
 * PKCE verifier/state and the returning authorization code is never exchanged,
 * landing the user signed-out. Cognito exposes no authorize-endpoint param to
 * open the signup form directly, so the login screen is the entry point.
 */
export async function startSignUp(): Promise<ServiceResult<void>> {
  return startSignIn();
}

/** Signs out locally and through the Hosted UI logout endpoint. */
export async function startSignOut(): Promise<ServiceResult<void>> {
  try {
    await signOut();
    return {success: true, data: undefined};
  } catch (err) {
    return {success: false, error: toError(err, 'Unable to sign out')};
  }
}
