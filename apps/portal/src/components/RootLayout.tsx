import { Outlet, useLocation } from 'react-router-dom';
import { Header } from './Header';

// Generalized layout shared by every page: the persistent auth-aware Header
// (SPEC-007) plus the routed page content. The auth gate is a nested sub-layout
// (ProtectedLayout), so the Header renders on public and protected routes alike.
//
// The landing route ('/') is the exception (SPEC-029): the marketing page renders
// its own self-contained nav, so the app Header is suppressed there and the
// Outlet fills the full viewport.
export function RootLayout() {
  const { pathname } = useLocation();
  const isLanding = pathname === '/';

  return (
    <div className="flex min-h-screen flex-col bg-bg">
      {!isLanding && <Header />}
      <div className="flex flex-1 flex-col">
        <Outlet />
      </div>
    </div>
  );
}
