import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  afterEach,
  type MockedFunction,
} from 'vitest';
import {
  getCurrentAuthUser,
  startSignIn,
  startSignUp,
  startSignOut,
} from './auth.service';

vi.mock('aws-amplify/auth', () => ({
  getCurrentUser: vi.fn(),
  fetchUserAttributes: vi.fn(),
  signInWithRedirect: vi.fn(),
  signOut: vi.fn(),
}));

import {
  getCurrentUser,
  fetchUserAttributes,
  signInWithRedirect,
  signOut,
} from 'aws-amplify/auth';

const mockGetCurrentUser = getCurrentUser as unknown as MockedFunction<
  () => Promise<unknown>
>;
const mockFetchUserAttributes = fetchUserAttributes as unknown as MockedFunction<
  () => Promise<unknown>
>;
const mockSignInWithRedirect = signInWithRedirect as unknown as MockedFunction<
  () => Promise<void>
>;
const mockSignOut = signOut as unknown as MockedFunction<() => Promise<void>>;

beforeEach(() => {
  vi.clearAllMocks();
});

describe('getCurrentAuthUser', () => {
  it('returns the username and email when signed in', async () => {
    mockGetCurrentUser.mockResolvedValueOnce({ username: 'alice' });
    mockFetchUserAttributes.mockResolvedValueOnce({ email: 'alice@example.com' });

    const result = await getCurrentAuthUser();

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data).toEqual({ username: 'alice', email: 'alice@example.com' });
  });

  it('returns the user without email when attributes are unavailable', async () => {
    mockGetCurrentUser.mockResolvedValueOnce({ username: 'bob' });
    mockFetchUserAttributes.mockRejectedValueOnce(new Error('no attributes'));

    const result = await getCurrentAuthUser();

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data).toEqual({ username: 'bob', email: undefined });
  });

  it('returns success: false when there is no session (getCurrentUser throws)', async () => {
    const err = Object.assign(new Error('No current user'), {
      name: 'UserUnAuthenticatedException',
    });
    mockGetCurrentUser.mockRejectedValueOnce(err);

    const result = await getCurrentAuthUser();

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toBe('No current user');
    expect(result.error.code).toBe('UserUnAuthenticatedException');
    expect(mockFetchUserAttributes).not.toHaveBeenCalled();
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
    mockSignInWithRedirect.mockRejectedValueOnce(
      Object.assign(new Error('redirect blocked'), { name: 'RedirectError' }),
    );

    const result = await startSignIn();

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toBe('redirect blocked');
    expect(result.error.code).toBe('RedirectError');
  });
});

describe('startSignUp', () => {
  const DOMAIN = 'example.auth.us-east-1.amazoncognito.com';
  let assignMock: MockedFunction<(url: string) => void>;

  beforeEach(() => {
    // jsdom forbids redefining window.location.assign, so stub the whole global.
    assignMock = vi.fn();
    vi.stubGlobal('location', { assign: assignMock });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it('navigates to the Hosted UI /signup URL built from env config', () => {
    vi.stubEnv('VITE_COGNITO_DOMAIN', DOMAIN);
    vi.stubEnv('VITE_COGNITO_USER_POOL_CLIENT_ID', 'abc123');
    vi.stubEnv('VITE_APP_URL', 'http://localhost:5173');

    const result = startSignUp();

    expect(result.success).toBe(true);
    expect(assignMock).toHaveBeenCalledWith(
      `https://${DOMAIN}/signup?client_id=abc123&response_type=code` +
        `&scope=openid+email+profile` +
        `&redirect_uri=${encodeURIComponent('http://localhost:5173')}`,
    );
  });

  it('returns an error and does not navigate when config is missing', () => {
    vi.stubEnv('VITE_COGNITO_DOMAIN', '');
    vi.stubEnv('VITE_COGNITO_USER_POOL_CLIENT_ID', '');
    vi.stubEnv('VITE_APP_URL', '');

    const result = startSignUp();

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toMatch(/not configured/i);
    expect(assignMock).not.toHaveBeenCalled();
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
