import { Outlet } from 'react-router-dom';
import { Header } from './Header';

// Generalized layout shared by every page: the persistent auth-aware Header
// (SPEC-007) plus the routed page content. The auth gate is a nested sub-layout
// (ProtectedLayout), so the Header renders on public and protected routes alike.
export function RootLayout() {
  return (
    <div className="flex min-h-screen flex-col bg-bg">
      <Header />
      <div className="flex flex-1 flex-col">
        <Outlet />
      </div>
    </div>
  );
}
