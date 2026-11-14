import {describe, it, expect, vi, beforeEach} from 'vitest';
import type {ReactNode} from 'react';
import {Link, useLocation, useNavigate} from '../lib/navigation';
import {act, screen, within, waitFor} from '@testing-library/react';
import {nextPopstate} from '../test/nextNavigation';
import type {UserEvent} from '@testing-library/user-event';
import type {QueryClient} from '@tanstack/react-query';
import {createTestQueryClient, renderWithProviders} from '../test/renderWithProviders';
import {connectionKeys} from '../features/connections/connectionKeys';
import {authenticated} from '../test/authFixtures';
import {FileOpsInFlightProvider, UploadQueueProvider} from '../features/file-browser';
import * as fileService from '../features/file-browser/fileBrowser.service';
import {readSharedConnectionsCache} from '../features/shared-spaces/sharedSpaces.service';
import {getNotifications} from '../features/notifications/notifications.service';
import {submitFileOperation} from '../features/file-browser/fileOps.service';
import type {FileListPage} from '../types/s3.types';
import type {SharedConnectionsCache} from '../features/shared-spaces/sharedSpaces.types';

// Integration style (react.md §21): render the REAL FilesPage — real useAuth
// (injected via renderWithProviders), real useConnections/useFileSpace, the real
// Sidebar, and the real FileBrowser subtree — and mock ONLY the AWS boundary the
// page's tree hits: the file-browser + shared-spaces service modules, the download
// side-effect, and the credentials client. The routing behavior (which bucket +
// prefix the browser targets, the vanished-space fallback) is asserted through what
// the real FileBrowser observably does (its `listFiles` call + rendered breadcrumb).
vi.mock('../features/file-browser/fileBrowser.service', async (importActual) => {
  const actual = await importActual<typeof fileService>();
  return {
    ...actual,
    ensurePrefixMarker: vi.fn().mockResolvedValue({success: true}),
    listFiles: vi.fn(),
    getObjectMetadata: vi.fn(),
    getDownloadUrl: vi.fn(),
    deleteObject: vi.fn(),
    moveObject: vi.fn(),
    copyObject: vi.fn(),
    objectExists: vi.fn(),
    firstFreeName: vi.fn(),
    uploadFile: vi.fn(),
    createFolder: vi.fn()
  };
});
vi.mock('../features/file-browser/fileBrowser.download', () => ({triggerBrowserDownload: vi.fn()}));
vi.mock('../features/shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn(),
  enqueueSharedSpaceRequest: vi.fn().mockResolvedValue({success: true, data: {requestId: 'r1'}})
}));
vi.mock('../features/notifications/notifications.service', async (importActual) => ({
  ...(await importActual<typeof import('../features/notifications/notifications.service')>()),
  getNotifications: vi.fn()
}));
vi.mock('../features/file-browser/fileOps.service', () => ({submitFileOperation: vi.fn()}));
const listFiles = vi.mocked(fileService.listFiles);
const mockReadCache = vi.mocked(readSharedConnectionsCache);

const ok = <T,>(data: T) => ({success: true as const, data});

const page = (over: Partial<FileListPage> = {}): FileListPage => ({
  files: [
    {type: 'file', key: 'alice/report.pdf', name: 'report.pdf', size: 2048, lastModified: new Date('2026-03-04')}
  ],
  folders: [{type: 'folder', prefix: 'alice/docs/', name: 'docs'}],
  isTruncated: false,
  ...over
});

// The per-user cache the pipeline writes: one active shared space (member) and one
// still-provisioning space (owner) → useConnections yields personal + both shared.
const cache: SharedConnectionsCache = {
  version: 1,
  connections: [
    {name: 'marketing_data', role: 'member', status: 'active'},
    {name: 'sales_2026', role: 'owner', status: 'provisioning'}
  ]
};

// The bucket variables are read at call time through `spaceBuckets()`, so the stubs below could in
// principle be set later — the dynamic import is kept because it is what makes the ORDER explicit
// at a glance, and because a module-scope read reintroduced here would otherwise pass locally and
// fail on a machine whose environment differs.
vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-bucket');
const {default: FilesPage} = await import('./FilesPage');

// The UploadQueueProvider lives in the authenticated app layout above the route in
// production; supply it here so the real FileBrowser subtree mounts. `beside` renders next to the
// page under the same router, standing in for the shell around it — a notification row's link.
function renderAt(route: string, queryClient?: QueryClient, beside?: ReactNode) {
  return renderWithProviders(
    <UploadQueueProvider>
      <FileOpsInFlightProvider>
        <FilesPage />
        {beside}
      </FileOpsInFlightProvider>
    </UploadQueueProvider>,
    {route, auth: authenticated('alice'), ...(queryClient && {queryClient})}
  );
}

/** The breadcrumb root crumb (the space name) — scoped to the breadcrumb nav so it
 *  doesn't collide with the sidebar's space list. */
function rootCrumb() {
  return within(screen.getByRole('navigation', {name: 'breadcrumb'}));
}

type CacheRead = Awaited<ReturnType<typeof readSharedConnectionsCache>>;
const NO_SPACES: CacheRead = ok({version: 1, connections: []});
const UNREADABLE: CacheRead = {success: false, error: {message: 'unreadable'}};

/** A client already holding a spaces list — without `marketing_data` unless `list` says otherwise — read
 *  `ageMs` ago under the app's 30s staleTime rather than the harness's 0, so whether the list is stale
 *  is the test's choice. */
function clientWithCachedList(ageMs: number, list: SharedConnectionsCache = {version: 1, connections: []}) {
  const client = createTestQueryClient();
  client.setQueryDefaults(connectionKeys.list('alice'), {gcTime: Infinity, staleTime: 30_000});
  client.setQueryData(connectionKeys.list('alice'), list, {updatedAt: Date.now() - ageMs});
  return client;
}

/** Drives New folder from the page as seeded and returns the key the write lands at — a listing at
 *  the root would not show where a folder went. */
async function newFolderKey(user: UserEvent, name: string): Promise<string> {
  const createFolder = vi
    .mocked(fileService.createFolder)
    .mockImplementation(async (params) => ok({prefix: `${params.prefix}${params.name}/`}));
  await user.click(await screen.findByRole('button', {name: 'New folder'}));
  const dialog = await screen.findByRole('dialog');
  await user.type(within(dialog).getByRole('textbox'), name);
  await user.click(within(dialog).getByRole('button', {name: /create/i}));
  await waitFor(() => expect(createFolder).toHaveBeenCalledOnce());
  const [{prefix, name: written}] = createFolder.mock.calls[0];
  return `${prefix}${written}/`;
}

beforeEach(() => {
  vi.clearAllMocks();
  window.innerWidth = 1024;
  listFiles.mockResolvedValue(ok(page()));
  mockReadCache.mockResolvedValue(ok(cache));
  vi.mocked(getNotifications).mockResolvedValue(ok([]));
  vi.mocked(submitFileOperation).mockResolvedValue({success: true, data: undefined});
});

describe('FilesPage — personal space (SPEC-013/044)', () => {
  it('defaults to the personal space: lists {username}/ in the user bucket, writable', async () => {
    renderAt('/files');
    await waitFor(() =>
      expect(listFiles).toHaveBeenCalledWith('user-bucket', 'alice/', undefined, expect.any(AbortSignal))
    );
    // The username is the root breadcrumb crumb, and write controls are present.
    expect(rootCrumb().getByText('alice')).toBeInTheDocument();
    expect(await screen.findByRole('button', {name: 'New folder'})).toBeInTheDocument();
  });

  it('seeds the browser at an in-space ?prefix= deep link', async () => {
    renderAt('/files?prefix=alice%2Fsales%2F');
    await waitFor(() =>
      expect(listFiles).toHaveBeenCalledWith('user-bucket', 'alice/sales/', undefined, expect.any(AbortSignal))
    );
  });

  it('ignores an out-of-space ?prefix= and falls back to the space root', async () => {
    renderAt('/files?prefix=bob%2Fsecret%2F');
    await waitFor(() =>
      expect(listFiles).toHaveBeenCalledWith('user-bucket', 'alice/', undefined, expect.any(AbortSignal))
    );
  });

  it('ignores a ?prefix= that stops mid-name, so New folder cannot finish the name it started', async () => {
    // The folder-name check reads the parent's last segment, and a folder's key is parent + name +
    // `/`. Seeded at `…/athena`, `results` passed the check and wrote the app's own results folder.
    const {user} = renderAt('/files?prefix=alice%2Fsystem_settings%2Fathena');
    expect(await newFolderKey(user, 'results')).toBe('alice/results/');
  });

  it.each([
    ['an empty segment', 'alice//docs/'],
    ['a . segment', 'alice/./docs/'],
    ['a .. segment', 'alice/../bob/']
  ])('ignores a ?prefix= with %s, so New folder writes at the root', async (_shape, seeded) => {
    // S3 resolves neither: `alice//docs/` is a look-alike the breadcrumbs render as `alice/docs/`,
    // and a dot segment names a folder the API refuses every write into.
    const {user} = renderAt(`/files?prefix=${encodeURIComponent(seeded)}`);
    expect(await newFolderKey(user, 'notes')).toBe('alice/notes/');
  });
});

describe('FilesPage — shared space (SPEC-057 FR-002/FR-004)', () => {
  it('targets the shared bucket + space root for an active ?space=', async () => {
    renderAt('/files?space=marketing_data');
    await waitFor(() =>
      expect(listFiles).toHaveBeenCalledWith('shared-bucket', 'marketing_data/', undefined, expect.any(AbortSignal))
    );
    expect(rootCrumb().getByText('marketing_data')).toBeInTheDocument();
  });

  it('opens a ?space= a fresh cached list already has, without reading the list', async () => {
    // Only an absence waits for a read: a space the list names as usable is opened on its word.
    renderAt('/files?space=marketing_data', clientWithCachedList(0, cache));
    await waitFor(() =>
      expect(listFiles).toHaveBeenCalledWith('shared-bucket', 'marketing_data/', undefined, expect.any(AbortSignal))
    );
    expect(mockReadCache).not.toHaveBeenCalled();
  });

  // The deep link the save-results toast and the rail's "View source files" both build.
  it('seeds a shared space at an in-space ?prefix= deep link', async () => {
    renderAt('/files?space=marketing_data&prefix=marketing_data%2Freports%2F');
    await waitFor(() =>
      expect(listFiles).toHaveBeenCalledWith(
        'shared-bucket',
        'marketing_data/reports/',
        undefined,
        expect.any(AbortSignal)
      )
    );
  });

  it.each([
    ['nothing is cached yet', () => undefined],
    ['a stale cached list predates the space', () => clientWithCachedList(60_000)],
    ['a fresh cached list predates the space', () => clientWithCachedList(0)]
  ])(
    'holds the browser back while a ?space= deep link resolves (%s), so nothing opens in the personal bucket first',
    async (_cached, seededClient) => {
      // Resolved personal-first while the spaces were read, the page mounted a writable browser on the
      // user's own bucket and swapped it out afterwards; an upload started in between stayed there. A
      // cached list counts however fresh: a notification followed moments after joining names a space
      // that list was read without, and trusted, it refused the space as "no longer available".
      let resolveCache: (result: CacheRead) => void = () => {};
      mockReadCache.mockReturnValue(new Promise((resolve) => (resolveCache = resolve)));
      renderAt('/files?space=marketing_data&prefix=marketing_data%2Fr%2F', seededClient());

      expect(await screen.findByText('Loading files…')).toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(screen.queryByText(/no longer available/i)).not.toBeInTheDocument();
      expect(screen.queryByText('(current space)')).not.toBeInTheDocument();

      resolveCache(ok(cache));
      await waitFor(() =>
        expect(listFiles).toHaveBeenCalledWith('shared-bucket', 'marketing_data/r/', undefined, expect.any(AbortSignal))
      );
      expect(listFiles.mock.calls.map(([bucket]) => bucket)).not.toContain('user-bucket');
    }
  );

  // Every state a page can mount in, settling without the space and then seeing a later refetch
  // (opening Send, a reconnect). One read after the link is waited for — the one owed on mount, or
  // the one the link asks for — and never again once it settles: three of these rows reproduce a
  // wait that came back and unmounted the browser, with the dialog open in it; a failed read would
  // otherwise have loaded for ever, and a second read on mount is one the link never needed.
  it.each([
    ['fresh in the cache, so read once for the link', () => clientWithCachedList(0), NO_SPACES, 1],
    ['fresh in the cache, and that read fails', () => clientWithCachedList(0), UNREADABLE, 1],
    ['stale in the cache, so re-read once on mount', () => clientWithCachedList(60_000), NO_SPACES, 1],
    ['not cached, and the read finds no such space', () => undefined, NO_SPACES, 1],
    ['not cached, and the read fails', () => undefined, UNREADABLE, 1]
  ])(
    'falls back when the spaces list lacks the ?space= (%s), and a later refetch leaves the page as it is',
    async (_mountedWith, seededClient, firstRead, readsOnMount) => {
      mockReadCache.mockResolvedValue(firstRead);
      const {user, queryClient} = renderAt('/files?space=marketing_data', seededClient());
      await user.click(await screen.findByRole('button', {name: 'New folder'}));
      expect(await screen.findByRole('dialog')).toBeInTheDocument();
      expect(mockReadCache).toHaveBeenCalledTimes(readsOnMount);

      let resolveRead: (result: CacheRead) => void = () => {};
      mockReadCache.mockReturnValue(new Promise((resolve) => (resolveRead = resolve)));
      const refetch = queryClient.invalidateQueries({queryKey: connectionKeys.list('alice')});
      await act(() => new Promise((settle) => setTimeout(settle, 20)));
      expect(screen.queryByText('Loading files…')).not.toBeInTheDocument();

      resolveRead(NO_SPACES);
      await act(() => refetch);
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    }
  );

  it('reads the spaces list again when a link followed on the open page names a space it lacks', async () => {
    // A notification row links to `/files?space=…`. Followed with Files already open, the page does
    // not remount, so no read is owed: checked against the list the page opened with, a space joined
    // since was refused as "no longer available", and nothing ever read the list again.
    mockReadCache.mockResolvedValueOnce(NO_SPACES);
    const {user, queryClient} = renderAt(
      '/files',
      clientWithCachedList(60_000),
      <Link to="/files?space=marketing_data">Open marketing_data</Link>
    );
    await waitFor(() => expect(mockReadCache).toHaveBeenCalledOnce());
    await waitFor(() => expect(queryClient.isFetching({queryKey: connectionKeys.list('alice')})).toBe(0));

    let resolveRead: (result: CacheRead) => void = () => {};
    mockReadCache.mockReturnValue(new Promise((resolve) => (resolveRead = resolve)));
    await user.click(screen.getByRole('link', {name: 'Open marketing_data'}));

    expect(await screen.findByText('Loading files…')).toBeInTheDocument();
    expect(screen.queryByText(/no longer available/i)).not.toBeInTheDocument();
    expect(mockReadCache).toHaveBeenCalledTimes(2);

    resolveRead(ok(cache));
    await waitFor(() =>
      expect(listFiles).toHaveBeenLastCalledWith('shared-bucket', 'marketing_data/', undefined, expect.any(AbortSignal))
    );
    expect(screen.queryByText(/no longer available/i)).not.toBeInTheDocument();
    expect(mockReadCache).toHaveBeenCalledTimes(2);
  });

  it('leaves a resolved link alone when the page moves to a fragment, as the skip link does', async () => {
    // The shell's "Skip to main content" is a same-document navigation. Measured in Chromium: the
    // new entry carries no history state and `popstate` fires, so the entry's key falls back to
    // "default" while the address still names the space. Read as a fresh follow, every skip-link
    // click would unmount the browser and spend a read — on the keyboard users the bypass link
    // exists for. jsdom follows an in-page anchor the same way (the address moves a task later and
    // a null-state `popstate` fires), so the anchor is a real one, clicked; the link is followed
    // first because that is what puts a key on the entry for the fragment to lose.
    mockReadCache.mockResolvedValue(NO_SPACES);
    const {user, location} = renderAt(
      '/files',
      clientWithCachedList(0),
      <>
        <Link to="/files?space=marketing_data">Open marketing_data</Link>
        <a href="#main">Skip to main content</a>
      </>
    );
    await user.click(screen.getByRole('link', {name: 'Open marketing_data'}));
    expect(await screen.findByText(/no longer available/i)).toBeInTheDocument();
    expect(mockReadCache).toHaveBeenCalledOnce();

    await act(async () => {
      const moved = nextPopstate();
      await user.click(screen.getByRole('link', {name: 'Skip to main content'}));
      await moved;
    });

    expect(location()).toMatchObject({hash: '#main', key: 'default'});
    expect(screen.getByRole('button', {name: 'New folder'})).toBeInTheDocument();
    expect(screen.queryByText('Loading files…')).not.toBeInTheDocument();
    expect(mockReadCache).toHaveBeenCalledOnce();
  });

  it('reads the list again when the same link is followed a second time', async () => {
    // While the notice shows, the address still names the space, so following the link again changes
    // only the navigation. That follow asks the question afresh, and a read before it cannot answer.
    mockReadCache.mockResolvedValue(NO_SPACES);
    const {user} = renderAt(
      '/files',
      clientWithCachedList(0),
      <Link to="/files?space=marketing_data">Open marketing_data</Link>
    );
    await user.click(screen.getByRole('link', {name: 'Open marketing_data'}));
    expect(await screen.findByText(/no longer available/i)).toBeInTheDocument();
    expect(mockReadCache).toHaveBeenCalledOnce();

    mockReadCache.mockResolvedValue(ok(cache));
    await user.click(screen.getByRole('link', {name: 'Open marketing_data'}));
    await waitFor(() =>
      expect(listFiles).toHaveBeenLastCalledWith('shared-bucket', 'marketing_data/', undefined, expect.any(AbortSignal))
    );
    expect(screen.queryByText(/no longer available/i)).not.toBeInTheDocument();
    expect(mockReadCache).toHaveBeenCalledTimes(2);
  });

  it('falls back to the personal space with a notice for a ?space= that is gone or not yet usable', async () => {
    // Unknown space → fallback; the browser targets the personal space and a
    // non-blocking status notice explains the switch.
    const unknown = renderAt('/files?space=ghost');
    await waitFor(() =>
      expect(listFiles).toHaveBeenLastCalledWith('user-bucket', 'alice/', undefined, expect.any(AbortSignal))
    );
    expect(await screen.findByText(/no longer available/i)).toBeInTheDocument();
    unknown.unmount();

    // A provisioning (not-yet-usable) space resolves the same way.
    listFiles.mockClear();
    renderAt('/files?space=sales_2026');
    await waitFor(() =>
      expect(listFiles).toHaveBeenCalledWith('user-bucket', 'alice/', undefined, expect.any(AbortSignal))
    );
    expect(await screen.findByText(/no longer available/i)).toBeInTheDocument();
  });
});

describe('FilesPage — a conflict review deep link', () => {
  /** The page's query string, as the address bar would show it. */
  function LocationProbe() {
    return <output aria-label="Address query">{useLocation().search}</output>;
  }

  const CONFLICTED = {
    id: 'n9',
    message: 'Moved 1 of 2 items to “out”.',
    read: false,
    timestamp: '2026-08-23T00:00:00Z',
    link: '/files?prefix=alice/out/',
    payload: {
      requestId: 'run-1',
      operation: 'move',
      source: {kind: 'personal', name: 'alice'},
      destination: {kind: 'personal', name: 'alice', prefix: 'alice/out/'},
      conflicts: [{itemKey: 'alice/q1.csv', kind: 'file'}]
    }
  };

  it('drops ?requestId= in place once the review is resolved, so a reload or Back cannot reopen it', async () => {
    vi.mocked(getNotifications).mockResolvedValue(ok([CONFLICTED]));
    const {user} = renderAt('/files?prefix=alice/docs/&requestId=run-1', undefined, <LocationProbe />);

    const review = await screen.findByRole('alertdialog', {name: 'Review conflicts'});
    await user.click(within(review).getByRole('button', {name: 'Overwrite…'}));
    const confirm = await screen.findByRole('alertdialog', {name: 'Confirm overwrite'});
    await user.click(within(confirm).getByRole('button', {name: 'Overwrite'}));

    // Waited on the ADDRESS, not the dialog: the review closes on local state at once, and the
    // navigation that drops the id may commit a render later.
    await waitFor(() => expect(screen.getByLabelText('Address query')).toHaveTextContent(/^\?prefix=alice%2Fdocs%2F$/));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(vi.mocked(submitFileOperation)).toHaveBeenCalledOnce();
  });

  it('leaves the user where they went when the resolve lands after they left the page', async () => {
    vi.mocked(getNotifications).mockResolvedValue(ok([CONFLICTED]));
    let land: (value: Awaited<ReturnType<typeof submitFileOperation>>) => void = () => undefined;
    vi.mocked(submitFileOperation).mockReturnValue(new Promise((resolve) => (land = resolve)));
    let go: ReturnType<typeof useNavigate> = () => undefined;
    function Where() {
      go = useNavigate();
      const {pathname, search} = useLocation();
      return <output aria-label="Address">{pathname + search}</output>;
    }
    // The page for the address, inside the shell's providers as the app holds them.
    function Page() {
      return useLocation().pathname === '/notifications' ? <p>Inbox</p> : <FilesPage />;
    }
    const {user} = renderWithProviders(
      <UploadQueueProvider>
        <FileOpsInFlightProvider>
          <Page />
          <Where />
        </FileOpsInFlightProvider>
      </UploadQueueProvider>,
      {route: '/files?prefix=alice/docs/&requestId=run-1', auth: authenticated('alice')}
    );
    const review = await screen.findByRole('alertdialog', {name: 'Review conflicts'});
    await user.click(within(review).getByRole('button', {name: 'Overwrite…'}));
    const confirm = await screen.findByRole('alertdialog', {name: 'Confirm overwrite'});
    await user.click(within(confirm).getByRole('button', {name: 'Overwrite'}));
    await act(async () => go('/notifications'));

    await act(async () => land({success: true, data: undefined}));

    expect(await screen.findByText('Inbox')).toBeInTheDocument();
    expect(screen.getByLabelText('Address')).toHaveTextContent(/^\/notifications$/);
  });

  it('drops ?requestId= on a space switch, which remounts the browser', async () => {
    const {user} = renderAt('/files?requestId=run-1', undefined, <LocationProbe />);

    const spaces = (await screen.findAllByRole('list', {name: 'Spaces'}))[0];
    await user.click(await within(spaces).findByRole('button', {name: /marketing_data/}));

    await waitFor(() => expect(screen.getByLabelText('Address query')).toHaveTextContent('?space=marketing_data'));
    expect(screen.getByLabelText('Address query')).not.toHaveTextContent('requestId');
  });
});
