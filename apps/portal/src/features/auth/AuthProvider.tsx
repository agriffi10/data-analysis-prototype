import {useCallback, useEffect, useMemo, useState, type ReactNode} from 'react';
import {Hub} from 'aws-amplify/utils';
import {AuthContext} from './authContext';
import {ALREADY_AUTHENTICATED, getCurrentAuthUser, startSignIn, startSignUp, startSignOut} from './auth.service';
import {isAmplifyConfigured} from '../../lib/amplify';
import {toUserText} from '../../lib/errorMessages';
import {setReturnPathIfAbsent} from '../../lib/returnPath';
import type {AuthStatus, AuthUser} from './auth.types';

/**
 * Provides auth state (status/user/error) and the sign-in/up/out actions via
 * AuthContext, deriving state from the Amplify session and Hub auth events.
 */
export function AuthProvider({children}: {children: ReactNode}) {
  // Read ONCE per mount, not per render: the answer cannot change while the app is
  // running (the runtime document resolves before the first render), and the two
  // useState initialisers plus the effect below must agree on one value.
  const [configured] = useState(() => isAmplifyConfigured());
  // Initial state is derived from config rather than set in an effect: when Cognito
  // isn't configured we start unauthenticated with a non-blocking error; the file
  // browser stays usable.
  const [status, setStatus] = useState<AuthStatus>(configured ? 'loading' : 'unauthenticated');
  const [user, setUser] = useState<AuthUser | null>(null);
  const [error, setError] = useState<string | null>(configured ? null : toUserText({code: 'RuntimeConfigUnavailable'}));

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
    if (!configured) return;

    // Restore session on load (also handles the post-redirect callback once
    // Amplify has exchanged the auth code and emitted `signedIn`). Wrapped in an
    // async IIFE: state updates happen after the await, not synchronously.
    void (async () => {
      await refresh();
    })();

    const unsubscribe = Hub.listen('auth', ({payload}) => {
      switch (payload.event) {
        // `signedIn` covers SRP/programmatic sign-in. `signInWithRedirect` fires
        // once Amplify v6 finishes the Hosted-UI OAuth code exchange — the mount
        // refresh runs before the exchange completes, so without handling it the
        // user appears signed out until a second sign-in.
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
  }, [configured, refresh]);

  // A Sign-in control is only rendered while we believe the user is signed out, but
  // that belief can disagree with Amplify — a transient `getCurrentUser()` failure
  // leaves `status` unauthenticated over a live session. Amplify then refuses to
  // redirect and throws `UserAlreadyAuthenticatedException`, so the click produced a
  // swallowed error and no visible effect: setting an error would put a failure banner
  // over what is really a live session. Treat it as what it is —
  // already signed in — and re-derive state, which flips the UI to its authenticated
  // form and lets the pending return path route the user on.
  const recoverIfAlreadySignedIn = useCallback(
    async (result: Awaited<ReturnType<typeof startSignIn>>) => {
      if (result.success) return;
      if (result.error.code === ALREADY_AUTHENTICATED) {
        await refresh();
        return;
      }
      // Map to friendly text here (the code is in scope) so the Header banner
      // never shows the raw Cognito message.
      setError(toUserText(result.error));
    },
    [refresh]
  );

  const signIn = useCallback(async () => {
    setError(null);
    // Default the post-auth landing to /files without clobbering a specific
    // protected path the auth gate may have captured.
    setReturnPathIfAbsent('/files');
    await recoverIfAlreadySignedIn(await startSignIn());
  }, [recoverIfAlreadySignedIn]);

  const signUp = useCallback(async () => {
    setError(null);
    setReturnPathIfAbsent('/files');
    await recoverIfAlreadySignedIn(await startSignUp());
  }, [recoverIfAlreadySignedIn]);

  const signOut = useCallback(async () => {
    setError(null);
    const result = await startSignOut();
    if (!result.success) setError(toUserText(result.error));
  }, []);

  const value = useMemo(
    () => ({status, user, error, signIn, signUp, signOut}),
    [status, user, error, signIn, signUp, signOut]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
