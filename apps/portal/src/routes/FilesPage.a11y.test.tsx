import {describe, it, expect, vi, beforeEach} from 'vitest';
import {screen} from '@testing-library/react';
import {QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import {AuthContext} from '../features/auth/authContext';
import {authenticated} from '../test/authFixtures';
import {createTestQueryClient, renderWithProviders} from '../test/renderWithProviders';
import {expectNoA11yViolations, ROUTE_AXE_OPTIONS} from '../test/axe';
import {UploadQueueProvider} from '../features/file-browser';
import {fileBrowserKeys} from '../features/file-browser/fileBrowserKeys';
import * as fileService from '../features/file-browser/fileBrowser.service';
import {readSharedConnectionsCache} from '../features/shared-spaces/sharedSpaces.service';
import type {FileListPage} from '../types/s3.types';

// Integration style (react.md §21): render the REAL FilesPage shell + the REAL
// FileBrowser populated with content (folders + files), so the authenticated
// browser's a11y is exercised at route level. Mock ONLY the AWS boundary; the real
// hooks resolve the default personal space.
vi.mock('../features/file-browser/fileBrowser.service', async (importActual) => {
  const actual = await importActual<typeof fileService>();
  return {
    ...actual,
    ensurePrefixMarker: vi.fn().mockResolvedValue({success: true}),
    listFiles: vi.fn(),
    getObjectMetadata: vi.fn(),
    getDownloadUrl: vi.fn()
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
const ok = <T,>(data: T) => ({success: true as const, data});

const listing: FileListPage = {
  files: [
    {type: 'file', key: 'alice/report.pdf', name: 'report.pdf', size: 1024, lastModified: new Date('2024-01-01')},
    {type: 'file', key: 'alice/data.csv', name: 'data.csv', size: 2048, lastModified: new Date('2024-02-01')}
  ],
  folders: [{type: 'folder', prefix: 'alice/photos/', name: 'photos'}],
  isTruncated: false
};

vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
const {default: FilesPage} = await import('./FilesPage');

beforeEach(() => {
  vi.clearAllMocks();
  window.innerWidth = 1024;
  listFiles.mockResolvedValue(ok(listing));
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(ok({version: 1, connections: []}));
});

// A QueryClient pre-seeded with the personal-space listing so the real FileBrowser
// paints its populated state synchronously (axe then evaluates content, not a
// loading spinner). The personal space resolves from `username` without waiting on
// the connections read.
function seededClient() {
  const client = createTestQueryClient();
  client.setQueryData(fileBrowserKeys.list('user-bucket', 'alice/'), {pages: [listing], pageParams: [undefined]});
  return client;
}

const tree = (
  <QueryClientProvider client={seededClient()}>
    <AuthContext.Provider value={authenticated('alice')}>
      <MemoryRouter initialEntries={['/files']}>
        <UploadQueueProvider>
          <FilesPage />
        </UploadQueueProvider>
      </MemoryRouter>
    </AuthContext.Provider>
  </QueryClientProvider>
);

describe('FilesPage accessibility (SPEC-045 FR-003)', () => {
  it('has no axe violations with folders + files present', async () => {
    await expectNoA11yViolations(tree, ROUTE_AXE_OPTIONS);
  });

  it('exposes exactly one <h1> and a <main> landmark, with content present', async () => {
    renderWithProviders(
      <UploadQueueProvider>
        <FilesPage />
      </UploadQueueProvider>,
      {route: '/files', auth: authenticated('alice'), queryClient: seededClient()}
    );
    expect(await screen.findByText('report.pdf')).toBeInTheDocument();
    expect(screen.getAllByRole('heading', {level: 1})).toHaveLength(1);
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(screen.getByText('photos')).toBeInTheDocument();
  });
});
