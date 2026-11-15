import {useCallback, useEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {AuthContext} from './authContext';
import {getCurrentAuthUser, startSignIn, startSignUp, startSignOut} from './auth.service';
import {setSignedInUser, setUnauthenticatedHandler} from '../../lib/apiClient';
import {reloadDocument} from '../../lib/documentNavigation';
import {armLeaveGuard, disarmLeaveGuard} from '../../lib/leaveGuard';
import {toUserText} from '../../lib/errorMessages';
import type {AuthStatus, AuthUser} from './auth.types';
import type {ServiceResult} from '../../types/service.types';

/** The parameter the server's callback adds to the landing page when a sign-in did not complete. */
const SIGNIN_PARAM = 'signin';

/** What the landing page says when it does. */
const SIGNIN_FAILED = 'Sign-in failed or was cancelled.';

/**
 * The landing page's address without the sign-in report, when it carries one.
 *
 * @returns The address to replace it with, or undefined when there is no report to show.
 */
function withoutSigninFailure(): string | undefined {
  const url = new URL(window.location.href);
  if (url.pathname !== '/' || url.searchParams.get(SIGNIN_PARAM) !== 'failed') return undefined;
  url.searchParams.delete(SIGNIN_PARAM);
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * Provides auth state (status/user/error) and the sign-in/up/out actions via AuthContext, from the
 * portal server's session.
 *
 * One session covers the browser, so this provider also decides what a tab does when the server
 * answers 401 under a page: the session is gone, or the browser's cookie now belongs to someone who
 * signed in in another tab.
 */
export function AuthProvider({children}: {children: ReactNode}) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<AuthUser | null>(null);
  // A sign-in the server's callback reported as failed shows from the first render.
  const [error, setError] = useState<string | null>(() =>
    withoutSigninFailure() === undefined ? null : SIGNIN_FAILED
  );
  // The user this tab holds, read by the 401 handler, which outlives any one render.
  const held = useRef<string | null>(null);

  /** Publish a user, or none, telling the API client FIRST so a query the change starts sees it. */
  const publish = useCallback((next: AuthUser | null) => {
    held.current = next?.username ?? null;
    setSignedInUser(held.current);
    setUser(next);
    setStatus(next ? 'authenticated' : 'unauthenticated');
  }, []);

  useEffect(() => {
    let current = true;
    // The report leaves the address with a replace, so a reload does not show it again. The history
    // entry's state is kept, because the navigation seam keys its entries there.
    const cleaned = withoutSigninFailure();
    if (cleaned !== undefined) window.history.replaceState(window.history.state, '', cleaned);
    void (async () => {
      const result = await getCurrentAuthUser();
      if (!current) return;
      if (result.success) {
        publish(result.data);
        return;
      }
      publish(null);
      if (result.error.code === 'ApiUnavailable') setError(toUserText(result.error));
    })();
    return () => {
      current = false;
    };
  }, [publish]);

  useEffect(() => {
    // One re-read at a time, however many 401s arrive while it runs.
    let rereading: Promise<void> | undefined;
    const reread = async () => {
      const result = await getCurrentAuthUser();
      if (!result.success) {
        // Signed out in local state only. No sign-out request and no logout navigation: by now the
        // cookie may belong to someone who signed in in another tab, and a logout sent on it would
        // end their session. The auth gate records this page, so the landing page's sign-in returns
        // here. A fault is not a sign-out, so it changes nothing.
        if (result.error.code === 'SessionExpired') publish(null);
        return;
      }
      if (result.data.username === held.current) return;
      // Another user signed in on this browser. Drop this page outright, so one person's page never
      // acts as another's, and so an upload's leave prompt cannot hold the stale page open.
      disarmLeaveGuard();
      reloadDocument();
    };
    setUnauthenticatedHandler(() => {
      rereading ??= reread().finally(() => {
        rereading = undefined;
      });
    });
    return () => setUnauthenticatedHandler(undefined);
  }, [publish]);

  /** Begin a sign-in or a sign-up, showing why it could not start. */
  const begin = useCallback(async (start: () => Promise<ServiceResult<void>>) => {
    setError(null);
    const result = await start();
    if (!result.success) setError(toUserText(result.error));
  }, []);

  const signIn = useCallback(() => begin(startSignIn), [begin]);
  const signUp = useCallback(() => begin(startSignUp), [begin]);

  const signOut = useCallback(async () => {
    setError(null);
    // Synchronously, before the sign-out starts: it moves the document to the provider's logout page,
    // and a deliberate sign-out asks nothing.
    disarmLeaveGuard();
    const result = await startSignOut();
    if (!result.success) {
      armLeaveGuard();
      setError(toUserText(result.error));
    }
  }, []);

  const value = useMemo(
    () => ({status, user, error, signIn, signUp, signOut}),
    [status, user, error, signIn, signUp, signOut]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
