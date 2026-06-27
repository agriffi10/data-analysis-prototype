import {useCallback, useEffect, useMemo, useState, type ReactNode} from 'react';
import {Hub} from 'aws-amplify/utils';
import {AuthContext} from './authContext';
import {getCurrentAuthUser, startSignIn, startSignUp, startSignOut} from './auth.service';
import {isAmplifyConfigured} from '../../lib/amplify';
import {setReturnPathIfAbsent} from '../../lib/returnPath';
import type {AuthStatus, AuthUser} from './auth.types';

export function AuthProvider({children}: {children: ReactNode}) {
  // Initial state is derived from config (a module constant) rather than set in
  // an effect: when Cognito isn't configured we start unauthenticated with a
  // non-blocking error; the file browser stays usable.
  const [status, setStatus] = useState<AuthStatus>(isAmplifyConfigured ? 'loading' : 'unauthenticated');
  const [user, setUser] = useState<AuthUser | null>(null);
  const [error, setError] = useState<string | null>(
    isAmplifyConfigured ? null : 'Authentication is not configured. Set the Cognito environment variables.'
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

    const unsubscribe = Hub.listen('auth', ({payload}) => {
      switch (payload.event) {
        // `signedIn` covers SRP/programmatic sign-in. `signInWithRedirect` is the
        // event Amplify v6 emits once the Hosted-UI OAuth redirect completes and
        // the authorization code has been exchanged for tokens — without handling
        // it, the first return from Cognito never updates auth state (the mount
        // refresh runs before the exchange finishes), so the user appears signed
        // out until a second sign-in. Both re-derive the session.
        case 'signedIn':
        case 'signInWithRedirect':
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
    // Default the post-auth landing to /files without clobbering a specific
    // protected path the auth gate may have captured (returnPath, SPEC-013/029).
    setReturnPathIfAbsent('/files');
    const result = await startSignIn();
    if (!result.success) setError(result.error.message);
  }, []);

  const signUp = useCallback(async () => {
    setError(null);
    setReturnPathIfAbsent('/files');
    const result = await startSignUp();
    if (!result.success) setError(result.error.message);
  }, []);

  const signOut = useCallback(async () => {
    setError(null);
    const result = await startSignOut();
    if (!result.success) setError(result.error.message);
  }, []);

  const value = useMemo(
    () => ({status, user, error, signIn, signUp, signOut}),
    [status, user, error, signIn, signUp, signOut]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
