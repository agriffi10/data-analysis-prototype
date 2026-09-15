import {describe, it, expect, vi, beforeEach} from 'vitest';
import {act, screen, within, waitFor} from '@testing-library/react';
import type {UserEvent} from '@testing-library/user-event';
import type {QueryClient} from '@tanstack/react-query';
import {createTestQueryClient, renderWithProviders} from '../test/renderWithProviders';
import {connectionKeys} from '../features/connections/connectionKeys';
import {authenticated} from '../test/authFixtures';
import {FileOpsInFlightProvider, UploadQueueProvider} from '../features/file-browser';
import * as fileService from '../features/file-browser/fileBrowser.service';
import {readSharedConnectionsCache} from '../features/shared-spaces/sharedSpaces.service';
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
// production; supply it here so the real FileBrowser subtree mounts.
function renderAt(route: string, queryClient?: QueryClient) {
  return renderWithProviders(
    <UploadQueueProvider>
      <FileOpsInFlightProvider>
        <FilesPage />
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

/** A client already holding a spaces list without `marketing_data`, read `ageMs` ago under the app's
 *  30s staleTime rather than the harness's 0 — so whether the list is stale is the test's choice. */
function clientWithCachedList(ageMs: number): QueryClient {
  const client = createTestQueryClient();
  client.setQueryDefaults(connectionKeys.list('alice'), {gcTime: Infinity, staleTime: 30_000});
  client.setQueryData(connectionKeys.list('alice'), {version: 1, connections: []}, {updatedAt: Date.now() - ageMs});
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
    ['a stale cached list predates the space', () => clientWithCachedList(60_000)]
  ])(
    'holds the browser back while a ?space= deep link resolves (%s), so nothing opens in the personal bucket first',
    async (_cached, seededClient) => {
      // Resolved personal-first while the spaces were read, the page mounted a writable browser on the
      // user's own bucket and swapped it out afterwards; an upload started in between stayed there. A
      // stale cached list counts, because `isLoading` is false as soon as anything is cached.
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
  // (opening Send, a reconnect). Only the read owed on mount is waited for, and never again once it
  // settles: three of these rows reproduce a wait that came back and unmounted the browser, with the
  // dialog open in it; the failed read would otherwise have loaded for ever.
  it.each([
    ['fresh in the cache, so trusted without a read', () => clientWithCachedList(0), NO_SPACES, 0],
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
