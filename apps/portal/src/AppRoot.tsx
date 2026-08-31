import {StrictMode} from 'react';
import {BrowserRouter} from 'react-router';
import {QueryClientProvider} from '@tanstack/react-query';
import App from './App.tsx';
import {AuthProvider} from './features/auth';
import {ToastProvider} from './components/ToastProvider';
import {queryClient} from './lib/queryClient';
import {getIdToken} from './lib/idToken';
import {setAuthTokenProvider} from './lib/apiClient';

// WHERE THE API CLIENT LEARNS ABOUT SESSIONS, and it is one call rather than an import inside
// the client because the client must not know how a session is obtained — the day the provider
// changes, nothing under `lib/` moves.
//
// Registered HERE and not in `main.tsx`: that module's static-import set is asserted by equality,
// and everything it imports is evaluated before the runtime document is fetched. This module is
// already behind the dynamic import that waits for it.
//
// The failure collapses to `null` rather than propagating: the client's contract is that no
// session means `SessionExpired` with zero network requests, and a provider that threw or
// returned a service error would leak provider wording into a layer that authors none.
setAuthTokenProvider(async (forceRefresh) => {
  const token = await getIdToken(forceRefresh);
  return token.success ? token.data : null;
});

/**
 * The whole application graph, behind one dynamic import.
 *
 * It lives here rather than in `main.tsx` because a module's static imports are
 * evaluated before its first statement runs: imported there, every module in this tree
 * would be evaluated before the runtime configuration is fetched, and any one of them
 * reading configuration at module scope would throw before the app could render its own
 * failure. `main.tsx` reaches this module only after the document is in hand.
 *
 * AuthProvider wraps the router so route guards (ProtectedLayout) can call useAuth.
 * QueryClientProvider sits inside AuthProvider and outside BrowserRouter so server-state
 * caching is available to every route but independent of navigation.
 *
 * A NAMED export: default exports are reserved for page-level route components, and this
 * is the composition above the router rather than a page.
 *
 * @returns The provider tree around the routed app.
 */
export function AppRoot() {
  return (
    <StrictMode>
      <AuthProvider>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ToastProvider>
              <App />
            </ToastProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </AuthProvider>
    </StrictMode>
  );
}
