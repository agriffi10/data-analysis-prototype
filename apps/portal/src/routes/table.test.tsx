import {describe, it, expect, vi} from 'vitest';
import {screen, waitFor} from '@testing-library/react';
import {renderApp} from '../test/appRouter';
import {renderWithProviders} from '../test/renderWithProviders';
import {authenticated, unauthenticated} from '../test/authFixtures';
import {AREAS, AreaRecordsContext} from '../lib/navigation';
import {RouteTable} from './table';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));

/** Every area view module's source, keyed by its file. */
const VIEW_SOURCES = Object.fromEntries(
  Object.entries(
    import.meta.glob('./areas/*.tsx', {query: '?raw', import: 'default', eager: true}) as Record<string, string>
  ).filter(([file]) => !file.includes('.test.'))
);

/**
 * Every route-level error boundary's key across the view modules, `null` for one with none.
 *
 * @param sources - View module sources.
 * @returns The keys, in file order.
 */
function boundaryKeys(sources: Record<string, string>): (string | null)[] {
  return Object.values(sources).flatMap((source) =>
    [...source.matchAll(/<ErrorBoundary\b([^>]*)>/g)].map(
      ([, attributes]) => /\bkey="([^"]+)"/.exec(attributes)?.[1] ?? null
    )
  );
}

// Exercises the route table and the chrome around it.
describe('App routing', () => {
  it('renders the 404 page for an unknown path', async () => {
    renderApp('/nope', {auth: unauthenticated()});
    expect(await screen.findByRole('heading', {name: 'Page not found'})).toBeInTheDocument();
  });

  it('renders the landing page at /, outside the gate and without the shell', async () => {
    renderApp('/', {auth: unauthenticated()});

    expect((await screen.findAllByRole('button', {name: /sign in/i})).length).toBeGreaterThan(0);
    expect(screen.queryByRole('heading', {name: 'Page not found'})).not.toBeInTheDocument();
  });

  // Matched case-sensitively, as Next routes: react-router would have opened Files here, and once
  // Files moves to the App Router the gate would have called the path signed in while Next served
  // the not-found page inside the shell.
  it('serves /Files as the 404, outside the shell, for a signed-in user', async () => {
    renderApp('/Files', {auth: authenticated('alice')});

    expect(await screen.findByRole('heading', {name: 'Page not found'})).toBeInTheDocument();
  });

  // Outside the gate too: a gate that claimed the path would send a signed-out user to `/`.
  it('serves /Files as the 404 to a signed-out user, with no redirect', async () => {
    const {location} = renderApp('/Files', {auth: unauthenticated()});

    expect(await screen.findByRole('heading', {name: 'Page not found'})).toBeInTheDocument();
    expect(location().pathname).toBe('/Files');
  });

  // Matched decoded, as the table matches it: `/fil%65s` is Files to both, so the gate claims it and
  // a signed-out user goes to `/` rather than seeing Files outside the gate.
  it('claims a percent-encoded spelling of an area’s path for the gate, as the table serves it', async () => {
    const {location} = renderApp('/fil%65s', {auth: unauthenticated()});

    await waitFor(() => expect(location().pathname).toBe('/'));
  });

  it('builds no route for an area the App Router serves, and renders the 404 at its path', async () => {
    const records = AREAS.map((record) => (record.area === 'help' ? {...record, router: 'app' as const} : record));
    renderWithProviders(
      <AreaRecordsContext.Provider value={records}>
        <RouteTable />
      </AreaRecordsContext.Provider>,
      {route: '/help', auth: authenticated('alice')}
    );

    expect(await screen.findByRole('heading', {name: 'Page not found'})).toBeInTheDocument();
  });

  // Each route renders its own view component, so React remounts a boundary on a route change
  // whatever its key, and no render can show two boundaries sharing one. The keys matter the day two
  // routes render one view component, and this holds them distinct before that day, including a
  // block copied with its key.
  it('gives every route-level error boundary a key no other one shares', () => {
    const keys = boundaryKeys(VIEW_SOURCES);

    expect(keys.length, 'no <ErrorBoundary> was found in the area views').toBeGreaterThan(0);
    expect(keys).not.toContain(null);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('finds a boundary copied with its key into another area', () => {
    const query = VIEW_SOURCES['./areas/query.tsx'];
    const copied = {...VIEW_SOURCES, './areas/copied.tsx': query};

    const keys = boundaryKeys(copied);

    expect(new Set(keys).size).toBeLessThan(keys.length);
  });
});
