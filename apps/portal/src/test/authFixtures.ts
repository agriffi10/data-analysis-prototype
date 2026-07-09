import {vi} from 'vitest';
import type {AuthContextValue, AuthUser} from '../features/auth/auth.types';

/**
 * Builds an `AuthContextValue` for injection via `renderWithProviders({auth})`.
 * Defaults to an authenticated user `alice`; override any field. The
 * sign-in/up/out actions are no-op spies so a test can assert they were called
 * without wiring Amplify.
 */
export function authValue(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    status: 'authenticated',
    user: {username: 'alice'},
    error: null,
    signIn: vi.fn().mockResolvedValue(undefined),
    signUp: vi.fn().mockResolvedValue(undefined),
    signOut: vi.fn().mockResolvedValue(undefined),
    ...overrides
  };
}

/** Authenticated as `username` (default `alice`). */
export function authenticated(username = 'alice', user: Partial<AuthUser> = {}): AuthContextValue {
  return authValue({status: 'authenticated', user: {username, ...user}});
}

/** Signed out. */
export function unauthenticated(): AuthContextValue {
  return authValue({status: 'unauthenticated', user: null});
}

/** Auth still resolving. */
export function authLoading(): AuthContextValue {
  return authValue({status: 'loading', user: null});
}
