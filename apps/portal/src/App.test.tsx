import {describe, it, expect} from 'vitest';
import {screen} from '@testing-library/react';
import App from './App';
import {renderWithProviders} from './test/renderWithProviders';
import {authenticated, unauthenticated} from './test/authFixtures';

// Exercises the route table + RootLayout/ProtectedLayout wiring in App.tsx.
describe('App routing', () => {
  it('renders the 404 page for an unknown path', () => {
    renderWithProviders(<App />, {route: '/nope', auth: unauthenticated()});
    expect(screen.getByRole('heading', {name: 'Page not found'})).toBeInTheDocument();
  });

  it('renders a protected route through the layout for an authenticated user', () => {
    renderWithProviders(<App />, {route: '/help', auth: authenticated('alice')});
    expect(screen.getByRole('main')).toBeInTheDocument();
  });
});
