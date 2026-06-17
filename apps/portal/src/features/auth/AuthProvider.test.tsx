import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  afterEach,
  type MockedFunction,
} from 'vitest';
import { render, screen, waitFor, act, cleanup } from '@testing-library/react';
import { AuthProvider } from './AuthProvider';
import { useAuth } from './useAuth';

vi.mock('./auth.service', () => ({
  getCurrentAuthUser: vi.fn(),
  startSignIn: vi.fn(),
  startSignUp: vi.fn(),
  startSignOut: vi.fn(),
}));
vi.mock('../../lib/amplify', () => ({ isAmplifyConfigured: true }));
vi.mock('aws-amplify/utils', () => ({ Hub: { listen: vi.fn() } }));

import {
  getCurrentAuthUser,
  startSignIn,
  startSignUp,
  startSignOut,
} from './auth.service';
import { Hub } from 'aws-amplify/utils';

const mockGetUser = getCurrentAuthUser as unknown as MockedFunction<
  () => Promise<unknown>
>;
const mockStartSignIn = startSignIn as unknown as MockedFunction<
  () => Promise<unknown>
>;
const mockStartSignUp = startSignUp as unknown as MockedFunction<
  () => unknown
>;
const mockStartSignOut = startSignOut as unknown as MockedFunction<
  () => Promise<unknown>
>;
const mockHubListen = Hub.listen as unknown as MockedFunction<
  (channel: string, cb: (data: { payload: { event: string } }) => void) => () => void
>;

function TestConsumer() {
  const { status, user, error, signIn, signUp, signOut } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="username">{user?.username ?? ''}</span>
      <span data-testid="error">{error ?? ''}</span>
      <button onClick={() => void signIn()}>signin</button>
      <button onClick={() => signUp()}>signup</button>
      <button onClick={() => void signOut()}>signout</button>
    </div>
  );
}

const renderProvider = () =>
  render(
    <AuthProvider>
      <TestConsumer />
    </AuthProvider>,
  );

// Fire the captured Hub auth handler as Amplify would.
const fireHub = (event: string) =>
  act(() => {
    mockHubListen.mock.calls[0][1]({ payload: { event } });
  });

beforeEach(() => {
  vi.resetAllMocks();
  mockHubListen.mockImplementation(() => vi.fn());
});

afterEach(() => {
  cleanup();
});

describe('AuthProvider', () => {
  it('restores an existing session: loading -> authenticated with username', async () => {
    mockGetUser.mockResolvedValue({
      success: true,
      data: { username: 'alice', email: 'alice@example.com' },
    });

    renderProvider();
    expect(screen.getByTestId('status').textContent).toBe('loading');

    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('authenticated'),
    );
    expect(screen.getByTestId('username').textContent).toBe('alice');
  });

  it('lands unauthenticated when there is no session', async () => {
    mockGetUser.mockResolvedValue({ success: false, error: { message: 'none' } });

    renderProvider();

    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('unauthenticated'),
    );
    expect(screen.getByTestId('username').textContent).toBe('');
  });

  it('signIn() delegates to the sign-in service', async () => {
    mockGetUser.mockResolvedValue({ success: false, error: { message: 'none' } });
    mockStartSignIn.mockResolvedValue({ success: true, data: undefined });

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('unauthenticated'),
    );

    await act(async () => {
      screen.getByText('signin').click();
    });
    expect(mockStartSignIn).toHaveBeenCalledOnce();
  });

  it('signUp() delegates to the sign-up service', async () => {
    mockGetUser.mockResolvedValue({ success: false, error: { message: 'none' } });
    mockStartSignUp.mockReturnValue({ success: true, data: undefined });

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('unauthenticated'),
    );

    await act(async () => {
      screen.getByText('signup').click();
    });
    expect(mockStartSignUp).toHaveBeenCalledOnce();
  });

  it('surfaces an error when sign-up is not configured, without throwing', async () => {
    mockGetUser.mockResolvedValue({ success: false, error: { message: 'none' } });
    mockStartSignUp.mockReturnValue({
      success: false,
      error: { message: 'Sign-up is not configured.' },
    });

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('unauthenticated'),
    );

    await act(async () => {
      screen.getByText('signup').click();
    });
    await waitFor(() =>
      expect(screen.getByTestId('error').textContent).toBe(
        'Sign-up is not configured.',
      ),
    );
  });

  it('surfaces an error when sign-in fails, without throwing', async () => {
    mockGetUser.mockResolvedValue({ success: false, error: { message: 'none' } });
    mockStartSignIn.mockResolvedValue({
      success: false,
      error: { message: 'popup blocked' },
    });

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('unauthenticated'),
    );

    await act(async () => {
      screen.getByText('signin').click();
    });
    await waitFor(() =>
      expect(screen.getByTestId('error').textContent).toBe('popup blocked'),
    );
  });

  it('signOut() delegates to the sign-out service', async () => {
    mockGetUser.mockResolvedValue({ success: true, data: { username: 'dave' } });
    mockStartSignOut.mockResolvedValue({ success: true, data: undefined });

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('authenticated'),
    );

    await act(async () => {
      screen.getByText('signout').click();
    });
    expect(mockStartSignOut).toHaveBeenCalledOnce();
  });

  it('Hub "signedIn" re-derives the session to authenticated', async () => {
    mockGetUser
      .mockResolvedValueOnce({ success: false, error: { message: 'none' } })
      .mockResolvedValueOnce({ success: true, data: { username: 'bob' } });

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('unauthenticated'),
    );

    await fireHub('signedIn');

    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('authenticated'),
    );
    expect(screen.getByTestId('username').textContent).toBe('bob');
  });

  it('Hub "signInWithRedirect" re-derives the session to authenticated', async () => {
    // Mirrors the post-OAuth-redirect callback: the mount refresh runs before the
    // code exchange completes (unauthenticated), then the redirect event fires.
    mockGetUser
      .mockResolvedValueOnce({ success: false, error: { message: 'none' } })
      .mockResolvedValueOnce({ success: true, data: { username: 'dave' } });

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('unauthenticated'),
    );

    await fireHub('signInWithRedirect');

    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('authenticated'),
    );
    expect(screen.getByTestId('username').textContent).toBe('dave');
  });

  it('Hub "signedOut" clears the user and returns to unauthenticated', async () => {
    mockGetUser.mockResolvedValue({
      success: true,
      data: { username: 'carol' },
    });

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('authenticated'),
    );

    await fireHub('signedOut');

    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('unauthenticated'),
    );
    expect(screen.getByTestId('username').textContent).toBe('');
  });

  it('Hub "signInWithRedirect_failure" surfaces a non-blocking error', async () => {
    mockGetUser.mockResolvedValue({ success: false, error: { message: 'none' } });

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId('status').textContent).toBe('unauthenticated'),
    );

    await fireHub('signInWithRedirect_failure');

    await waitFor(() =>
      expect(screen.getByTestId('error').textContent).toBe(
        'Sign-in failed or was cancelled.',
      ),
    );
  });
});

describe('useAuth', () => {
  it('throws a descriptive error when used outside AuthProvider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<TestConsumer />)).toThrow(
      'useAuth must be used within an AuthProvider',
    );
    spy.mockRestore();
  });
});
