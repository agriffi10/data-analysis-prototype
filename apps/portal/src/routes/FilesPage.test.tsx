import {describe, it, expect, vi, beforeEach} from 'vitest';
import {screen, within, waitFor} from '@testing-library/react';
import {renderWithProviders} from '../test/renderWithProviders';
import {authenticated} from '../test/authFixtures';
import {UploadQueueProvider} from '../features/file-browser';
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
    deleteObjects: vi.fn(),
    deleteFolder: vi.fn(),
    moveObject: vi.fn(),
    moveFolder: vi.fn(),
    copyObject: vi.fn(),
    copyFolder: vi.fn(),
    objectExists: vi.fn(),
    uploadFile: vi.fn(),
    createFolder: vi.fn()
  };
});
vi.mock('../features/file-browser/fileBrowser.download', () => ({triggerBrowserDownload: vi.fn()}));
vi.mock('../features/shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn(),
  enqueueSharedSpaceRequest: vi.fn().mockResolvedValue({success: true, data: {requestId: 'r1'}})
}));
vi.mock('../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}}),
  getIdToken: vi.fn().mockResolvedValue({success: true, data: 'id-token'})
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

// The BUCKET vars are read at call time now (SPEC-155 FR-006, via `spaceBuckets()`),
// but the dev-unauth trio — `devUnauthenticated`, `devBucket`, `devPrefix` — is still
// evaluated at import, so the env must be stubbed BEFORE the module loads. Hence the
// dynamic import.
vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-bucket');
const {default: FilesPage} = await import('./FilesPage');

// The UploadQueueProvider lives in the authenticated app layout above the route in
// production; supply it here so the real FileBrowser subtree mounts.
function renderAt(route: string) {
  return renderWithProviders(
    <UploadQueueProvider>
      <FilesPage />
    </UploadQueueProvider>,
    {route, auth: authenticated('alice')}
  );
}

/** The breadcrumb root crumb (the space name) — scoped to the breadcrumb nav so it
 *  doesn't collide with the sidebar's space list. */
function rootCrumb() {
  return within(screen.getByRole('navigation', {name: 'breadcrumb'}));
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
    await waitFor(() => expect(listFiles).toHaveBeenCalledWith('user-bucket', 'alice/', undefined));
    // The username is the root breadcrumb crumb, and write controls are present.
    expect(rootCrumb().getByText('alice')).toBeInTheDocument();
    expect(await screen.findByRole('button', {name: 'New folder'})).toBeInTheDocument();
  });

  it('seeds the browser at an in-space ?prefix= deep link', async () => {
    renderAt('/files?prefix=alice%2Fsales%2F');
    await waitFor(() => expect(listFiles).toHaveBeenCalledWith('user-bucket', 'alice/sales/', undefined));
  });

  it('ignores an out-of-space ?prefix= and falls back to the space root', async () => {
    renderAt('/files?prefix=bob%2Fsecret%2F');
    await waitFor(() => expect(listFiles).toHaveBeenCalledWith('user-bucket', 'alice/', undefined));
  });
});

describe('FilesPage — shared space (SPEC-057 FR-002/FR-004)', () => {
  it('targets the shared bucket + space root for an active ?space=', async () => {
    renderAt('/files?space=marketing_data');
    await waitFor(() => expect(listFiles).toHaveBeenCalledWith('shared-bucket', 'marketing_data/', undefined));
    expect(rootCrumb().getByText('marketing_data')).toBeInTheDocument();
  });

  it('falls back to the personal space with a notice for a ?space= that is gone or not yet usable', async () => {
    // Unknown space → fallback; the browser targets the personal space and a
    // non-blocking status notice explains the switch.
    const unknown = renderAt('/files?space=ghost');
    await waitFor(() => expect(listFiles).toHaveBeenLastCalledWith('user-bucket', 'alice/', undefined));
    expect(await screen.findByText(/no longer available/i)).toBeInTheDocument();
    unknown.unmount();

    // A provisioning (not-yet-usable) space resolves the same way.
    listFiles.mockClear();
    renderAt('/files?space=sales_2026');
    await waitFor(() => expect(listFiles).toHaveBeenCalledWith('user-bucket', 'alice/', undefined));
    expect(await screen.findByText(/no longer available/i)).toBeInTheDocument();
  });
});
