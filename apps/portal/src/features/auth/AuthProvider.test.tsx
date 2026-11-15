import {afterEach, beforeEach, describe, expect, it, vi, type MockedFunction} from 'vitest';
import {act, cleanup, render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {AuthProvider} from './AuthProvider';
import {useAuth} from './useAuth';
import {apiRequest, resetApiClientForTests} from '../../lib/apiClient';

// AuthProvider's OWN test: the real provider, a real consumer and the real API client, with the
// boundaries it talks to mocked: the auth service, the document's navigation and the network. The
// leave guard is the real module, recorded, so an assertion can read the order of what happened.
const calls = vi.hoisted(() => [] as string[]);
vi.mock('./auth.service', () => ({
  getCurrentAuthUser: vi.fn(),
  startSignIn: vi.fn(),
  startSignUp: vi.fn(),
  startSignOut: vi.fn()
}));
vi.mock('../../lib/documentNavigation', () => ({
  assignDocument: (url: string) => calls.push(`assign ${url}`),
  reloadDocument: () => calls.push('reload')
}));
vi.mock('../../lib/leaveGuard', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../lib/leaveGuard')>();
  return {
    ...original,
    disarmLeaveGuard: () => (calls.push('disarm'), original.disarmLeaveGuard()),
    armLeaveGuard: () => (calls.push('arm'), original.armLeaveGuard())
  };
});

import {getCurrentAuthUser, startSignIn, startSignOut} from './auth.service';

const mockGetUser = getCurrentAuthUser as unknown as MockedFunction<() => Promise<unknown>>;
const mockStartSignIn = startSignIn as unknown as MockedFunction<() => Promise<unknown>>;
const mockStartSignOut = startSignOut as unknown as MockedFunction<() => Promise<unknown>>;

function TestConsumer() {
  const {status, user, error, signIn, signOut} = useAuth();
  return (
    <div>
      <output aria-label="status">{status}</output>
      <output aria-label="username">{user?.username ?? ''}</output>
      <output aria-label="error">{error ?? ''}</output>
      <button onClick={() => void signIn()}>signin</button>
      <button onClick={() => void signOut()}>signout</button>
    </div>
  );
}

const renderProvider = () =>
  render(
    <AuthProvider>
      <TestConsumer />
    </AuthProvider>
  );

const status = () => screen.getByRole('status', {name: 'status'}).textContent;
const username = () => screen.getByRole('status', {name: 'username'}).textContent;
const errorText = () => screen.getByRole('status', {name: 'error'}).textContent;

const ok = <T,>(data: T) => ({success: true as const, data});
const fail = (code: string) => ({success: false as const, error: {message: '', code}});

/** The network: every API call answers 401, as the server does once the session is gone. */
function apiAnswers401() {
  const fetch = vi.fn(async () => new Response(JSON.stringify({error: {code: 'SessionExpired'}}), {status: 401}));
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

/** Signed in as alice, then the next session read answers what the test gives. */
async function signedInAsAlice(...thenRead: unknown[]) {
  mockGetUser.mockResolvedValueOnce(ok({username: 'alice'}));
  for (const answer of thenRead) mockGetUser.mockResolvedValueOnce(answer);
  renderProvider();
  await waitFor(() => expect(status()).toBe('authenticated'));
}

beforeEach(() => {
  vi.resetAllMocks();
  calls.length = 0;
  resetApiClientForTests();
  window.history.replaceState(null, '', '/');
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('the session, on mount', () => {
  it('restores a signed-in user, and lands signed out showing nothing when there is no session', async () => {
    await signedInAsAlice();
    expect(username()).toBe('alice');
    cleanup();

    mockGetUser.mockResolvedValueOnce(fail('SessionExpired'));
    renderProvider();
    await waitFor(() => expect(status()).toBe('unauthenticated'));
    expect(errorText()).toBe('');
  });

  it('lands signed out and says the server could not answer when the session read fails', async () => {
    mockGetUser.mockResolvedValueOnce(fail('ApiUnavailable'));

    renderProvider();

    await waitFor(() => expect(status()).toBe('unauthenticated'));
    expect(errorText()).toMatch(/^The server couldn’t complete that request/);
  });

  it('shows a failed sign-in the callback reported, and takes the report out of the address', async () => {
    window.history.replaceState({key: 'seam'}, '', '/?signin=failed&other=1#top');
    mockGetUser.mockResolvedValueOnce(fail('SessionExpired'));

    renderProvider();

    await waitFor(() => expect(errorText()).toBe('Sign-in failed or was cancelled.'));
    expect(`${window.location.pathname}${window.location.search}${window.location.hash}`).toBe('/?other=1#top');
    expect(window.history.state).toEqual({key: 'seam'});
  });
});

describe('a 401 under a page', () => {
  it('signs the tab out locally when the session is gone, sending no sign-out and nothing after', async () => {
    await signedInAsAlice(fail('SessionExpired'));
    const fetch = apiAnswers401();

    await act(async () => void (await apiRequest('featureFlags.get')));

    await waitFor(() => expect(status()).toBe('unauthenticated'));
    expect(mockStartSignOut).not.toHaveBeenCalled();
    expect(calls).toEqual([]);
    expect(await apiRequest('featureFlags.get')).toEqual(fail('SessionExpired'));
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('drops the page, disarming the leave guard first, when another user now holds the session', async () => {
    await signedInAsAlice(ok({username: 'bob'}));
    apiAnswers401();

    await act(async () => void (await apiRequest('featureFlags.get')));

    await waitFor(() => expect(calls).toEqual(['disarm', 'reload']));
  });

  it('stays signed in, and moves nowhere, when the re-read itself cannot be answered', async () => {
    await signedInAsAlice(fail('ApiUnavailable'));
    apiAnswers401();

    await act(async () => void (await apiRequest('featureFlags.get')));

    await waitFor(() => expect(mockGetUser).toHaveBeenCalledTimes(2));
    expect(status()).toBe('authenticated');
    expect(calls).toEqual([]);
  });

  it('stays signed in when the session still names this user, and reads it once for three 401s', async () => {
    await signedInAsAlice(ok({username: 'alice'}));
    apiAnswers401();

    await act(async () => {
      await Promise.all([1, 2, 3].map(() => apiRequest('featureFlags.get')));
    });

    await waitFor(() => expect(mockGetUser).toHaveBeenCalledTimes(2));
    expect(status()).toBe('authenticated');
    expect(calls).toEqual([]);
  });
});

describe('the actions', () => {
  it('disarms the leave guard before the sign-out starts, and on a failure re-arms it and stays signed in', async () => {
    const user = userEvent.setup();
    await signedInAsAlice();
    mockStartSignOut.mockImplementationOnce(async () => (calls.push('sign-out starts'), fail('ApiUnavailable')));

    await user.click(screen.getByRole('button', {name: 'signout'}));

    await waitFor(() => expect(calls).toEqual(['disarm', 'sign-out starts', 'arm']));
    expect(status()).toBe('authenticated');
    expect(errorText()).toMatch(/^The server couldn’t complete that request/);
  });

  it('shows why a sign-in could not start', async () => {
    const user = userEvent.setup();
    mockGetUser.mockResolvedValueOnce(fail('SessionExpired'));
    mockStartSignIn.mockResolvedValueOnce(fail('ApiUnavailable'));
    renderProvider();
    await waitFor(() => expect(status()).toBe('unauthenticated'));

    await user.click(screen.getByRole('button', {name: 'signin'}));

    await waitFor(() => expect(errorText()).toMatch(/^The server couldn’t complete that request/));
  });
});

describe('useAuth', () => {
  it('throws a descriptive error when used outside AuthProvider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<TestConsumer />)).toThrow('useAuth must be used within an AuthProvider');
    spy.mockRestore();
  });
});
