import {StrictMode, useState, type ReactNode} from 'react';
import {QueryClientProvider} from '@tanstack/react-query';
import {AppChrome} from './AppChrome';
import {AuthProvider} from './features/auth';
import {ToastProvider} from './components/ToastProvider';
import {NavigationProvider} from './lib/navigation';
import {createQueryClient} from './lib/queryClient';
import {getIdToken} from './lib/idToken';
import {setAuthTokenProvider} from './lib/apiClient';

// WHERE THE API CLIENT LEARNS ABOUT SESSIONS, and it is one call rather than an import inside
// the client because the client must not know how a session is obtained — the day the provider
// changes, nothing under `lib/` moves.
//
// Registered HERE: `PortalBoot`'s static-import set is asserted by equality, and everything it
// imports is evaluated before the runtime document is fetched. This module is already behind the
// dynamic import that waits for it.
//
// The failure collapses to `null` rather than propagating: the client's contract is that no
// session means `SessionExpired` with zero network requests, and a provider that threw or
// returned a service error would leak provider wording into a layer that authors none.
setAuthTokenProvider(async (forceRefresh) => {
  const token = await getIdToken(forceRefresh);
  return token.success ? token.data : null;
});

/**
 * The providers, around the chrome, around the page: what the boot renders once the runtime
 * document is in hand.
 *
 * Everything that reads configuration while rendering is here, behind the dynamic import the boot
 * waits on, because the root layout above it is rendered on the server too. The query client is
 * made per mount, never shared from a module. `AppChrome` is split out so the proof can render the
 * real chrome under the test harness's providers.
 *
 * A NAMED export: default exports are reserved for page-level route components.
 *
 * @param props.children - The page Next selected.
 * @returns The providers, the chrome and the page.
 */
export function AppFrame({children}: {children: ReactNode}) {
  const [queryClient] = useState(createQueryClient);
  return (
    <StrictMode>
      <AuthProvider>
        <QueryClientProvider client={queryClient}>
          <NavigationProvider>
            <ToastProvider>
              <AppChrome>{children}</AppChrome>
            </ToastProvider>
          </NavigationProvider>
        </QueryClientProvider>
      </AuthProvider>
    </StrictMode>
  );
}
