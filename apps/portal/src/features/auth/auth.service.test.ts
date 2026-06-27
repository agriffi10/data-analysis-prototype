import {describe, it, expect, vi, beforeEach, type MockedFunction} from 'vitest';
import {getCurrentAuthUser, startSignIn, startSignUp, startSignOut} from './auth.service';

vi.mock('aws-amplify/auth', () => ({
  getCurrentUser: vi.fn(),
  fetchAuthSession: vi.fn(),
  signInWithRedirect: vi.fn(),
  signOut: vi.fn()
}));

import {getCurrentUser, fetchAuthSession, signInWithRedirect, signOut} from 'aws-amplify/auth';

const mockGetCurrentUser = getCurrentUser as unknown as MockedFunction<() => Promise<unknown>>;
const mockFetchAuthSession = fetchAuthSession as unknown as MockedFunction<() => Promise<unknown>>;

// Build a fetchAuthSession result whose ID token carries the given email claim.
const sessionWithEmail = (email?: string) => ({
  tokens: {idToken: {payload: email ? {email} : {}}}
});
const mockSignInWithRedirect = signInWithRedirect as unknown as MockedFunction<() => Promise<void>>;
const mockSignOut = signOut as unknown as MockedFunction<() => Promise<void>>;

beforeEach(() => {
  vi.clearAllMocks();
});

describe('getCurrentAuthUser', () => {
  it('returns the username and email from the ID token claim when signed in', async () => {
    mockGetCurrentUser.mockResolvedValueOnce({username: 'alice'});
    mockFetchAuthSession.mockResolvedValueOnce(sessionWithEmail('alice@example.com'));

    const result = await getCurrentAuthUser();

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data).toEqual({username: 'alice', email: 'alice@example.com'});
  });

  it('returns the user without email when the ID token has no email claim', async () => {
    mockGetCurrentUser.mockResolvedValueOnce({username: 'bob'});
    mockFetchAuthSession.mockResolvedValueOnce(sessionWithEmail(undefined));

    const result = await getCurrentAuthUser();

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data).toEqual({username: 'bob', email: undefined});
  });

  it('returns success: false when there is no session (getCurrentUser throws)', async () => {
    const err = Object.assign(new Error('No current user'), {
      name: 'UserUnAuthenticatedException'
    });
    mockGetCurrentUser.mockRejectedValueOnce(err);

    const result = await getCurrentAuthUser();

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toBe('No current user');
    expect(result.error.code).toBe('UserUnAuthenticatedException');
    expect(mockFetchAuthSession).not.toHaveBeenCalled();
  });
});

describe('startSignIn', () => {
  it('invokes signInWithRedirect and returns success', async () => {
    mockSignInWithRedirect.mockResolvedValueOnce(undefined);

    const result = await startSignIn();

    expect(result.success).toBe(true);
    expect(mockSignInWithRedirect).toHaveBeenCalledOnce();
  });

  it('returns success: false without throwing when redirect fails', async () => {
    mockSignInWithRedirect.mockRejectedValueOnce(Object.assign(new Error('redirect blocked'), {name: 'RedirectError'}));

    const result = await startSignIn();

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toBe('redirect blocked');
    expect(result.error.code).toBe('RedirectError');
  });
});

describe('startSignUp', () => {
  // Account creation now routes through the same Amplify-managed Hosted UI
  // redirect as sign-in, so Amplify owns the OAuth round-trip and the returning
  // code is exchanged (the user lands signed-in). The classic Hosted UI has no
  // signup deep-link, so there's no hand-built URL to assert anymore.
  it('delegates to the Amplify Hosted UI redirect', async () => {
    mockSignInWithRedirect.mockResolvedValueOnce(undefined);

    const result = await startSignUp();

    expect(result.success).toBe(true);
    expect(mockSignInWithRedirect).toHaveBeenCalledOnce();
  });

  it('returns success: false without throwing when the redirect fails', async () => {
    mockSignInWithRedirect.mockRejectedValueOnce(Object.assign(new Error('redirect blocked'), {name: 'RedirectError'}));

    const result = await startSignUp();

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toBe('redirect blocked');
  });
});

describe('startSignOut', () => {
  it('invokes signOut and returns success', async () => {
    mockSignOut.mockResolvedValueOnce(undefined);

    const result = await startSignOut();

    expect(result.success).toBe(true);
    expect(mockSignOut).toHaveBeenCalledOnce();
  });

  it('returns success: false without throwing when signOut fails', async () => {
    mockSignOut.mockRejectedValueOnce(new Error('network down'));

    const result = await startSignOut();

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toBe('network down');
  });
});
