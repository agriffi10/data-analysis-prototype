import {describe, it, expect, vi} from 'vitest';
import {screen} from '@testing-library/react';
import App from './App';
import {renderWithProviders} from './test/renderWithProviders';
import {authenticated, unauthenticated} from './test/authFixtures';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));

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

  // SPEC-179 FR-003. The path is `/explore`, it is not the 404, and the lazy chunk resolves
  // — the picker is the page's own first surface, so finding it proves the route matched and
  // the element mounted behind Suspense.
  it('renders the Data Explorer at /explore', async () => {
    renderWithProviders(<App />, {route: '/explore', auth: authenticated('alice')});

    expect(await screen.findByRole('region', {name: 'Choose a table to explore'})).toBeInTheDocument();
    expect(screen.queryByRole('heading', {name: 'Page not found'})).not.toBeInTheDocument();
  });

  // A lazy route with no ErrorBoundary unmounts the tree on a chunk-load rejection, and
  // `Suspense` has no error path of its own (deploy-app.yml's accepted deploy race). The
  // boundary's own behaviour is exercised through the features that render it; what can only be checked
  // here is that this route is WRAPPED in one — and inside the gate, so the page cannot
  // start fetching before the flag answer arrives.
  it('wraps /explore in FeatureRoute → ErrorBoundary → Suspense, in that order', () => {
    const source = (
      import.meta.glob('./App.tsx', {query: '?raw', import: 'default', eager: true}) as Record<string, string>
    )['./App.tsx'];
    const block = source?.match(/path="\/explore"[\s\S]*?<ExplorePage \/>/);

    // Guard the guard: a renamed route or a reformat that breaks this match must fail
    // loudly rather than quietly stop checking.
    expect(block, 'the /explore route block was not found in App.tsx').not.toBeNull();
    const wrappers = [...(block as RegExpMatchArray)[0].matchAll(/<(FeatureRoute|ErrorBoundary|Suspense)\b/g)].map(
      (m) => m[1]
    );
    expect(wrappers).toEqual(['FeatureRoute', 'ErrorBoundary', 'Suspense']);
    // And the gate is the RIGHT flag. Without this line, changing it to `flag="query"` left
    // the whole suite green — a flag bypass no test could see, because the walking test
    // builds its own `<FeatureRoute>` around a stub and never reads App's.
    expect(block?.[0]).toContain('<FeatureRoute flag="dataExplorer">');
  });
});
