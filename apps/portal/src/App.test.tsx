import {describe, it, expect, vi} from 'vitest';
import {screen} from '@testing-library/react';
import App from './App';
import {renderWithProviders} from './test/renderWithProviders';
import {authenticated, unauthenticated} from './test/authFixtures';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));
// The accepted rollover race: a lazy route's chunk request lands on a task built from another
// commit and the import rejects. A throwing factory is what makes the dynamic import reject.
vi.mock('./routes/QueryPage', () => {
  throw new Error('chunk load failed');
});

const APP_SOURCE = (
  import.meta.glob('./App.tsx', {query: '?raw', import: 'default', eager: true}) as Record<string, string>
)['./App.tsx'];

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
    // The skip link's target: without it, "Skip to main content" does nothing on this page.
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main');
  });

  // A lazy route with no ErrorBoundary unmounts the tree on a chunk-load rejection, and
  // `Suspense` has no error path of its own (the accepted rollover race). The
  // boundary's own behaviour is exercised through the features that render it; what can only be checked
  // here is that this route is WRAPPED in one — and inside the gate, so the page cannot
  // start fetching before the flag answer arrives.
  it('wraps /explore in FeatureRoute → ErrorBoundary → Suspense, in that order', () => {
    const block = APP_SOURCE?.match(/path="\/explore"[\s\S]*?<ExplorePage \/>/);

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

  it('lets a lazy route that failed to load give way to the next one', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const {user} = renderWithProviders(<App />, {route: '/query', auth: authenticated('alice')});
    expect(await screen.findByRole('alert')).toHaveTextContent('This part of the page didn’t load');

    await user.click(screen.getByRole('link', {name: 'Data Explorer'}));

    expect(await screen.findByRole('region', {name: 'Choose a table to explore'})).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    consoleError.mockRestore();
    consoleWarn.mockRestore();
  });

  // Sibling routes render their element into the same slot, so two route-level boundaries of the
  // same shape and the same key are ONE instance, and a chunk that failed on one route pins the
  // fallback on the next. The test above drives that for one pair of routes; this holds every
  // boundary the table declares, including the next one copied from an existing block.
  it('gives every route-level error boundary a key no other one shares', () => {
    const keys = [...(APP_SOURCE ?? '').matchAll(/<ErrorBoundary\b([^>]*)>/g)].map(
      ([, attributes]) => /\bkey="([^"]+)"/.exec(attributes)?.[1] ?? null
    );

    expect(keys.length, 'no <ErrorBoundary> was found in App.tsx').toBeGreaterThan(0);
    expect(keys).not.toContain(null);
    expect(new Set(keys).size).toBe(keys.length);
  });
});
