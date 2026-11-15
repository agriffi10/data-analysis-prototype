import {StrictMode, useState, type ReactNode} from 'react';
import {QueryClientProvider} from '@tanstack/react-query';
import {AppChrome} from './AppChrome';
import {AuthProvider} from './features/auth';
import {ToastProvider} from './components/ToastProvider';
import {NavigationProvider} from './lib/navigation';
import {createQueryClient} from './lib/queryClient';

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
