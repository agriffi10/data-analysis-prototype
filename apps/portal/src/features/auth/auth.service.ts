import type {AuthUser} from './auth.types';
import type {ServiceResult} from '../../types/service.types';
import {assignDocument} from '../../lib/documentNavigation';
import {setReturnPathIfAbsent} from '../../lib/returnPath';

// The portal server's session routes, in the shape the rest of the app expects. The browser holds no
// token and no secret: the server signs in, keeps the session, and answers who is signed in. These
// functions never throw — callers branch on `success`.

/** Where a sign-in or a sign-up starts: the server's route, which redirects to Managed Login. */
const LOGIN_ROUTE = '/auth/login';

/** Where the post-sign-in landing defaults to, unless the auth gate recorded a protected path. */
const DEFAULT_RETURN_PATH = '/files';

/**
 * A failure with no message of its own: the wording comes from the code, at the surface.
 *
 * @param code - The machine code.
 * @returns The failure.
 */
function failure<T>(code: string): ServiceResult<T> {
  return {success: false, error: {message: '', code}};
}

/**
 * Whether a body is the user `/auth/session` answers.
 *
 * @param body - The parsed body.
 * @returns True for an object with a non-empty string `username` and, if present, a string `email`.
 */
function isAuthUser(body: unknown): body is AuthUser {
  if (typeof body !== 'object' || body === null) return false;
  const {username, email} = body as Record<string, unknown>;
  return typeof username === 'string' && username !== '' && (email === undefined || typeof email === 'string');
}

/**
 * Who is signed in, from the server's session.
 *
 * A 401 is signed out, as `SessionExpired`, which the provider shows nothing for. A 503, any other
 * answer and a network failure are signed out as well, but as `ApiUnavailable`, which it shows: the
 * server holds that a fault is not a sign-out, and a developer whose AWS credentials have lapsed should
 * read "unavailable" rather than nothing at all.
 *
 * @returns The user, or why there is none.
 */
export async function getCurrentAuthUser(): Promise<ServiceResult<AuthUser>> {
  let response: Response;
  try {
    response = await fetch('/auth/session', {credentials: 'same-origin', cache: 'no-store'});
  } catch {
    return failure('ApiUnavailable');
  }
  if (response.status === 401) return failure('SessionExpired');
  if (response.status !== 200) return failure('ApiUnavailable');
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return failure('ApiUnavailable');
  }
  if (!isAuthUser(body)) return failure('ApiUnavailable');
  return {success: true, data: body.email === undefined ? {username: body.username} : body};
}

/**
 * Begin a sign-in: record where to land, then move the document to the server's sign-in route.
 *
 * The landing defaults to the files page without replacing a specific protected path the auth gate
 * may have recorded.
 *
 * @returns Success; the document is leaving.
 */
export async function startSignIn(): Promise<ServiceResult<void>> {
  setReturnPathIfAbsent(DEFAULT_RETURN_PATH);
  assignDocument(LOGIN_ROUTE);
  return {success: true, data: undefined};
}

/**
 * Begin creating an account. Managed Login's sign-in page links to sign-up, and the provider exposes
 * no parameter that opens the sign-up form directly, so this starts the same sign-in.
 *
 * @returns Success; the document is leaving.
 */
export async function startSignUp(): Promise<ServiceResult<void>> {
  return startSignIn();
}

/**
 * Whether the server's answer to a sign-out names a provider logout page the document may move to.
 *
 * @param body - The parsed body.
 * @returns The URL, or undefined when the body carries no absolute HTTPS `logoutUrl`.
 */
function logoutUrlOf(body: unknown): string | undefined {
  const value = typeof body === 'object' && body !== null ? (body as Record<string, unknown>).logoutUrl : undefined;
  if (typeof value !== 'string') return undefined;
  try {
    return new URL(value).protocol === 'https:' ? value : undefined;
  } catch {
    return undefined;
  }
}

/**
 * End the server's session, then move the document to the provider's logout page.
 *
 * The document moves **only on a 200** naming that page. On any failure it stays where it is and the
 * user stays signed in: navigating anyway would reload the page, find the session the failed call left
 * alive, and sign the user back in while they believe they signed out.
 *
 * @returns Success when the document is leaving, or why the sign-out failed.
 */
export async function startSignOut(): Promise<ServiceResult<void>> {
  let response: Response;
  try {
    response = await fetch('/auth/logout', {method: 'POST', credentials: 'same-origin'});
  } catch {
    return failure('ApiUnavailable');
  }
  if (response.status !== 200) return failure(response.status === 403 ? 'AccessDenied' : 'ApiUnavailable');
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return failure('ApiUnavailable');
  }
  const logoutUrl = logoutUrlOf(body);
  if (logoutUrl === undefined) return failure('ApiUnavailable');
  assignDocument(logoutUrl);
  return {success: true, data: undefined};
}
