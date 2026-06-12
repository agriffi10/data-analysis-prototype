import {
  getCurrentUser,
  fetchAuthSession,
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

/**
 * Begins Hosted UI sign-up via a full-page navigation to the Cognito `/signup`
 * endpoint. Amplify's `signInWithRedirect` only targets the login screen, so the
 * authorization-code URL is built by hand from the same env config Amplify uses
 * (domain, SPA client id, app URL) — `response_type=code` + the openid/email/
 * profile scopes, matching the User Pool client (SPEC-006). Returns an error
 * instead of navigating to a broken URL when that config is missing. Synchronous:
 * on success the browser leaves the page, so nothing after the call runs.
 */
export function startSignUp(): ServiceResult<void> {
  const domain = import.meta.env.VITE_COGNITO_DOMAIN as string | undefined;
  const clientId = import.meta.env.VITE_COGNITO_USER_POOL_CLIENT_ID as
    | string
    | undefined;
  const appUrl = import.meta.env.VITE_APP_URL as string | undefined;

  if (!domain || !clientId || !appUrl) {
    return {
      success: false,
      error: {
        message: 'Sign-up is not configured. Set the Cognito environment variables.',
      },
    };
  }

  const url =
    `https://${domain}/signup?client_id=${clientId}` +
    `&response_type=code&scope=openid+email+profile` +
    `&redirect_uri=${encodeURIComponent(appUrl)}`;

  window.location.assign(url);
  return { success: true, data: undefined };
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
