import {useLayoutEffect} from 'react';
import {act, screen, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {renderApp, type RenderAppOptions} from '../../test/appRouter';
import {authenticated} from '../../test/authFixtures';
import {
  documentLoads,
  external,
  hold,
  nextPopstate,
  release,
  requests,
  standInRouter,
  traverse
} from '../../test/nextNavigation';
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
import {useNavigate, useSearchParams} from './hooks';
import {matchPath} from './matchPath';

/**
 * The navigation seam, proved through the test App Router: the real chrome, a readout page per
 * area, and Next's behaviours modelled by the stand-in. Every page records what the seam told it on
 * each commit.
 */

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

/** Each readout area served by its readout page, signed in. */
const SERVED: RenderAppOptions = {
  auth: authenticated('alice'),
  pages: {
    ...Object.fromEntries(READOUT_AREAS.map((area) => [`(signed-in)/${area}/page.tsx`, readoutPage(area)])),
    '(signed-in)/data-quality/[space]/[requestId]/page.tsx': readoutPage('report')
  }
};

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
  it('pushes, replaces, and makes a link to the address shown a replace with a new key', async () => {
    const {user} = renderApp('/files', SERVED);
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
  });

  it('pushes a hash-only target on the same page, dropping the query', async () => {
    const {user} = renderApp('/help?topic=x', SERVED);
    await screen.findByRole('heading', {name: 'page help'});

    await follow(user, 'To the files section');

    await waitFor(() =>
      expect(lastCommit()).toMatchObject({page: 'help', pathname: '/help', search: '', hash: '#files', type: 'PUSH'})
    );
  });

  it('reads Back to a pushed entry as a POP with that entry’s own key', async () => {
    const {user} = renderApp('/files', SERVED);
    await screen.findByRole('heading', {name: 'page files'});
    await follow(user, 'To notifications');
    await screen.findByRole('heading', {name: 'page notifications'});
    const entry = lastCommit();
    await follow(user, 'To help');
    await screen.findByRole('heading', {name: 'page help'});

    await traverse(-1);

    expect(lastCommit()).toMatchObject({page: 'notifications', type: 'POP', key: entry.key});
  });

  it('reads an in-page anchor as a POP with the default key', async () => {
    const {user} = renderApp('/files', SERVED);
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
    const {user} = renderApp('/data-quality', SERVED);
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

  // Two navigations in one event, a native one first: Next renders the native one before the router
  // one, and the router one must still arrive with its own state.
  it('keeps a router navigation’s state when a native navigation renders ahead of it', async () => {
    renderApp('/files', SERVED);
    await screen.findByRole('heading', {name: 'page files'});

    hold();
    act(() => {
      fixture.navigate?.('?x=1', {replace: true});
      fixture.navigate?.('/data-quality', {state: {handOff: true}});
    });
    release();

    await screen.findByRole('heading', {name: 'page data-quality'});
    expect(lastCommit()).toMatchObject({page: 'data-quality', type: 'PUSH', state: {handOff: true}});
  });

  // React renders a traversal inside Next's popstate dispatch, before any listener the app adds,
  // so a seam that classified by its own listener would report a Back as a push for one commit.
  it('reports no type but POP on any commit during a traversal', async () => {
    const {user} = renderApp('/files', SERVED);
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

describe('which navigations are native', () => {
  it('renders /help#files with its hash on the destination’s first render', async () => {
    const {user} = renderApp('/files', SERVED);
    await screen.findByRole('heading', {name: 'page files'});

    await follow(user, 'To help at files');

    await screen.findByRole('heading', {name: 'page help'});
    expect(commitsOf('help')[0]).toMatchObject({pathname: '/help', hash: '#files'});
  });

  // Asserted on the calls the seam makes: a navigation that keeps the committed path is written
  // natively, every other one is Next's to render.
  it('calls router.push for another path, and neither router.push nor router.replace for the same one', async () => {
    resetReadout([...LINKS, {label: 'Same page, another query', to: '/help?topic=y'}]);
    const {user} = renderApp('/files', SERVED);
    await screen.findByRole('heading', {name: 'page files'});
    const push = vi.spyOn(standInRouter(), 'push');
    const replace = vi.spyOn(standInRouter(), 'replace');

    await follow(user, 'To help');
    await screen.findByRole('heading', {name: 'page help'});
    expect(push.mock.calls).toEqual([['/help']]);
    push.mockClear();

    await follow(user, 'Same page, another query');
    await waitFor(() => expect(lastCommit().search).toBe('?topic=y'));
    await follow(user, 'To the files section');
    await waitFor(() => expect(lastCommit().hash).toBe('#files'));
    act(() => fixture.navigate?.('/help#files'));
    await waitFor(() => expect(lastCommit().type).toBe('PUSH'));

    expect(push).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
    expect(mounts).toEqual(['files', 'help']);
  });

  it('changes only the query or the hash on a page without Next’s router, and without a remount', async () => {
    resetReadout([...LINKS, {label: 'Same page, another query', to: '/help?topic=y'}]);
    const {user} = renderApp('/help', SERVED);
    await screen.findByRole('heading', {name: 'page help'});

    await follow(user, 'Same page, another query');
    await waitFor(() => expect(lastCommit().search).toBe('?topic=y'));
    await follow(user, 'To the files section');
    await waitFor(() => expect(lastCommit().hash).toBe('#files'));

    expect(requests()).toEqual([]);
    expect(mounts).toEqual(['help']);
  });

  it('goes through Next’s router to a page at another path', async () => {
    const {user} = renderApp('/files', SERVED);
    await screen.findByRole('heading', {name: 'page files'});

    await follow(user, 'To notifications');

    await screen.findByRole('heading', {name: 'page notifications'});
    expect(requests()).toEqual(['/notifications']);
  });

  // The source is the committed address, never the navigation still pending: with a push to
  // Notifications in flight, a change of query on Notifications is still a move away from Files, and
  // written natively it would leave Files on screen under Notifications' address.
  it('decides by the committed address while a router push is still in flight', async () => {
    renderApp('/files', SERVED);
    await screen.findByRole('heading', {name: 'page files'});

    hold();
    act(() => fixture.navigate?.('/notifications'));
    act(() => fixture.navigate?.('/notifications?x=1'));
    release();

    await screen.findByRole('heading', {name: 'page notifications'});
    await waitFor(() => expect(lastCommit()).toMatchObject({page: 'notifications', search: '?x=1'}));
    expect(screen.queryByRole('heading', {name: 'page files'})).not.toBeInTheDocument();
  });

  // Next writes the address before any layout effect runs, and the seam learns of the arrival only
  // in its own layout effect, after the page's: a page correcting its address as it arrives must be
  // judged against the address, or its replace would go to Next's router as a move to another path.
  it('writes natively a correction the arriving page makes in its first layout effect', async () => {
    const {user} = renderApp('/files', {
      ...SERVED,
      pages: {...SERVED.pages, '(signed-in)/help/page.tsx': CorrectsOnArrival}
    });
    await screen.findByRole('heading', {name: 'page files'});

    await follow(user, 'To help');

    await waitFor(() => expect(window.location.search).toBe('?topic=x'));
    expect(screen.getByRole('heading', {name: 'help corrected'})).toBeInTheDocument();
    expect(requests()).toEqual(['/help']);
  });
});

/** A page that corrects its own address in its first layout effect, before the seam has seen it arrive. */
function CorrectsOnArrival() {
  const navigate = useNavigate();
  useLayoutEffect(() => {
    navigate('?topic=x', {replace: true});
  }, [navigate]);
  return <h1>help corrected</h1>;
}

describe('a target’s trailing slash', () => {
  // Next's router strips a trailing slash, so handed `/files/` from `/files` it would land where it
  // started, and a navigation that never leaves would leave the page's own writes dropped.
  it('writes a target that differs only by a trailing slash natively, at the bare path', async () => {
    renderApp('/files', SERVED);
    await screen.findByRole('heading', {name: 'page files'});

    act(() => fixture.navigate?.('/files/?x=1', {replace: true}));

    await waitFor(() => expect(lastCommit()).toMatchObject({page: 'files', pathname: '/files', search: '?x=1'}));
    expect(requests()).toEqual([]);
  });
});

// A router navigation waits on the server while the page it leaves stays mounted. A native write in
// that window makes Next restore, and a restore discards the pending navigation, so the click is lost.
describe('a page that is leaving', () => {
  // Twice, the first spelled as the browser re-encodes it, so the leave must follow the address shown.
  it('corrects its address without losing the click', async () => {
    const {user} = renderApp('/files', SERVED);
    await screen.findByRole('heading', {name: 'page files'});

    hold();
    await follow(user, 'To notifications');
    act(() => fixture.navigate?.('?space=a b', {replace: true}));
    act(() => fixture.navigate?.('?space=team', {replace: true}));
    release();

    await screen.findByRole('heading', {name: 'page notifications'});
    expect(lastCommit()).toMatchObject({page: 'notifications', pathname: '/notifications', search: ''});
  });

  it('keeps the correction on the entry it left, for Back', async () => {
    const {user} = renderApp('/files', SERVED);
    await screen.findByRole('heading', {name: 'page files'});
    hold();
    await follow(user, 'To notifications');
    act(() => fixture.navigate?.('?space=team', {replace: true}));
    release();
    await screen.findByRole('heading', {name: 'page notifications'});

    await traverse(-1);

    await waitFor(() => expect(lastCommit()).toMatchObject({page: 'files', search: '?space=team', type: 'POP'}));
  });

  // The Back lands on an entry with the same address as the one left, so only the entry tells that the
  // leave is over.
  it('corrects its address as usual once a Back has dropped the navigation', async () => {
    const {user} = renderApp('/files', SERVED);
    await screen.findByRole('heading', {name: 'page files'});
    act(() => fixture.navigate?.('/files'));
    hold();
    await follow(user, 'To notifications');
    await traverse(-1);
    await waitFor(() => expect(lastCommit()).toMatchObject({page: 'files', type: 'POP'}));

    act(() => fixture.navigate?.('?x=1', {replace: true}));

    await waitFor(() => expect(lastCommit()).toMatchObject({page: 'files', search: '?x=1'}));
  });

  // The page does not re-render with its correction, so a second one must build on the address shown,
  // or it would put back what the first removed.
  it('builds a second correction on the first', async () => {
    const options = SERVED;
    const {user} = renderApp('/files', {
      ...options,
      pages: {...options.pages, '(signed-in)/files/page.tsx': FilesWithSearch}
    });
    await screen.findByRole('heading', {name: 'page files'});
    hold();
    await follow(user, 'To notifications');
    act(() => {
      search.set?.((previous) => new URLSearchParams([...previous, ['a', '1']]), {replace: true});
      search.set?.((previous) => new URLSearchParams([...previous, ['b', '2']]), {replace: true});
    });
    release();
    await screen.findByRole('heading', {name: 'page notifications'});

    await traverse(-1);

    await waitFor(() => expect(lastCommit()).toMatchObject({page: 'files', search: '?a=1&b=2'}));
  });

  // A child's layout effects run before the seam's own, so the destination's first write lands
  // while the seam's entry is still the one left; Next has written the new address by then.
  it('keeps a write the destination makes as it first lays out', async () => {
    const options = SERVED;
    const {user, location} = renderApp('/files', {
      ...options,
      pages: {...options.pages, '(signed-in)/notifications/page.tsx': WritesOnArrival}
    });
    await screen.findByRole('heading', {name: 'page files'});

    await follow(user, 'To notifications');

    await screen.findByRole('heading', {name: 'page arrived'});
    await waitFor(() => expect(location().search).toBe('?x=1'));
  });
});

// A page's own write cannot be told from the user's, so only a page's replace on the same path, how a
// page corrects its address, is held to the page; a link clicked, a push or another page is the user
// leaving again, and the last click wins.
describe('the user’s next move during a leave', () => {
  it.each([
    ['a link to the address shown', 'link', {page: 'files', pathname: '/files', hash: ''}],
    ['a page’s push on the same path', 'push', {page: 'files', pathname: '/files', hash: '#files'}],
    ['a page’s replace to another page', 'replace', {page: 'help', pathname: '/help'}]
  ] as const)('wins over the navigation in flight: %s', async (_kind, move, landed) => {
    const {user} = renderApp('/files', SERVED);
    await screen.findByRole('heading', {name: 'page files'});

    hold();
    await follow(user, 'To data quality');
    if (move === 'link') await follow(user, 'To files');
    else if (move === 'push') act(() => fixture.navigate?.('#files'));
    else act(() => fixture.navigate?.('/help', {replace: true}));
    release();

    await waitFor(() => expect(lastCommit()).toMatchObject(landed));
    expect(screen.queryByRole('heading', {name: 'page data-quality'})).not.toBeInTheDocument();
  });
});

// An in-page anchor makes an entry with no state, which Next ignores, so the navigation in flight goes
// on: the anchor must neither end the leave nor be left without the Next state Back needs.
describe('an in-page anchor during a leave', () => {
  it('leaves the navigation in flight, and the page’s correction after it does too', async () => {
    const {user} = renderApp('/files', SERVED);
    await screen.findByRole('heading', {name: 'page files'});

    hold();
    await follow(user, 'To notifications');
    await followAnchor(user);
    act(() => fixture.navigate?.('?space=team', {replace: true}));
    release();

    await screen.findByRole('heading', {name: 'page notifications'});
    expect(lastCommit()).toMatchObject({page: 'notifications', pathname: '/notifications'});
  });

  it('is restorable after a correction, so Back shows the page it belongs to', async () => {
    const {user} = renderApp('/files', SERVED);
    await screen.findByRole('heading', {name: 'page files'});
    hold();
    await follow(user, 'To notifications');
    act(() => fixture.navigate?.('?space=team', {replace: true}));
    await followAnchor(user);
    release();
    await screen.findByRole('heading', {name: 'page notifications'});

    await traverse(-1);

    await waitFor(() => expect(lastCommit()).toMatchObject({page: 'files', search: '?space=team', hash: '#section'}));
  });
});

/** The search setter of the page on screen, for a test to call as the page would. */
const search: {set: ReturnType<typeof useSearchParams>[1] | null} = {set: null};

/** The Files readout, exposing its search setter. */
function FilesWithSearch() {
  const [, set] = useSearchParams();
  useLayoutEffect(() => {
    search.set = set;
  }, [set]);
  return <FilesReadout />;
}

const FilesReadout = readoutPage('files');

/** A destination that corrects its own address in its first layout effect. */
function WritesOnArrival() {
  const navigate = useNavigate();
  useLayoutEffect(() => navigate('?x=1', {replace: true}), [navigate]);
  return <h1>page arrived</h1>;
}

describe('an in-page anchor’s entry', () => {
  // A native anchor makes an entry with no state, and Next ignores a popstate whose state is null,
  // so without the seam stamping it Back would leave the page it came from on screen.
  it('is one a later Back restores, as a POP with the default key', async () => {
    const {user} = renderApp('/files', SERVED);
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
  it('arrives on a link whose query holds an encoded space, and Back reads that entry’s key', async () => {
    resetReadout([...LINKS, {label: 'To My Reports', to: '/files?prefix=My%20Reports%2F', state: {from: 'query'}}]);
    const {user} = renderApp('/notifications', SERVED);
    await screen.findByRole('heading', {name: 'page notifications'});

    await follow(user, 'To My Reports');
    await screen.findByRole('heading', {name: 'page files'});
    const arrived = lastCommit();
    await follow(user, 'To help');
    await screen.findByRole('heading', {name: 'page help'});
    await traverse(-1);

    expect(arrived).toMatchObject({search: '?prefix=My%20Reports%2F', state: {from: 'query'}, type: 'PUSH'});
    expect(lastCommit()).toMatchObject({page: 'files', type: 'POP', key: arrived.key});
  });

  it('reaches the first render, and is gone after Back, Forward and a reload', async () => {
    resetReadout([...LINKS, {label: 'To files with state', to: '/files', state: {handOff: 1}}]);
    const view = renderApp('/notifications', SERVED);
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
    renderApp(window.location.pathname, SERVED);
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
    renderApp('/files', SERVED);
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
    renderApp('/files', SERVED);
    await screen.findByRole('heading', {name: 'page files'});

    expect(screen.getByText('Off site')).not.toHaveAttribute('href');
  });

  // A dot segment before a doubled slash is a path as written and protocol-relative once the URL
  // parser resolves it. Resolved with its doubled slashes collapsed, it stays here: no page serves
  // the path, so Next loads this origin's document there.
  it.each(['/.//evil.example/x', '/a/..//evil.example/x', '/%2e//evil.example/x'])(
    'keeps %j in the portal, collapsing its doubled slashes',
    async (target) => {
      resetReadout([{label: 'Dotted', to: target}]);
      renderApp('/files', SERVED);
      await screen.findByRole('heading', {name: 'page files'});

      expect(screen.getByText('Dotted')).toHaveAttribute('href', '/evil.example/x');
      act(() => fixture.navigate?.(target));

      expect(documentLoads()).toEqual(['/evil.example/x']);
      expect(external()).toEqual([]);
    }
  );

  it('still navigates to the portal’s own paths', async () => {
    const {user} = renderApp('/files', SERVED);
    await screen.findByRole('heading', {name: 'page files'});
    expect(screen.getByRole('link', {name: 'To help at files'})).toHaveAttribute('href', '/help#files');

    act(() => fixture.navigate?.('/notifications'));
    await screen.findByRole('heading', {name: 'page notifications'});
    await follow(user, 'To help at files');

    expect(await screen.findByRole('heading', {name: 'page help'})).toBeInTheDocument();
  });
});

describe('route params', () => {
  // `a%2541` is the one that tells a single decode from a double: twice, it would read `aA`.
  it.each([
    ['a%40b%20c', 'a@b c'],
    ['a%2541', 'a%41']
  ] as const)('decodes a percent-encoded segment exactly once (%s)', async (segment, space) => {
    renderApp(`/data-quality/${segment}/r1`, SERVED);

    await screen.findByRole('heading', {name: 'page report'});
    expect(lastCommit().params).toMatchObject({space, requestId: 'r1'});
  });

  it('matches case-sensitively, as Next routes', () => {
    expect(matchPath('/files', '/Files')).toBeNull();
    expect(matchPath('/files', '/files')).toEqual({params: {}});
  });
});
