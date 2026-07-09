import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';
import {render, screen, waitFor, act, cleanup} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {AuthProvider} from './AuthProvider';
import {useAuth} from './useAuth';

// AuthProvider's OWN test: render the REAL provider + a real consumer and mock only
// the boundary it synchronizes with — the auth service (getCurrentAuthUser/startSign*),
// the Amplify config flag, the return-path helper, and the Amplify `Hub` event bus.
vi.mock('./auth.service', () => ({
  getCurrentAuthUser: vi.fn(),
  startSignIn: vi.fn(),
  startSignUp: vi.fn(),
  startSignOut: vi.fn()
}));
vi.mock('../../lib/amplify', () => ({isAmplifyConfigured: true}));
vi.mock('../../lib/returnPath', () => ({setReturnPathIfAbsent: vi.fn()}));
vi.mock('aws-amplify/utils', () => ({Hub: {listen: vi.fn()}}));

import {getCurrentAuthUser, startSignIn, startSignUp, startSignOut} from './auth.service';
import {Hub} from 'aws-amplify/utils';

const mockGetUser = getCurrentAuthUser as unknown as MockedFunction<() => Promise<unknown>>;
const mockStartSignIn = startSignIn as unknown as MockedFunction<() => Promise<unknown>>;
const mockStartSignUp = startSignUp as unknown as MockedFunction<() => Promise<unknown>>;
const mockStartSignOut = startSignOut as unknown as MockedFunction<() => Promise<unknown>>;
const mockHubListen = Hub.listen as unknown as MockedFunction<
  (channel: string, cb: (data: {payload: {event: string}}) => void) => () => void
>;

function TestConsumer() {
  const {status, user, error, signIn, signUp, signOut} = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="username">{user?.username ?? ''}</span>
      <span data-testid="error">{error ?? ''}</span>
      <button onClick={() => void signIn()}>signin</button>
      <button onClick={() => void signUp()}>signup</button>
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

const status = () => screen.getByTestId('status').textContent;
const username = () => screen.getByTestId('username').textContent;
const errorText = () => screen.getByTestId('error').textContent;

// Fire the captured Hub auth handler as Amplify would.
const fireHub = (event: string) =>
  act(() => {
    mockHubListen.mock.calls[0][1]({payload: {event}});
  });

const ok = <T,>(data: T) => ({success: true as const, data});
const fail = (message: string) => ({success: false as const, error: {message}});

beforeEach(() => {
  vi.resetAllMocks();
  mockHubListen.mockImplementation(() => vi.fn());
});

afterEach(() => {
  cleanup();
});

describe('AuthProvider', () => {
  it('restores an existing session: loading → authenticated with the username', async () => {
    mockGetUser.mockResolvedValue(ok({username: 'alice', email: 'alice@example.com'}));

    renderProvider();
    expect(status()).toBe('loading');

    await waitFor(() => expect(status()).toBe('authenticated'));
    expect(username()).toBe('alice');
  });

  it('lands unauthenticated (no user) when there is no session', async () => {
    mockGetUser.mockResolvedValue(fail('none'));

    renderProvider();

    await waitFor(() => expect(status()).toBe('unauthenticated'));
    expect(username()).toBe('');
  });

  it('sign-in / sign-up / sign-out each delegate to their service', async () => {
    const user = userEvent.setup();
    mockGetUser.mockResolvedValue(ok({username: 'dave'}));
    mockStartSignIn.mockResolvedValue(ok(undefined));
    mockStartSignUp.mockResolvedValue(ok(undefined));
    mockStartSignOut.mockResolvedValue(ok(undefined));

    renderProvider();
    await waitFor(() => expect(status()).toBe('authenticated'));

    await user.click(screen.getByText('signin'));
    await user.click(screen.getByText('signup'));
    await user.click(screen.getByText('signout'));

    expect(mockStartSignIn).toHaveBeenCalledOnce();
    expect(mockStartSignUp).toHaveBeenCalledOnce();
    expect(mockStartSignOut).toHaveBeenCalledOnce();
  });

  it('surfaces a failed sign-up or sign-in as a non-blocking error (never throws)', async () => {
    const user = userEvent.setup();
    mockGetUser.mockResolvedValue(fail('none'));
    mockStartSignUp.mockResolvedValue(fail('Sign-up is not configured.'));
    mockStartSignIn.mockResolvedValue(fail('popup blocked'));

    renderProvider();
    await waitFor(() => expect(status()).toBe('unauthenticated'));

    await user.click(screen.getByText('signup'));
    await waitFor(() => expect(errorText()).toBe('Sign-up is not configured.'));

    await user.click(screen.getByText('signin'));
    await waitFor(() => expect(errorText()).toBe('popup blocked'));

    // A surfaced error never tips the provider out of a usable state.
    expect(status()).toBe('unauthenticated');
  });

  it.each(['signedIn', 'signInWithRedirect'])('Hub "%s" re-derives the session to authenticated', async (event) => {
    // Mirrors the post-OAuth callback: the mount refresh runs before the code
    // exchange completes (unauthenticated), then the Hub event fires.
    mockGetUser.mockResolvedValueOnce(fail('none')).mockResolvedValueOnce(ok({username: 'bob'}));

    renderProvider();
    await waitFor(() => expect(status()).toBe('unauthenticated'));

    await fireHub(event);

    await waitFor(() => expect(status()).toBe('authenticated'));
    expect(username()).toBe('bob');
  });

  it('Hub "signedOut" clears the user and returns to unauthenticated', async () => {
    mockGetUser.mockResolvedValue(ok({username: 'carol'}));

    renderProvider();
    await waitFor(() => expect(status()).toBe('authenticated'));

    await fireHub('signedOut');

    await waitFor(() => expect(status()).toBe('unauthenticated'));
    expect(username()).toBe('');
  });

  it('Hub "signInWithRedirect_failure" surfaces a non-blocking error', async () => {
    mockGetUser.mockResolvedValue(fail('none'));

    renderProvider();
    await waitFor(() => expect(status()).toBe('unauthenticated'));

    await fireHub('signInWithRedirect_failure');

    await waitFor(() => expect(errorText()).toBe('Sign-in failed or was cancelled.'));
  });
});

describe('useAuth', () => {
  it('throws a descriptive error when used outside AuthProvider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<TestConsumer />)).toThrow('useAuth must be used within an AuthProvider');
    spy.mockRestore();
  });
});
