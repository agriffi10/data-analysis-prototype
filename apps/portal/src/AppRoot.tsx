import {StrictMode} from 'react';
import {BrowserRouter} from 'react-router';
import {QueryClientProvider} from '@tanstack/react-query';
import App from './App.tsx';
import {AuthProvider} from './features/auth';
import {ToastProvider} from './components/ToastProvider';
import {queryClient} from './lib/queryClient';

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
