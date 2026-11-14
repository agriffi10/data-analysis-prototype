import {act, screen, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {renderApp, type RenderAppOptions} from '../../test/appRouter';
import {authenticated} from '../../test/authFixtures';
import {external, hold, nextPopstate, requests, traverse} from '../../test/nextNavigation';
import {
  commits,
  commitsOf,
  fixture,
  lastCommit,
  mounts,
  readoutPage,
  resetReadout,
  type FixtureLink
} from '../../test/seamReadout';
import {matchPath} from './matchPath';
import type {AreaName, AreaRouter} from './areas';

/**
 * The navigation seam, proved through the test App Router: the real chrome, the real route table,
 * and Next's behaviours modelled by the stand-in. Every page here is a readout that records what the
 * seam told it on each commit, so a scenario reads the same whichever router serves the page.
 */

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));
vi.mock('../../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));
vi.mock('../../routes/FilesPage', async () => ({
  default: (await import('../../test/seamReadout')).readoutPage('files')
}));
vi.mock('../../routes/NotificationsPage', async () => ({
  default: (await import('../../test/seamReadout')).readoutPage('notifications')
}));
vi.mock('../../routes/HelpPage', async () => ({default: (await import('../../test/seamReadout')).readoutPage('help')}));
vi.mock('../../routes/DataQualityPage', async () => ({
  default: (await import('../../test/seamReadout')).readoutPage('data-quality')
}));
vi.mock('../../routes/DataQualityReportPage', async () => ({
  default: (await import('../../test/seamReadout')).readoutPage('report')
}));

const READOUT_AREAS = ['files', 'notifications', 'help', 'data-quality'] as const;

/** Each readout area on one router, its App Router pages supplied when that router is the App Router's. */
function servedBy(router: AreaRouter, areas: readonly AreaName[] = READOUT_AREAS): RenderAppOptions {
  const routers: Partial<Record<AreaName, AreaRouter>> = {};
  const pages: NonNullable<RenderAppOptions['pages']> = {};
  for (const area of areas) {
    routers[area] = router;
    pages[`(signed-in)/${area}/page.tsx`] = readoutPage(area);
  }
  pages['(signed-in)/data-quality/[space]/[requestId]/page.tsx'] = readoutPage('report');
  return {auth: authenticated('alice'), routers, pages};
}

/** Two option sets merged, their routers and pages together. */
function both(a: RenderAppOptions, b: RenderAppOptions): RenderAppOptions {
  return {...a, ...b, routers: {...a.routers, ...b.routers}, pages: {...a.pages, ...b.pages}};
}

const ROUTERS: AreaRouter[] = ['catch-all', 'app'];

/** Follow a readout link by its label, and wait for the page it names to commit there. */
async function follow(user: ReturnType<typeof renderApp>['user'], label: string) {
  await user.click(screen.getByRole('link', {name: label}));
}

/** Click the page's in-page anchor, a real one, and wait for the browser's popstate. */
async function followAnchor(user: ReturnType<typeof renderApp>['user']) {
  await act(async () => {
    const moved = nextPopstate();
    await user.click(screen.getByRole('link', {name: 'In-page anchor'}));
    await moved;
  });
}

const LINKS: FixtureLink[] = [
  {label: 'To files', to: '/files'},
  {label: 'To notifications', to: '/notifications'},
  {label: 'To help', to: '/help'},
  {label: 'Replace with help', to: '/help', replace: true},
  {label: 'To help at files', to: '/help#files'},
  {label: 'To the files section', to: '#files'},
  {label: 'To data quality', to: '/data-quality'}
];

beforeEach(() => resetReadout(LINKS));
afterEach(() => vi.restoreAllMocks());

describe('the seam’s location, type and key', () => {
  it.each(ROUTERS)(
    'pushes, replaces, and makes a link to the address shown a replace with a new key (%s)',
    async (router) => {
      const {user} = renderApp('/files', servedBy(router));
      await screen.findByRole('heading', {name: 'page files'});

      await follow(user, 'To notifications');
      await screen.findByRole('heading', {name: 'page notifications'});
      const pushed = lastCommit();
      await follow(user, 'Replace with help');
      await screen.findByRole('heading', {name: 'page help'});
      const replaced = lastCommit();
      await follow(user, 'To help');
      await waitFor(() => expect(lastCommit().key).not.toBe(replaced.key));
      const again = lastCommit();

      expect(pushed).toMatchObject({page: 'notifications', pathname: '/notifications', type: 'PUSH'});
      expect(replaced).toMatchObject({page: 'help', pathname: '/help', type: 'REPLACE'});
      expect(again).toMatchObject({page: 'help', pathname: '/help', type: 'REPLACE'});
      expect(new Set([pushed.key, replaced.key, again.key]).size).toBe(3);
    }
  );

  it.each(ROUTERS)('pushes a hash-only target on the same page, dropping the query (%s)', async (router) => {
    const {user} = renderApp('/help?topic=x', servedBy(router));
    await screen.findByRole('heading', {name: 'page help'});

    await follow(user, 'To the files section');

    await waitFor(() =>
      expect(lastCommit()).toMatchObject({page: 'help', pathname: '/help', search: '', hash: '#files', type: 'PUSH'})
    );
  });

  it.each(ROUTERS)('reads Back to a pushed entry as a POP with that entry’s own key (%s)', async (router) => {
    const {user} = renderApp('/files', servedBy(router));
    await screen.findByRole('heading', {name: 'page files'});
    await follow(user, 'To notifications');
    await screen.findByRole('heading', {name: 'page notifications'});
    const entry = lastCommit();
    await follow(user, 'To help');
    await screen.findByRole('heading', {name: 'page help'});

    await traverse(-1);

    expect(lastCommit()).toMatchObject({page: 'notifications', type: 'POP', key: entry.key});
  });

  it.each(ROUTERS)('reads an in-page anchor as a POP with the default key (%s)', async (router) => {
    const {user} = renderApp('/files', servedBy(router));
    await screen.findByRole('heading', {name: 'page files'});
    await follow(user, 'To notifications');
    await screen.findByRole('heading', {name: 'page notifications'});

    await followAnchor(user);

    expect(lastCommit()).toMatchObject({page: 'notifications', hash: '#section', type: 'POP', key: 'default'});
  });

  // Next drops a navigation still in flight when a traversal arrives. Taken as the navigation that
  // rendered, the dropped push would call the Back a push, with its key and its state.
  it('reads Back over a router push Next dropped as a POP, with the entry’s own key and no state', async () => {
    resetReadout([...LINKS, {label: 'To data quality with state', to: '/data-quality', state: {dropped: true}}]);
    const options = both(servedBy('app', ['data-quality']), servedBy('catch-all', ['files']));
    const {user} = renderApp('/data-quality', options);
    await screen.findByRole('heading', {name: 'page data-quality'});
    const first = lastCommit();
    await follow(user, 'To files');
    await screen.findByRole('heading', {name: 'page files'});

    hold();
    await follow(user, 'To data quality with state');
    commits.length = 0;
    await traverse(-1);

    await screen.findByRole('heading', {name: 'page data-quality'});
    expect(commits.map((commit) => commit.type)).toEqual(commits.map(() => 'POP'));
    expect(lastCommit()).toMatchObject({page: 'data-quality', key: first.key, state: undefined});
  });

  // React renders a traversal inside Next's popstate dispatch, before any listener the app adds,
  // so a seam that classified by its own listener would report a Back as a push for one commit.
  it.each(ROUTERS)('reports no type but POP on any commit during a traversal (%s)', async (router) => {
    const {user} = renderApp('/files', servedBy(router));
    await screen.findByRole('heading', {name: 'page files'});
    await follow(user, 'To notifications');
    await screen.findByRole('heading', {name: 'page notifications'});
    await follow(user, 'To help');
    await screen.findByRole('heading', {name: 'page help'});
    commits.length = 0;

    await traverse(-1);

    expect(commits.length).toBeGreaterThan(0);
    expect(commits.map((commit) => commit.type)).toEqual(commits.map(() => 'POP'));
  });
});

describe('which router performs a navigation', () => {
  it.each([
    ['catch-all', 'catch-all'],
    ['catch-all', 'app'],
    ['app', 'catch-all'],
    ['app', 'app']
  ] as const)('renders /help#files with its hash on the destination’s first render (%s to %s)', async (from, to) => {
    const options = both(servedBy(from, ['files']), servedBy(to, ['help']));
    const {user} = renderApp('/files', options);
    await screen.findByRole('heading', {name: 'page files'});

    await follow(user, 'To help at files');

    await screen.findByRole('heading', {name: 'page help'});
    expect(commitsOf('help')[0]).toMatchObject({pathname: '/help', hash: '#files'});
  });

  it('moves between two catch-all pages without Next’s router, and the catch-all page stays mounted', async () => {
    const {user} = renderApp('/files', servedBy('catch-all'));
    await screen.findByRole('heading', {name: 'page files'});

    await follow(user, 'To notifications');

    await screen.findByRole('heading', {name: 'page notifications'});
    expect(requests()).toEqual([]);
  });

  it('changes only the query or the hash on an App Router page without Next’s router, and without a remount', async () => {
    resetReadout([...LINKS, {label: 'Same page, another query', to: '/help?topic=y'}]);
    const {user} = renderApp('/help', servedBy('app'));
    await screen.findByRole('heading', {name: 'page help'});

    await follow(user, 'Same page, another query');
    await waitFor(() => expect(lastCommit().search).toBe('?topic=y'));
    await follow(user, 'To the files section');
    await waitFor(() => expect(lastCommit().hash).toBe('#files'));

    expect(requests()).toEqual([]);
    expect(mounts).toEqual(['help']);
  });

  it('goes through Next’s router to a page the App Router serves at another path', async () => {
    const {user} = renderApp('/files', servedBy('app'));
    await screen.findByRole('heading', {name: 'page files'});

    await follow(user, 'To notifications');

    await screen.findByRole('heading', {name: 'page notifications'});
    expect(requests()).toEqual(['/notifications']);
  });

  // The source is the committed address, never the seam's own idea of where it is going: from an App
  // Router page with a push to a catch-all page still in flight, a second click to another catch-all
  // page must go through Next's router too, or Next shows the App Router page under the new address.
  it('decides by the committed address while a router push is still in flight', async () => {
    const {user} = renderApp(
      '/files',
      both(servedBy('app', ['files']), servedBy('catch-all', ['notifications', 'help']))
    );
    await screen.findByRole('heading', {name: 'page files'});

    hold();
    await follow(user, 'To notifications');
    await follow(user, 'To help');

    await screen.findByRole('heading', {name: 'page help'});
    expect(lastCommit()).toMatchObject({page: 'help', pathname: '/help'});
    expect(screen.queryByRole('heading', {name: 'page files'})).not.toBeInTheDocument();
  });

  // react-router inside the catch-all is fed by the seam. A `BrowserRouter` there reads
  // `window.location` as it mounts, and Next renders a page before it writes the address.
  it('renders the matching catch-all page on its first render after an App Router page', async () => {
    const options = both(servedBy('app', ['files']), servedBy('catch-all', ['notifications', 'help']));
    const {user} = renderApp('/notifications', options);
    await screen.findByRole('heading', {name: 'page notifications'});
    await follow(user, 'To files');
    await screen.findByRole('heading', {name: 'page files'});

    await follow(user, 'To help');

    await screen.findByRole('heading', {name: 'page help'});
    expect(commitsOf('help')[0]).toMatchObject({pathname: '/help', type: 'PUSH'});
    expect(screen.queryByRole('heading', {name: 'Page not found'})).not.toBeInTheDocument();
  });
});

describe('an in-page anchor’s entry', () => {
  // A native anchor makes an entry with no state, and Next ignores a popstate whose state is null,
  // so without the seam stamping it Back would leave the page it came from on screen.
  it.each(ROUTERS)('is one a later Back restores, as a POP with the default key (%s)', async (router) => {
    const {user} = renderApp('/files', servedBy(router));
    await screen.findByRole('heading', {name: 'page files'});
    await followAnchor(user);
    await follow(user, 'To notifications');
    await screen.findByRole('heading', {name: 'page notifications'});

    await traverse(-1);

    expect(await screen.findByRole('heading', {name: 'page files'})).toBeInTheDocument();
    expect(lastCommit()).toMatchObject({page: 'files', hash: '#section', type: 'POP', key: 'default'});
  });
});

describe('the state a navigation carries', () => {
  // Next re-serializes the search, so the seam compares two addresses only once both are parsed:
  // compared raw, the state would never arrive and Back would be called a push.
  it.each(ROUTERS)(
    'arrives on a link whose query holds an encoded space, and Back reads that entry’s key (%s)',
    async (router) => {
      resetReadout([...LINKS, {label: 'To My Reports', to: '/files?prefix=My%20Reports%2F', state: {from: 'query'}}]);
      const {user} = renderApp('/notifications', servedBy(router));
      await screen.findByRole('heading', {name: 'page notifications'});

      await follow(user, 'To My Reports');
      await screen.findByRole('heading', {name: 'page files'});
      const arrived = lastCommit();
      await follow(user, 'To help');
      await screen.findByRole('heading', {name: 'page help'});
      await traverse(-1);

      expect(arrived).toMatchObject({search: '?prefix=My%20Reports%2F', state: {from: 'query'}, type: 'PUSH'});
      expect(lastCommit()).toMatchObject({page: 'files', type: 'POP', key: arrived.key});
    }
  );

  it.each(ROUTERS)('reaches the first render, and is gone after Back, Forward and a reload (%s)', async (router) => {
    resetReadout([...LINKS, {label: 'To files with state', to: '/files', state: {handOff: 1}}]);
    const view = renderApp('/notifications', servedBy(router));
    await screen.findByRole('heading', {name: 'page notifications'});

    await follow(view.user, 'To files with state');
    await screen.findByRole('heading', {name: 'page files'});
    expect(commitsOf('files')[0].state).toEqual({handOff: 1});
    await follow(view.user, 'To help');
    await screen.findByRole('heading', {name: 'page help'});
    await traverse(-1);
    expect(lastCommit()).toMatchObject({page: 'files', state: undefined});
    await traverse(1);
    await traverse(-1);
    expect(lastCommit()).toMatchObject({page: 'files', state: undefined});

    view.unmount();
    resetReadout(LINKS);
    renderApp(window.location.pathname, servedBy(router));
    await screen.findByRole('heading', {name: 'page files'});
    expect(lastCommit().state).toBeUndefined();
  });
});

describe('targets outside the portal', () => {
  const OFF_SITE = [
    '//evil.example/x',
    '/\\evil.example/x',
    '\\\\evil.example/x',
    ' //evil.example/x',
    '/\t/evil.example/x',
    'https:evil.example/x',
    'https://evil.example/',
    'javascript:alert(1)',
    'data:text/html,x'
  ];

  it.each(OFF_SITE)('refuses %j through navigate: no navigation, the address kept, one log line', async (target) => {
    renderApp('/files', servedBy('app'));
    await screen.findByRole('heading', {name: 'page files'});
    const pushState = vi.spyOn(window.history, 'pushState');
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

    act(() => fixture.navigate?.(target));

    expect(pushState).not.toHaveBeenCalled();
    expect(requests()).toEqual([]);
    expect(window.location.pathname).toBe('/files');
    expect(warn).toHaveBeenCalledOnce();
  });

  it.each(OFF_SITE)('renders %j through Link as an anchor with no href', async (target) => {
    resetReadout([{label: 'Off site', to: target}]);
    renderApp('/files', servedBy('catch-all'));
    await screen.findByRole('heading', {name: 'page files'});

    expect(screen.getByText('Off site')).not.toHaveAttribute('href');
  });

  // A dot segment before a doubled slash is a path as written and protocol-relative once the URL
  // parser resolves it. Resolved as react-router resolves it, the slashes collapse and it stays here.
  it.each(['/.//evil.example/x', '/a/..//evil.example/x', '/%2e//evil.example/x'])(
    'keeps %j in the portal, resolving it as react-router does',
    async (target) => {
      resetReadout([{label: 'Dotted', to: target}]);
      renderApp('/files', servedBy('app'));
      await screen.findByRole('heading', {name: 'page files'});

      expect(screen.getByText('Dotted')).toHaveAttribute('href', '/evil.example/x');
      act(() => fixture.navigate?.(target));

      await waitFor(() => expect(window.location.pathname).toBe('/evil.example/x'));
      expect(window.location.origin).toBe('http://localhost:3000');
      expect(external()).toEqual([]);
    }
  );

  it('still navigates to the portal’s own paths', async () => {
    const {user} = renderApp('/files', servedBy('catch-all'));
    await screen.findByRole('heading', {name: 'page files'});
    expect(screen.getByRole('link', {name: 'To help at files'})).toHaveAttribute('href', '/help#files');

    act(() => fixture.navigate?.('/notifications'));
    await screen.findByRole('heading', {name: 'page notifications'});
    await follow(user, 'To help at files');

    expect(await screen.findByRole('heading', {name: 'page help'})).toBeInTheDocument();
  });
});

describe('route params', () => {
  it.each(ROUTERS)('decodes a percent-encoded segment (%s)', async (router) => {
    renderApp('/data-quality/a%40b%20c/r1', servedBy(router));

    await screen.findByRole('heading', {name: 'page report'});
    expect(lastCommit().params).toMatchObject({space: 'a@b c', requestId: 'r1'});
  });

  it('matches case-sensitively, as Next routes', () => {
    expect(matchPath('/files', '/Files')).toBeNull();
    expect(matchPath('/files', '/files')).toEqual({params: {}});
  });
});

describe('the routers the app renders', () => {
  // The catch-all's react-router is a `<Router>` the seam feeds; no other may own a history.
  it('renders no BrowserRouter, MemoryRouter or HashRouter anywhere under src/', () => {
    const owners = ['Browser', 'Memory', 'Hash'].map((kind) => `${kind}Router`);
    const sources = import.meta.glob('/src/**/*.{ts,tsx}', {query: '?raw', import: 'default', eager: true}) as Record<
      string,
      string
    >;

    const found = Object.entries(sources).flatMap(([file, source]) =>
      owners
        .filter((owner) => new RegExp(`<${owner}\\b|createElement\\(${owner}\\b|\\b${owner}\\s*[,}]`).test(source))
        .map((owner) => `${file}: ${owner}`)
    );

    expect(Object.keys(sources).length).toBeGreaterThan(100);
    expect(found).toEqual([]);
  });
});
