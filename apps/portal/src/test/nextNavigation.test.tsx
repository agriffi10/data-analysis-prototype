import {useEffect} from 'react';
import {act, render} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it} from 'vitest';
import {
  NextStandInRoot,
  announcements,
  documentLoads,
  hold,
  release,
  reloads,
  traverse,
  requests,
  resetStandIn,
  useParams,
  usePathname,
  useRouter,
  useSearchParams,
  useStandInTree,
  writeAddressRaw
} from './nextNavigation';
import {selectPage} from './pageSelection';

/**
 * The stand-in for Next's App Router, one test per behaviour it models. Each asserts the behaviour
 * itself, because the seam's own tests can only be as faithful as what they run against.
 */

type Seen = {
  pathname: string;
  search: string;
  tree: string;
  address: string;
  params: Record<string, string | string[]>;
};

const seen: Seen[] = [];
const handle: {router: ReturnType<typeof useRouter> | null} = {router: null};

/** Records, on every render, what Next's hooks say and what the address bar shows at that moment. */
function Probe() {
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const tree = useStandInTree();
  const params = useParams();
  const router = useRouter();
  useEffect(() => {
    handle.router = router;
  });
  seen.push({pathname, search, tree, address: window.location.pathname + window.location.search, params});
  return null;
}

const last = () => seen[seen.length - 1];

/** The stand-in's router, as the probe last saw it. */
function router(): ReturnType<typeof useRouter> {
  if (!handle.router) throw new Error('the probe has not rendered');
  return handle.router;
}

function start(href: string, resolver: Parameters<typeof resetStandIn>[0] = null, pagesOnly = false) {
  writeAddressRaw(null, href);
  resetStandIn(resolver, pagesOnly);
  seen.length = 0;
  render(
    <NextStandInRoot>
      <Probe />
    </NextStandInRoot>
  );
}

const before = window.location.href;
beforeEach(() => {
  seen.length = 0;
});
afterEach(() => {
  writeAddressRaw(null, before);
});

describe('the next/navigation stand-in', () => {
  it('1: renders a router push before it writes the address', () => {
    start('/a');

    act(() => router().push('/b'));

    const rendered = seen.find((entry) => entry.pathname === '/b');
    expect(rendered?.address).toBe('/a');
    expect(window.location.pathname).toBe('/b');
    expect(window.history.state).toMatchObject({__NA: true, __PRIVATE_NEXTJS_INTERNALS_TREE: {href: '/b'}});
  });

  it('2: renders a traversal inside the popstate dispatch, with the address already moved, before the app hears it', async () => {
    start('/a');
    act(() => router().push('/b'));
    const heard: string[] = [];
    const listener = () => heard.push(last().pathname);
    window.addEventListener('popstate', listener, true);

    await traverse(-1);

    window.removeEventListener('popstate', listener, true);
    expect(heard).toEqual(['/a']);
    expect(seen.find((entry) => entry.pathname === '/a' && entry.tree === '/a')?.address).toBe('/a');
  });

  it('3: moves the pathname and search on an external pushState without changing the page, and copies its state', () => {
    start('/a');

    act(() => window.history.pushState({mine: 1}, '', '/c?x=1'));

    expect(last()).toMatchObject({pathname: '/c', search: 'x=1', tree: '/a'});
    expect(window.history.state).toMatchObject({mine: 1, __NA: true, __PRIVATE_NEXTJS_INTERNALS_TREE: {href: '/a'}});

    // Data that already carries Next's marker passes straight through, as Next's own writes do.
    act(() => window.history.pushState({__NA: true}, '', '/d'));
    expect(last().pathname).toBe('/c');
  });

  it('4: ignores a popstate whose state is null, and would reload on one that is not Next’s', () => {
    start('/a');
    const renders = seen.length;
    writeAddressRaw(null, '/elsewhere');

    act(() => {
      window.dispatchEvent(new PopStateEvent('popstate', {state: null}));
    });

    expect(seen.length).toBe(renders);
    expect(last().pathname).toBe('/a');
    act(() => {
      window.dispatchEvent(new PopStateEvent('popstate', {state: {foreign: true}}));
    });
    expect(reloads()).toBe(1);
  });

  it('5: re-serializes the search', () => {
    start('/a');

    act(() => router().push('/a?prefix=My%20Reports%2F'));

    expect(last().search).toBe('prefix=My+Reports%2F');
  });

  it('6: fetches on every router navigation, and replaces rather than adds on one to the current address', () => {
    start('/a');
    const length = window.history.length;

    act(() => router().push('/a'));

    expect(window.history.length).toBe(length);
    expect(requests()).toEqual(['/a']);
    act(() => router().push('/b'));
    expect(window.history.length).toBe(length + 1);
    expect(requests()).toEqual(['/a', '/b']);
  });

  it('7: holds a router push uncommitted until a later navigation supersedes or drops it', () => {
    start('/a');

    hold();
    act(() => router().push('/b'));
    expect(last()).toMatchObject({pathname: '/a', tree: '/a', address: '/a'});

    act(() => router().push('/c'));
    expect(last()).toMatchObject({pathname: '/c', tree: '/c'});

    hold();
    act(() => router().push('/d'));
    act(() => window.history.pushState({}, '', '/e'));
    release();
    // Dropped: the address moved under it, over the page already shown.
    expect(last()).toMatchObject({pathname: '/e', tree: '/c'});
  });

  it('7: drops a router push still in flight when a traversal arrives', async () => {
    start('/a');
    act(() => router().push('/b'));

    hold();
    act(() => router().push('/c'));
    await traverse(-1);
    release();

    expect(last()).toMatchObject({pathname: '/a', tree: '/a'});
  });

  it('8: hands over the selected page’s params percent-encoded, from the page and not the address', () => {
    const files = ['(signed-in)/data-quality/[space]/[requestId]/page.tsx', 'page.tsx'];
    start('/a', (pathname) => selectPage(files, pathname));

    act(() => router().push('/data-quality/a%40b%20c/r1'));
    expect(last().params).toEqual({space: 'a%40b%20c', requestId: 'r1'});

    act(() => window.history.pushState({}, '', '/data-quality/other/r2'));
    expect(last().params).toEqual({space: 'a%40b%20c', requestId: 'r1'});
  });

  it('9: announces the title once the page’s own effects have set it, when it changed since the last tree', async () => {
    writeAddressRaw(null, '/a');
    resetStandIn();
    document.title = 'Before';
    render(
      <NextStandInRoot>
        <Probe />
        <TitledPage />
      </NextStandInRoot>
    );
    expect(announcements()).toEqual([]);

    act(() => router().push('/b'));
    act(() => window.history.pushState({}, '', '/b?c'));
    document.title = 'Changed in place';
    act(() => window.history.pushState({}, '', '/b?d'));
    await traverse(-3);

    expect(announcements()).toEqual(['Page /b', 'Changed in place', 'Page /a']);
  });

  it('10: loads the document for a router navigation or a traversal to a path no page serves', async () => {
    const files = ['page.tsx', '(signed-in)/files/page.tsx'];
    start('/files', (pathname) => selectPage(files, pathname), true);

    act(() => router().push('/nope?x=1#h'));
    expect(last()).toMatchObject({pathname: '/files', tree: '/files', address: '/files'});
    act(() => router().push('/'));
    act(() => window.history.pushState({}, '', '/nope'));
    act(() => router().push('/files'));
    const renders = seen.length;
    await traverse(-1);

    expect(documentLoads()).toEqual(['/nope?x=1#h', '/nope']);
    expect(seen.length).toBe(renders);
    expect(last().tree).toBe('/files');
  });

  it('10: restores, rather than loads, a traversal between two entries of one such path', async () => {
    start('/nope', (pathname) => selectPage(['page.tsx'], pathname), true);
    act(() => window.history.pushState({}, '', '/nope#x'));

    await traverse(-1);

    expect(documentLoads()).toEqual([]);
    expect(last()).toMatchObject({pathname: '/nope', address: '/nope'});
  });

  it('10: renders every navigation for a resolver that selects params rather than pages', () => {
    start('/a', (pathname) => (pathname === '/a' ? {params: {}} : null));

    act(() => router().push('/b'));

    expect(documentLoads()).toEqual([]);
    expect(last()).toMatchObject({pathname: '/b', tree: '/b'});
  });
});

/** A page that titles itself in a passive effect, from the tree the router selected. */
function TitledPage() {
  const tree = useStandInTree();
  useEffect(() => {
    document.title = `Page ${tree}`;
  }, [tree]);
  return null;
}
