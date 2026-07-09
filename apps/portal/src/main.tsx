import './lib/amplify'; // must be first — configures Amplify before any component renders
import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter} from 'react-router-dom';
import {QueryClientProvider} from '@tanstack/react-query';
import './index.css';
import App from './App.tsx';
import {AuthProvider} from './features/auth';
import {ToastProvider} from './components/ToastProvider';
import {queryClient} from './lib/queryClient';

// AuthProvider wraps the router so route guards (ProtectedLayout) can call
// useAuth. QueryClientProvider sits inside AuthProvider and outside
// BrowserRouter so server-state caching is available to every route but
// independent of navigation.
createRoot(document.getElementById('root')!).render(
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
