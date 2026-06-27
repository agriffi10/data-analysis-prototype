import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen} from '@testing-library/react';
import type {ReactNode} from 'react';
import {MemoryRouter} from 'react-router-dom';
import {expectNoA11yViolations, ROUTE_AXE_OPTIONS} from '../test/axe';
import {useFileBrowser} from '../features/file-browser/useFileBrowser';
import type {UseFileBrowserResult} from '../features/file-browser/useFileBrowser';
import {useFileUpload} from '../features/file-browser/useFileUpload';
import type {UseFileUploadResult} from '../features/file-browser/useFileUpload';
import {useUploadQueue} from '../features/file-browser/uploadQueueContext';
import type {UploadQueueContextValue} from '../features/file-browser/uploadQueueContext';
import {useDelete} from '../features/file-browser/useDelete';
import type {UseDeleteResult} from '../features/file-browser/useDelete';
import {useMove} from '../features/file-browser/useMove';
import type {UseMoveResult} from '../features/file-browser/useMove';
import {useCopy} from '../features/file-browser/useCopy';
import type {UseCopyResult} from '../features/file-browser/useCopy';

// The page shell is rendered with the real FileBrowser populated with content
// (folders + files), exercising the authenticated browser's a11y at route level.
// The data/action hooks are stubbed exactly as in FileBrowser.test.tsx so no live
// AWS / QueryClient is needed.
vi.mock('../features/auth', () => ({
  useAuth: () => ({user: {username: 'alice'}, status: 'authenticated'})
}));
vi.mock('../hooks/usePageTitle', () => ({usePageTitle: vi.fn()}));
vi.mock('../components/Sidebar', () => ({
  Sidebar: () => <nav aria-label="Your spaces" />
}));
vi.mock('../features/file-browser/useFileBrowser');
vi.mock('../features/file-browser/useFileUpload');
vi.mock('../features/file-browser/useDelete');
vi.mock('../features/file-browser/useMove');
vi.mock('../features/file-browser/useCopy');
vi.mock('../features/file-browser/uploadQueueContext', () => ({
  useUploadQueue: vi.fn()
}));
vi.mock('../features/file-browser/UploadQueueProvider', () => ({
  UploadQueueProvider: ({children}: {children: ReactNode}) => children
}));
vi.mock('../features/file-browser/UploadQueuePanel', () => ({
  UploadQueuePanel: () => null
}));
vi.mock('../features/file-browser/fileBrowser.service', () => ({
  ensurePrefixMarker: vi.fn().mockResolvedValue({success: true}),
  getDownloadUrl: vi.fn()
}));

vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
const {default: FilesPage} = await import('./FilesPage');

const mockUseFileBrowser = vi.mocked(useFileBrowser);

const browserContent: UseFileBrowserResult = {
  files: [
    {
      type: 'file',
      key: 'alice/report.pdf',
      name: 'report.pdf',
      size: 1024,
      lastModified: new Date('2024-01-01')
    },
    {
      type: 'file',
      key: 'alice/data.csv',
      name: 'data.csv',
      size: 2048,
      lastModified: new Date('2024-02-01')
    }
  ],
  folders: [{type: 'folder', prefix: 'alice/photos/', name: 'photos'}],
  isLoading: false,
  error: null,
  refresh: vi.fn(),
  hasMore: false,
  loadMore: vi.fn(),
  isLoadingMore: false
};

const uploadBase: UseFileUploadResult = {
  progress: null,
  pendingCollision: null,
  error: null,
  isBusy: false,
  uploadOne: vi.fn(),
  createNewFolder: vi.fn(),
  cancelCollision: vi.fn(),
  dismissError: vi.fn()
};

const uploadQueueBase: UploadQueueContextValue = {
  items: [],
  enqueue: vi.fn(),
  cancel: vi.fn(),
  dismiss: vi.fn(),
  resolveOverwrite: vi.fn(),
  resolveRename: vi.fn(),
  clearFinished: vi.fn()
};

const deleteBase: UseDeleteResult = {
  isDeleting: false,
  summary: null,
  error: null,
  runDelete: vi.fn().mockResolvedValue({deletedCount: 0, errors: []}),
  dismissSummary: vi.fn(),
  dismissError: vi.fn()
};

const moveBase: UseMoveResult = {
  isBusy: false,
  progress: null,
  error: null,
  summary: null,
  renameCollision: null,
  moveCollision: null,
  renameItem: vi.fn(),
  moveItems: vi.fn(),
  dismissError: vi.fn(),
  dismissSummary: vi.fn(),
  cancelCollision: vi.fn()
};

const copyBase: UseCopyResult = {
  isBusy: false,
  progress: null,
  error: null,
  summary: null,
  copyCollision: null,
  sameFolderPrompt: null,
  copyItems: vi.fn(),
  dismissError: vi.fn(),
  dismissSummary: vi.fn(),
  cancelCollision: vi.fn()
};

beforeEach(() => {
  vi.clearAllMocks();
  mockUseFileBrowser.mockReturnValue(browserContent);
  vi.mocked(useFileUpload).mockReturnValue(uploadBase);
  vi.mocked(useUploadQueue).mockReturnValue(uploadQueueBase);
  vi.mocked(useDelete).mockReturnValue(deleteBase);
  vi.mocked(useMove).mockReturnValue(moveBase);
  vi.mocked(useCopy).mockReturnValue(copyBase);
});

const tree = (
  <MemoryRouter initialEntries={['/files']}>
    <FilesPage />
  </MemoryRouter>
);

describe('FilesPage accessibility (SPEC-045 FR-003)', () => {
  it('has no axe violations with folders + files present', async () => {
    await expectNoA11yViolations(tree, ROUTE_AXE_OPTIONS);
  });

  it('exposes exactly one <h1> and a <main> landmark', () => {
    render(tree);
    expect(screen.getAllByRole('heading', {level: 1})).toHaveLength(1);
    expect(screen.getByRole('main')).toBeInTheDocument();
    // Content is actually present (guards the "with content" requirement).
    expect(screen.getByText('report.pdf')).toBeInTheDocument();
    expect(screen.getByText('photos')).toBeInTheDocument();
  });
});
