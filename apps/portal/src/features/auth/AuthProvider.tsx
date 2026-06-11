import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { Hub } from 'aws-amplify/utils';
import { AuthContext } from './authContext';
import { getCurrentAuthUser, startSignIn, startSignOut } from './auth.service';
import { isAmplifyConfigured } from '../../lib/amplify';
import type { AuthStatus, AuthUser } from './auth.types';

export function AuthProvider({ children }: { children: ReactNode }) {
  // Initial state is derived from config (a module constant) rather than set in
  // an effect: when Cognito isn't configured we start unauthenticated with a
  // non-blocking error; the file browser stays usable.
  const [status, setStatus] = useState<AuthStatus>(
    isAmplifyConfigured ? 'loading' : 'unauthenticated',
  );
  const [user, setUser] = useState<AuthUser | null>(null);
  const [error, setError] = useState<string | null>(
    isAmplifyConfigured
      ? null
      : 'Authentication is not configured. Set the Cognito environment variables.',
  );

  // Derive auth state from the current Amplify session.
  const refresh = useCallback(async () => {
    const result = await getCurrentAuthUser();
    if (result.success) {
      setUser(result.data);
      setStatus('authenticated');
    } else {
      setUser(null);
      setStatus('unauthenticated');
    }
  }, []);

  useEffect(() => {
    // Initial not-configured state is set above; nothing to subscribe to.
    if (!isAmplifyConfigured) return;

    // Restore session on load (also handles the post-redirect callback once
    // Amplify has exchanged the auth code and emitted `signedIn`). Wrapped in an
    // async IIFE: state updates happen after the await, not synchronously.
    void (async () => {
      await refresh();
    })();

    const unsubscribe = Hub.listen('auth', ({ payload }) => {
      switch (payload.event) {
        case 'signedIn':
          setError(null);
          void refresh();
          break;
        case 'signedOut':
          setUser(null);
          setStatus('unauthenticated');
          break;
        case 'signInWithRedirect_failure':
          setUser(null);
          setStatus('unauthenticated');
          setError('Sign-in failed or was cancelled.');
          break;
      }
    });

    return unsubscribe;
  }, [refresh]);

  const signIn = useCallback(async () => {
    setError(null);
    const result = await startSignIn();
    if (!result.success) setError(result.error.message);
  }, []);

  const signOut = useCallback(async () => {
    setError(null);
    const result = await startSignOut();
    if (!result.success) setError(result.error.message);
  }, []);

  const value = useMemo(
    () => ({ status, user, error, signIn, signOut }),
    [status, user, error, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
