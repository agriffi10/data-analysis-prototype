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

    // Email comes from the ID token's claims (we request the `email` OAuth scope),
    // NOT from fetchUserAttributes()/GetUser: the Hosted UI access token lacks the
    // `aws.cognito.signin.user.admin` scope that GetUser requires, so calling it
    // 400s with "Access Token does not have required scopes". Reading the claim
    // avoids that failed request entirely. Email stays best-effort.
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
 * Begins Hosted UI account creation. Delegates to the same Amplify-managed
 * `signInWithRedirect` flow as sign-in (the Hosted UI login page links to
 * "Sign up"). A previous version hand-built the Cognito `/signup` URL to deep-link
 * the signup form, but because Amplify never initiated that flow it had no stored
 * PKCE verifier/state, so the authorization code returned by Cognito was never
 * exchanged — the user landed signed-out and had to sign in again. Routing through
 * Amplify lets it own the round-trip end-to-end, so account creation completes
 * signed-in. Cognito's classic Hosted UI exposes no authorize-endpoint param to
 * open the signup form directly, so we accept the login screen as the entry point.
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
