import {describe, it, expect, vi} from 'vitest';
import {screen} from '@testing-library/react';
import {renderApp} from '../test/appRouter';
import {renderWithProviders} from '../test/renderWithProviders';
import {authenticated, unauthenticated} from '../test/authFixtures';
import {AREAS, AreaRecordsContext} from '../lib/navigation';
import {RouteTable} from './table';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));
// The accepted rollover race: a lazy route's chunk request lands on a task built from another
// commit and the import rejects. A throwing factory is what makes the dynamic import reject. It is
// file-wide, which is why this scenario lives here and not in the Query area's own file.
vi.mock('./QueryPage', () => {
  throw new Error('chunk load failed');
});

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

  it('lets a lazy route that failed to load give way to the next one', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const {user} = renderApp('/query', {auth: authenticated('alice')});
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
  // boundary the area views declare, including the next one copied from an existing block.
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
