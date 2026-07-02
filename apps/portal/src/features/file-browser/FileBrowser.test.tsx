import {render, screen, fireEvent, within, waitFor} from '@testing-library/react';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {FileBrowser} from './FileBrowser';
import {useFileBrowser} from './useFileBrowser';
import type {UseFileBrowserResult} from './useFileBrowser';
import {getDownloadUrl} from './fileBrowser.service';
import {useFileUpload} from './useFileUpload';
import type {UseFileUploadResult} from './useFileUpload';
import {useUploadQueue} from './uploadQueueContext';
import type {UploadQueueContextValue} from './uploadQueueContext';
import {useDelete} from './useDelete';
import type {UseDeleteResult} from './useDelete';
import {useMove} from './useMove';
import type {UseMoveResult} from './useMove';
import {useCopy} from './useCopy';
import type {UseCopyResult} from './useCopy';

vi.mock('./useFileBrowser');
vi.mock('./fileBrowser.service');
vi.mock('./useFileUpload');
vi.mock('./useDelete');
vi.mock('./useMove');
vi.mock('./useCopy');
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn(() => Promise.resolve({success: true, data: {}}))
}));
// The upload queue is exercised in UploadQueueProvider.test.tsx; here the hook is
// stubbed and the in-drawer uploads list is a no-op so these tests stay focused on
// FileBrowser wiring (and don't need a QueryClient). The provider lives at the app
// shell, so FileBrowser does not render it.
vi.mock('./uploadQueueContext', () => ({useUploadQueue: vi.fn()}));
vi.mock('./UploadList', () => ({UploadList: () => null}));
// Stub the move dialog's folder picker so these tests don't pull in useFileBrowser
// twice; MoveDialog itself is covered by MoveDialog.test.tsx.
vi.mock('./MoveDialog', () => ({
  MoveDialog: ({
    items,
    onMove,
    onCancel
  }: {
    items: {type: string}[];
    onMove: (destPrefix: string, destBucket: string) => void;
    onCancel: () => void;
  }) => (
    <div
      role="dialog"
      aria-label="Move to folder">
      <span>moving {items.length}</span>
      <button onClick={() => onMove('alice/dest/', 'my-bucket')}>move-here-stub</button>
      <button onClick={onCancel}>move-cancel-stub</button>
    </div>
  )
}));
// Stub the copy dialog's folder picker (the real picker + same-folder prompt are
// covered by CopyDialog.test.tsx / DestinationPicker reuse). The stub exposes a
// different-folder copy and a same-folder copy (current parent) so the wiring to
// useCopy is exercised here.
vi.mock('./CopyDialog', () => ({
  CopyDialog: ({
    items,
    currentPrefix,
    onCopy,
    onCancel
  }: {
    items: {type: string}[];
    currentPrefix: string;
    onCopy: (destPrefix: string, destBucket: string) => void;
    onCancel: () => void;
  }) => (
    <div
      role="dialog"
      aria-label="Copy to folder">
      <span>copying {items.length}</span>
      <button onClick={() => onCopy('alice/dest/', 'my-bucket')}>copy-here-stub</button>
      <button onClick={() => onCopy(currentPrefix, 'my-bucket')}>copy-same-folder-stub</button>
      <button onClick={onCancel}>copy-cancel-stub</button>
    </div>
  )
}));
// Stub the rename dialog — its validation uses validateFolderName, which is
// auto-mocked by the wholesale ./fileBrowser.service mock below. The real dialog
// (and its validation) is covered by RenameDialog.test.tsx.
vi.mock('./RenameDialog', () => ({
  RenameDialog: ({
    currentName,
    onRename,
    onCancel
  }: {
    currentName: string;
    onRename: (newName: string) => void;
    onCancel: () => void;
  }) => (
    <div
      role="dialog"
      aria-label="Rename">
      <span>renaming {currentName}</span>
      <button onClick={() => onRename('renamed')}>rename-submit-stub</button>
      <button onClick={onCancel}>rename-cancel-stub</button>
    </div>
  )
}));
// Stub the metadata drawer so these tests don't pull in its TanStack Query hook
// (covered by MetadataPanel.test.tsx). The stub echoes the file it was opened for.
vi.mock('./MetadataPanel', () => ({
  MetadataPanel: ({file, onClose}: {file: {name: string}; onClose: () => void}) => (
    <div
      role="dialog"
      aria-label={`Details for ${file.name}`}>
      <button onClick={onClose}>close-stub</button>
    </div>
  )
}));
// Folder details drawer stub — echoes the folder it was opened for.
vi.mock('./FolderDetailsPanel', () => ({
  FolderDetailsPanel: ({folder, onClose}: {folder: {name: string}; onClose: () => void}) => (
    <div
      role="dialog"
      aria-label={`Details for ${folder.name}`}>
      <button onClick={onClose}>close-folder-stub</button>
    </div>
  )
}));

const mockUseFileBrowser = vi.mocked(useFileBrowser);
const mockGetDownloadUrl = vi.mocked(getDownloadUrl);
const mockUseFileUpload = vi.mocked(useFileUpload);
const mockUseUploadQueue = vi.mocked(useUploadQueue);
const mockUseDelete = vi.mocked(useDelete);
const mockUseMove = vi.mocked(useMove);
const mockUseCopy = vi.mocked(useCopy);

const base: UseFileBrowserResult = {
  files: [],
  folders: [],
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

// A file + folder fixture used by the selection/delete tests. The delete UI is
// only offered when both `writable` and `username` are set (authenticated flow).
const oneFile = {
  type: 'file' as const,
  key: 'alice/report.pdf',
  name: 'report.pdf',
  size: 1024,
  lastModified: new Date('2024-01-01')
};
const oneFolder = {type: 'folder' as const, prefix: 'alice/photos/', name: 'photos'};

beforeEach(() => {
  vi.clearAllMocks();
  mockUseFileBrowser.mockReturnValue(base);
  mockUseFileUpload.mockReturnValue(uploadBase);
  mockUseUploadQueue.mockReturnValue(uploadQueueBase);
  mockUseDelete.mockReturnValue(deleteBase);
  mockUseMove.mockReturnValue(moveBase);
  mockUseCopy.mockReturnValue(copyBase);
});

// ─── Loading ──────────────────────────────────────────────────────────────────

describe('loading state', () => {
  it('shows a loading indicator when isLoading is true', () => {
    mockUseFileBrowser.mockReturnValue({...base, isLoading: true});
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.getByRole('status', {name: /loading/i})).toBeInTheDocument();
  });

  it('hides file content while loading', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      isLoading: true,
      files: [
        {
          type: 'file',
          key: 'secret.txt',
          name: 'secret.txt',
          size: 100,
          lastModified: new Date()
        }
      ]
    });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.queryByText('secret.txt')).not.toBeInTheDocument();
  });
});

// ─── Error ────────────────────────────────────────────────────────────────────

describe('error state', () => {
  it('shows an alert with the error message', () => {
    mockUseFileBrowser.mockReturnValue({...base, error: 'Access Denied'});
    render(<FileBrowser bucket="my-bucket" />);
    const alert = screen.getByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent('Access Denied');
  });

  it('offers a "Refresh access" affordance for a just-added shared space (list-denied)', async () => {
    const refresh = vi.fn();
    mockUseFileBrowser.mockReturnValue({
      ...base,
      error: 'User ... is not authorized to perform: s3:ListBucket on dat-prod-shared-space',
      refresh
    });
    const {getSessionCredentials} = await import('../../lib/awsCredentials');
    render(
      <FileBrowser
        bucket="dat-prod-shared-space"
        spaceKind="shared"
      />
    );
    // The raw IAM error is replaced by the "applying access" affordance, not a dead end.
    expect(screen.getByText(/you were just added to this space/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: /refresh access/i}));
    expect(getSessionCredentials).toHaveBeenCalledWith(true);
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it('shows the raw error (no affordance) for a personal-space failure', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      error: 'User ... is not authorized to perform: s3:ListBucket'
    });
    render(
      <FileBrowser
        bucket="dat-prod-user-space"
        spaceKind="personal"
      />
    );
    expect(screen.getByText(/failed to load files/i)).toBeInTheDocument();
    expect(screen.queryByText(/you were just added/i)).not.toBeInTheDocument();
  });
});

// ─── Empty ────────────────────────────────────────────────────────────────────

describe('empty state', () => {
  it('shows an empty-folder message when there are no files or folders', () => {
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.getByText(/this folder is empty/i)).toBeInTheDocument();
  });
});

// ─── Populated ───────────────────────────────────────────────────────────────

describe('populated state', () => {
  it('renders folder names', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [{type: 'folder', prefix: 'docs/', name: 'docs'}]
    });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.getByText('docs')).toBeInTheDocument();
  });

  it('renders file names', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      files: [
        {
          type: 'file',
          key: 'readme.md',
          name: 'readme.md',
          size: 512,
          lastModified: new Date()
        }
      ]
    });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.getByText('readme.md')).toBeInTheDocument();
  });

  it('formats file size as human-readable', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      files: [
        {
          type: 'file',
          key: 'data.bin',
          name: 'data.bin',
          size: 1_536,
          lastModified: new Date()
        }
      ]
    });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.getByText('1.5 KB')).toBeInTheDocument();
  });

  it('shows the file last-modified year', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      files: [
        {
          type: 'file',
          key: 'report.pdf',
          name: 'report.pdf',
          size: 0,
          lastModified: new Date('2024-06-15T00:00:00Z')
        }
      ]
    });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.getByText(/2024/)).toBeInTheDocument();
  });

  it('renders folders before files', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [{type: 'folder', prefix: 'archive/', name: 'archive'}],
      files: [
        {
          type: 'file',
          key: 'notes.txt',
          name: 'notes.txt',
          size: 10,
          lastModified: new Date()
        }
      ]
    });
    render(<FileBrowser bucket="my-bucket" />);
    const list = screen.getByRole('list', {name: /file list/i});
    const items = within(list).getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('archive');
    expect(items[1]).toHaveTextContent('notes.txt');
  });
});

// ─── Navigation ───────────────────────────────────────────────────────────────

describe('folder drill-down', () => {
  it('clicking a folder passes its prefix to the hook', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [{type: 'folder', prefix: 'photos/', name: 'photos'}]
    });
    render(<FileBrowser bucket="my-bucket" />);

    fireEvent.click(screen.getByRole('button', {name: /open folder photos/i}));

    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('my-bucket', 'photos/', undefined);
  });
});

// ─── Root prefix clamping ─────────────────────────────────────────────────────

describe('root prefix clamping', () => {
  it('shows the root prefix folder name instead of Home when rootPrefix is set', () => {
    render(
      <FileBrowser
        bucket="my-bucket"
        prefix="project-alpha/"
        rootPrefix="project-alpha/"
      />
    );
    const nav = screen.getByRole('navigation', {name: /breadcrumb/i});
    expect(nav).toHaveTextContent('project-alpha');
    expect(within(nav).queryByText('Home')).not.toBeInTheDocument();
    // At root prefix the root crumb is aria-current="page", not a button
    expect(within(nav).queryByRole('button', {name: 'project-alpha'})).not.toBeInTheDocument();
  });

  it('uses rootLabel for the root crumb, hiding the raw prefix segment (SPEC-013)', () => {
    // The username is the navigation floor but must never be shown to the user.
    render(
      <FileBrowser
        bucket="my-bucket"
        prefix="alice/"
        rootPrefix="alice/"
        rootLabel="My Files"
      />
    );
    const nav = screen.getByRole('navigation', {name: /breadcrumb/i});
    expect(within(nav).getByText('My Files')).toBeInTheDocument();
    expect(within(nav).queryByText('alice')).not.toBeInTheDocument();
  });

  it('keeps showing the username segment as the floor label when browsing deeper, still hidden', () => {
    mockUseFileBrowser.mockImplementation((_bucket, prefix) => ({
      ...base,
      folders: prefix === 'alice/' ? [{type: 'folder', prefix: 'alice/docs/', name: 'docs'}] : []
    }));
    render(
      <FileBrowser
        bucket="my-bucket"
        prefix="alice/"
        rootPrefix="alice/"
        rootLabel="My Files"
      />
    );

    fireEvent.click(screen.getByRole('button', {name: /open folder docs/i}));

    const nav = screen.getByRole('navigation', {name: /breadcrumb/i});
    expect(within(nav).getByRole('button', {name: 'My Files'})).toBeInTheDocument();
    expect(within(nav).queryByText('alice')).not.toBeInTheDocument();
    expect(within(nav).getByText('docs')).toHaveAttribute('aria-current', 'page');
  });

  it('does not show path segments above rootPrefix when browsing deeper', () => {
    mockUseFileBrowser.mockImplementation((_bucket, prefix) => ({
      ...base,
      folders: prefix === 'project-alpha/' ? [{type: 'folder', prefix: 'project-alpha/docs/', name: 'docs'}] : []
    }));
    render(
      <FileBrowser
        bucket="my-bucket"
        prefix="project-alpha/"
        rootPrefix="project-alpha/"
      />
    );

    fireEvent.click(screen.getByRole('button', {name: /open folder docs/i}));

    const nav = screen.getByRole('navigation', {name: /breadcrumb/i});
    expect(within(nav).queryByText('Home')).not.toBeInTheDocument();
    expect(within(nav).getByRole('button', {name: 'project-alpha'})).toBeInTheDocument();
    expect(within(nav).getByText('docs')).toHaveAttribute('aria-current', 'page');
  });

  it('clicking the root prefix crumb navigates to rootPrefix not bucket root', () => {
    mockUseFileBrowser.mockImplementation((_bucket, prefix) => ({
      ...base,
      folders: prefix === 'project-alpha/' ? [{type: 'folder', prefix: 'project-alpha/docs/', name: 'docs'}] : []
    }));
    render(
      <FileBrowser
        bucket="my-bucket"
        prefix="project-alpha/"
        rootPrefix="project-alpha/"
      />
    );

    fireEvent.click(screen.getByRole('button', {name: /open folder docs/i}));
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('my-bucket', 'project-alpha/docs/', undefined);

    const nav = screen.getByRole('navigation', {name: /breadcrumb/i});
    fireEvent.click(within(nav).getByRole('button', {name: 'project-alpha'}));
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('my-bucket', 'project-alpha/', undefined);
  });
});

// ─── Breadcrumb ───────────────────────────────────────────────────────────────

describe('breadcrumb', () => {
  it('shows only "Home" at the root level', () => {
    render(<FileBrowser bucket="my-bucket" />);
    const nav = screen.getByRole('navigation', {name: /breadcrumb/i});
    expect(nav).toHaveTextContent('Home');
    // Home is aria-current="page" at root, not a button
    expect(within(nav).queryByRole('button', {name: 'Home'})).not.toBeInTheDocument();
  });

  it('updates to show the folder name after drilling in', () => {
    mockUseFileBrowser.mockImplementation((_bucket, prefix) => ({
      ...base,
      folders: prefix === undefined ? [{type: 'folder', prefix: 'reports/', name: 'reports'}] : []
    }));
    render(<FileBrowser bucket="my-bucket" />);

    fireEvent.click(screen.getByRole('button', {name: /open folder reports/i}));

    const nav = screen.getByRole('navigation', {name: /breadcrumb/i});
    expect(nav).toHaveTextContent('Home');
    expect(within(nav).getByText('reports')).toHaveAttribute('aria-current', 'page');
    expect(within(nav).getByRole('button', {name: 'Home'})).toBeInTheDocument();
  });

  it('clicking an ancestor crumb navigates back up', () => {
    mockUseFileBrowser.mockImplementation((_bucket, prefix) => ({
      ...base,
      folders: prefix === undefined ? [{type: 'folder', prefix: 'archive/', name: 'archive'}] : []
    }));
    render(<FileBrowser bucket="my-bucket" />);

    fireEvent.click(screen.getByRole('button', {name: /open folder archive/i}));
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('my-bucket', 'archive/', undefined);

    const nav = screen.getByRole('navigation', {name: /breadcrumb/i});
    fireEvent.click(within(nav).getByRole('button', {name: 'Home'}));
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('my-bucket', undefined, undefined);
  });

  it('builds multi-level breadcrumbs for nested prefixes', () => {
    mockUseFileBrowser.mockImplementation((_bucket, prefix) => ({
      ...base,
      folders:
        prefix === 'docs/'
          ? [{type: 'folder', prefix: 'docs/2024/', name: '2024'}]
          : prefix === undefined
            ? [{type: 'folder', prefix: 'docs/', name: 'docs'}]
            : []
    }));
    render(<FileBrowser bucket="my-bucket" />);

    fireEvent.click(screen.getByRole('button', {name: /open folder docs/i}));
    fireEvent.click(screen.getByRole('button', {name: /open folder 2024/i}));

    const nav = screen.getByRole('navigation', {name: /breadcrumb/i});
    expect(nav).toHaveTextContent('Home');
    expect(nav).toHaveTextContent('docs');
    expect(within(nav).getByText('2024')).toHaveAttribute('aria-current', 'page');
  });
});

// ─── Load more (pagination) ────────────────────────────────────────────────────

describe('load more', () => {
  const withFile = {
    ...base,
    files: [
      {
        type: 'file' as const,
        key: 'a.txt',
        name: 'a.txt',
        size: 1,
        lastModified: new Date('2024-01-01')
      }
    ]
  };

  it('shows "Load more" only when hasMore is true', () => {
    mockUseFileBrowser.mockReturnValue({...withFile, hasMore: true});
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.getByRole('button', {name: /load more/i})).toBeInTheDocument();
  });

  it('hides "Load more" when fully loaded', () => {
    mockUseFileBrowser.mockReturnValue({...withFile, hasMore: false});
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.queryByRole('button', {name: /load more/i})).not.toBeInTheDocument();
  });

  it('calls loadMore when clicked', () => {
    const loadMore = vi.fn();
    mockUseFileBrowser.mockReturnValue({...withFile, hasMore: true, loadMore});
    render(<FileBrowser bucket="my-bucket" />);
    fireEvent.click(screen.getByRole('button', {name: /load more/i}));
    expect(loadMore).toHaveBeenCalledOnce();
  });

  it('disables the control while a page is loading', () => {
    mockUseFileBrowser.mockReturnValue({
      ...withFile,
      hasMore: true,
      isLoadingMore: true
    });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.getByRole('button', {name: /loading/i})).toBeDisabled();
  });
});

// ─── Download ─────────────────────────────────────────────────────────────────

describe('download', () => {
  const fileItem = {
    type: 'file' as const,
    key: 'alice/docs/report.pdf',
    name: 'report.pdf',
    size: 1024,
    lastModified: new Date('2024-01-01')
  };

  beforeEach(() => {
    mockUseFileBrowser.mockReturnValue({...base, files: [fileItem]});
  });

  it('exposes a Download action per file', () => {
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.getByRole('button', {name: /download report\.pdf/i})).toBeInTheDocument();
  });

  it('folders expose no Download action', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [{type: 'folder', prefix: 'docs/', name: 'docs'}]
    });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.queryByRole('button', {name: /download/i})).not.toBeInTheDocument();
  });

  it('requests a presigned URL and triggers the browser download on success', async () => {
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    mockGetDownloadUrl.mockResolvedValue({
      success: true,
      data: {url: 'https://signed.example/report.pdf', expiresAt: '2026-01-01T00:00:00Z'}
    });

    render(<FileBrowser bucket="my-bucket" />);
    fireEvent.click(screen.getByRole('button', {name: /download report\.pdf/i}));

    await waitFor(() => expect(clickSpy).toHaveBeenCalledOnce());
    expect(mockGetDownloadUrl).toHaveBeenCalledWith({
      bucket: 'my-bucket',
      key: 'alice/docs/report.pdf',
      fileName: 'report.pdf'
    });
    clickSpy.mockRestore();
  });

  it('surfaces a download error inline without throwing', async () => {
    mockGetDownloadUrl.mockResolvedValue({
      success: false,
      error: {message: 'No AWS credentials — sign in required'}
    });

    render(<FileBrowser bucket="my-bucket" />);
    fireEvent.click(screen.getByRole('button', {name: /download report\.pdf/i}));

    expect(await screen.findByText(/could not download report\.pdf/i)).toBeInTheDocument();
  });
});

// ─── Details / metadata panel ───────────────────────────────────────────────────

describe('details panel', () => {
  const fileItem = {
    type: 'file' as const,
    key: 'alice/docs/report.pdf',
    name: 'report.pdf',
    size: 1024,
    lastModified: new Date('2024-01-01')
  };

  it('exposes a Details action per file', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [fileItem]});
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.getByRole('button', {name: /details for report\.pdf/i})).toBeInTheDocument();
  });

  it('exposes a Details action per folder', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [{type: 'folder', prefix: 'docs/', name: 'docs'}]
    });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.getByRole('button', {name: /details for docs/i})).toBeInTheDocument();
  });

  it('opens the folder details drawer when a folder Details is clicked', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [{type: 'folder', prefix: 'docs/', name: 'docs'}]
    });
    render(<FileBrowser bucket="my-bucket" />);

    expect(screen.queryByRole('dialog', {name: /details for docs/i})).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: /details for docs/i}));

    expect(screen.getByRole('dialog', {name: /details for docs/i})).toBeInTheDocument();
  });

  it('opens the metadata drawer for the file when Details is clicked', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [fileItem]});
    render(<FileBrowser bucket="my-bucket" />);

    expect(screen.queryByRole('dialog', {name: /details for report\.pdf/i})).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: /details for report\.pdf/i}));

    expect(screen.getByRole('dialog', {name: /details for report\.pdf/i})).toBeInTheDocument();
  });

  it('closes the drawer when the panel requests close', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [fileItem]});
    render(<FileBrowser bucket="my-bucket" />);

    fireEvent.click(screen.getByRole('button', {name: /details for report\.pdf/i}));
    fireEvent.click(screen.getByRole('button', {name: /close-stub/i}));

    expect(screen.queryByRole('dialog', {name: /details for report\.pdf/i})).not.toBeInTheDocument();
  });
});

// ─── Write controls gating ──────────────────────────────────────────────────────

describe('write controls', () => {
  it('are hidden when not writable (read-only / dev-unauth)', () => {
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.queryByRole('button', {name: /new folder/i})).not.toBeInTheDocument();
    expect(screen.queryByText(/choose files/i)).not.toBeInTheDocument();
  });

  it('shows New folder + Upload buttons when writable; the dropzone opens in a drawer', () => {
    render(
      <FileBrowser
        bucket="my-bucket"
        writable
      />
    );
    expect(screen.getByRole('button', {name: /new folder/i})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: /^upload$/i})).toBeInTheDocument();

    // The dropzone lives in a drawer that is closed until Upload is clicked.
    expect(screen.queryByText(/choose files/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: /^upload$/i}));
    expect(screen.getByText(/choose files/i)).toBeInTheDocument();
  });

  it('enqueues selected files onto the upload queue (SPEC-020)', () => {
    render(
      <FileBrowser
        bucket="my-bucket"
        writable
      />
    );
    fireEvent.click(screen.getByRole('button', {name: /^upload$/i}));

    const input = screen.getByLabelText(/choose files/i);
    const f1 = new File(['a'], 'a.txt');
    const f2 = new File(['b'], 'b.txt');
    fireEvent.change(input, {target: {files: [f1, f2]}});

    expect(uploadQueueBase.enqueue).toHaveBeenCalledWith([f1, f2], {bucket: 'my-bucket', prefix: ''});
  });
});

// ─── Selection + delete ─────────────────────────────────────────────────────────

describe('selection + delete', () => {
  const authProps = {bucket: 'my-bucket', writable: true, username: 'alice'} as const;

  it('shows no selection checkboxes when not writable (read-only)', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('shows no selection checkboxes when writable but unauthenticated (no username)', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    render(
      <FileBrowser
        bucket="my-bucket"
        writable
      />
    );
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('renders per-row + select-all checkboxes in the authenticated writable flow', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      files: [oneFile],
      folders: [oneFolder]
    });
    render(<FileBrowser {...authProps} />);
    expect(screen.getByRole('checkbox', {name: /select all/i})).toBeInTheDocument();
    expect(screen.getByRole('checkbox', {name: /select report\.pdf/i})).toBeInTheDocument();
    expect(screen.getByRole('checkbox', {name: /select folder photos/i})).toBeInTheDocument();
  });

  it('disables Delete until something is selected', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    render(<FileBrowser {...authProps} />);

    expect(screen.getByRole('button', {name: 'Delete selected items'})).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', {name: /select report\.pdf/i}));
    expect(screen.getByRole('button', {name: 'Delete selected items'})).toBeEnabled();
  });

  it('select-all toggles every row', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      files: [oneFile],
      folders: [oneFolder]
    });
    render(<FileBrowser {...authProps} />);

    fireEvent.click(screen.getByRole('checkbox', {name: /select all/i}));
    expect(screen.getByRole('checkbox', {name: /select report\.pdf/i})).toBeChecked();
    expect(screen.getByRole('checkbox', {name: /select folder photos/i})).toBeChecked();
  });

  it('opens a confirmation naming the item and deletes nothing until confirmed', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    render(<FileBrowser {...authProps} />);

    fireEvent.click(screen.getByRole('checkbox', {name: /select report\.pdf/i}));
    fireEvent.click(screen.getByRole('button', {name: 'Delete selected items'}));

    const dialog = screen.getByRole('alertdialog', {name: /confirm delete/i});
    expect(dialog).toHaveTextContent(/report\.pdf/);
    expect(dialog).toHaveTextContent(/can.t be undone/i);
    expect(deleteBase.runDelete).not.toHaveBeenCalled();
  });

  it('confirming deletes exactly the selected files and folders', async () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      files: [oneFile],
      folders: [oneFolder]
    });
    render(<FileBrowser {...authProps} />);

    fireEvent.click(screen.getByRole('checkbox', {name: /select report\.pdf/i}));
    fireEvent.click(screen.getByRole('checkbox', {name: /select folder photos/i}));
    fireEvent.click(screen.getByRole('button', {name: 'Delete selected items'}));

    const dialog = screen.getByRole('alertdialog', {name: /confirm delete/i});
    fireEvent.click(within(dialog).getByRole('button', {name: /^delete$/i}));

    await waitFor(() => expect(deleteBase.runDelete).toHaveBeenCalledTimes(1));
    const items = vi.mocked(deleteBase.runDelete).mock.calls[0][0];
    expect(items).toEqual(
      expect.arrayContaining([
        {type: 'file', key: 'alice/report.pdf'},
        {type: 'folder', prefix: 'alice/photos/'}
      ])
    );
    expect(items).toHaveLength(2);
  });

  it('cancelling the confirmation deletes nothing and closes the dialog', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    render(<FileBrowser {...authProps} />);

    fireEvent.click(screen.getByRole('checkbox', {name: /select report\.pdf/i}));
    fireEvent.click(screen.getByRole('button', {name: 'Delete selected items'}));

    const dialog = screen.getByRole('alertdialog', {name: /confirm delete/i});
    fireEvent.click(within(dialog).getByRole('button', {name: /cancel/i}));

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(deleteBase.runDelete).not.toHaveBeenCalled();
  });

  it('shows a success summary with the deleted count', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    mockUseDelete.mockReturnValue({
      ...deleteBase,
      summary: {deletedCount: 3, errors: []}
    });
    render(<FileBrowser {...authProps} />);

    expect(screen.getByRole('status')).toHaveTextContent(/deleted 3 items/i);
  });

  it('shows a partial-failure summary listing what failed and why', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    mockUseDelete.mockReturnValue({
      ...deleteBase,
      summary: {
        deletedCount: 1,
        errors: [{key: 'alice/locked.txt', message: 'Access Denied'}]
      }
    });
    render(<FileBrowser {...authProps} />);

    expect(screen.getByText(/could not delete 1/i)).toBeInTheDocument();
    expect(screen.getByText(/locked\.txt — access denied/i)).toBeInTheDocument();
  });
});

// ─── Rename + move ──────────────────────────────────────────────────────────────

describe('rename + move', () => {
  const authProps = {bucket: 'my-bucket', writable: true, username: 'alice'} as const;

  it('shows no Rename action when read-only', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.queryByRole('button', {name: /rename/i})).not.toBeInTheDocument();
  });

  it('enables toolbar Rename only for a single selected item (file or folder)', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      files: [oneFile],
      folders: [oneFolder]
    });
    render(<FileBrowser {...authProps} />);

    expect(screen.getByRole('button', {name: 'Rename selected item'})).toBeDisabled();

    fireEvent.click(screen.getByRole('checkbox', {name: /select report\.pdf/i}));
    expect(screen.getByRole('button', {name: 'Rename selected item'})).toBeEnabled();

    fireEvent.click(screen.getByRole('checkbox', {name: /select folder photos/i}));
    expect(screen.getByRole('button', {name: 'Rename selected item'})).toBeDisabled();
  });

  it('toolbar Rename opens the dialog and calls renameItem on submit', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    render(<FileBrowser {...authProps} />);

    fireEvent.click(screen.getByRole('checkbox', {name: /select report\.pdf/i}));
    fireEvent.click(screen.getByRole('button', {name: 'Rename selected item'}));
    const dialog = screen.getByRole('dialog', {name: /rename/i});
    fireEvent.click(within(dialog).getByRole('button', {name: /rename-submit-stub/i}));

    expect(moveBase.renameItem).toHaveBeenCalledWith({type: 'file', key: 'alice/report.pdf'}, 'renamed');

    // The renamed item's key changes, so a stale selection would linger as a ghost;
    // rename clears the selection, leaving Rename disabled and the box unchecked.
    expect(screen.getByRole('button', {name: 'Rename selected item'})).toBeDisabled();
    expect(screen.getByRole('checkbox', {name: /select report\.pdf/i})).not.toBeChecked();
  });

  it('does not render per-row Rename buttons (actions live in the toolbar)', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      files: [oneFile],
      folders: [oneFolder]
    });
    render(<FileBrowser {...authProps} />);
    expect(screen.queryByRole('button', {name: /rename report\.pdf/i})).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /rename folder photos/i})).not.toBeInTheDocument();
  });

  it('disables Move until something is selected', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    render(<FileBrowser {...authProps} />);
    expect(screen.getByRole('button', {name: 'Move selected items'})).toBeDisabled();
  });

  it('Move opens the destination picker and calls moveItems on confirm', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile], folders: [oneFolder]});
    render(<FileBrowser {...authProps} />);

    fireEvent.click(screen.getByRole('checkbox', {name: /select report\.pdf/i}));
    fireEvent.click(screen.getByRole('button', {name: 'Move selected items'}));

    const dialog = screen.getByRole('dialog', {name: /move to folder/i});
    expect(dialog).toHaveTextContent(/moving 1/i);
    fireEvent.click(within(dialog).getByRole('button', {name: /move-here-stub/i}));

    expect(moveBase.moveItems).toHaveBeenCalledWith(
      [{type: 'file', key: 'alice/report.pdf'}],
      'alice/dest/',
      'my-bucket'
    );
  });

  it('shows a move result summary with the moved count', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    mockUseMove.mockReturnValue({
      ...moveBase,
      summary: {movedCount: 2, errors: []}
    });
    render(<FileBrowser {...authProps} />);
    expect(screen.getByText(/moved 2 items/i)).toBeInTheDocument();
  });

  it('renders the rename-collision prompt from the move hook', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    mockUseMove.mockReturnValue({
      ...moveBase,
      renameCollision: {
        kind: 'file',
        label: 'taken.pdf',
        onOverwrite: vi.fn(),
        onRename: vi.fn(),
        onCancel: vi.fn()
      }
    });
    render(<FileBrowser {...authProps} />);
    expect(screen.getByRole('alertdialog', {name: /already exists/i})).toBeInTheDocument();
  });
});

// ─── Copy ───────────────────────────────────────────────────────────────────────

describe('copy', () => {
  const authProps = {bucket: 'my-bucket', writable: true, username: 'alice'} as const;

  it('shows no Copy action when read-only', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.queryByRole('button', {name: /copy/i})).not.toBeInTheDocument();
  });

  it('disables the selection-bar Copy until something is selected', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    render(<FileBrowser {...authProps} />);
    expect(screen.getByRole('button', {name: 'Copy selected items'})).toBeDisabled();
  });

  it('does not render per-row Copy buttons (actions live in the toolbar)', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      files: [oneFile],
      folders: [oneFolder]
    });
    render(<FileBrowser {...authProps} />);
    expect(screen.queryByRole('button', {name: /copy report\.pdf/i})).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /copy folder photos/i})).not.toBeInTheDocument();
  });

  it('selection-bar Copy copies the selected items', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      files: [oneFile],
      folders: [oneFolder]
    });
    render(<FileBrowser {...authProps} />);

    fireEvent.click(screen.getByRole('checkbox', {name: /select report\.pdf/i}));
    fireEvent.click(screen.getByRole('button', {name: 'Copy selected items'}));

    const dialog = screen.getByRole('dialog', {name: /copy to folder/i});
    fireEvent.click(within(dialog).getByRole('button', {name: /copy-here-stub/i}));

    expect(copyBase.copyItems).toHaveBeenCalledWith(
      [{type: 'file', key: 'alice/report.pdf'}],
      'alice/dest/',
      'my-bucket'
    );
  });

  it('keeps the copy dialog open for a same-folder copy (auto-number flow)', () => {
    // Current parent is "alice/"; a same-folder copy passes that current parent.
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    render(
      <FileBrowser
        {...authProps}
        prefix="alice/"
      />
    );

    fireEvent.click(screen.getByRole('checkbox', {name: /select report\.pdf/i}));
    fireEvent.click(screen.getByRole('button', {name: 'Copy selected items'}));
    const dialog = screen.getByRole('dialog', {name: /copy to folder/i});
    fireEvent.click(within(dialog).getByRole('button', {name: /copy-same-folder-stub/i}));

    // copyItems is called with the current parent, and the dialog stays open so the
    // same-folder editable-name prompt (rendered by the real CopyDialog) can show.
    expect(copyBase.copyItems).toHaveBeenCalledWith([{type: 'file', key: 'alice/report.pdf'}], 'alice/', 'my-bucket');
    expect(screen.getByRole('dialog', {name: /copy to folder/i})).toBeInTheDocument();
  });

  it('shows a copy result summary with the copied count', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    mockUseCopy.mockReturnValue({
      ...copyBase,
      summary: {copiedCount: 2, errors: []}
    });
    render(<FileBrowser {...authProps} />);
    expect(screen.getByText(/copied 2 items/i)).toBeInTheDocument();
  });

  it('shows a partial-failure copy summary listing what failed', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    mockUseCopy.mockReturnValue({
      ...copyBase,
      summary: {
        copiedCount: 1,
        errors: [{item: 'alice/locked.txt', message: 'Access Denied'}]
      }
    });
    render(<FileBrowser {...authProps} />);
    expect(screen.getByText(/could not copy 1/i)).toBeInTheDocument();
    expect(screen.getByText(/locked\.txt — access denied/i)).toBeInTheDocument();
  });

  it('renders the copy-collision overwrite-all prompt from the copy hook', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    mockUseCopy.mockReturnValue({
      ...copyBase,
      copyCollision: {count: 2, onOverwriteAll: vi.fn(), onCancel: vi.fn()}
    });
    render(<FileBrowser {...authProps} />);
    expect(screen.getByRole('alertdialog', {name: /destination already has items/i})).toBeInTheDocument();
    expect(screen.getByText(/2 item\(s\) already exist/i)).toBeInTheDocument();
  });
});

// ─── Toolbar download (authenticated) ───────────────────────────────────────────

describe('toolbar download', () => {
  const authProps = {bucket: 'my-bucket', writable: true, username: 'alice'} as const;

  it('enables Download only for a single selected file', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      files: [oneFile],
      folders: [oneFolder]
    });
    render(<FileBrowser {...authProps} />);

    expect(screen.getByRole('button', {name: 'Download selected items'})).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', {name: /select report\.pdf/i}));
    expect(screen.getByRole('button', {name: 'Download selected items'})).toBeEnabled();
    fireEvent.click(screen.getByRole('checkbox', {name: /select folder photos/i}));
    expect(screen.getByRole('button', {name: 'Download selected items'})).toBeDisabled();
  });

  it('downloads the selected file from the toolbar', async () => {
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    mockGetDownloadUrl.mockResolvedValue({
      success: true,
      data: {url: 'https://signed/report.pdf', expiresAt: '2026-01-01T00:00:00Z'}
    });
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    render(<FileBrowser {...authProps} />);

    fireEvent.click(screen.getByRole('checkbox', {name: /select report\.pdf/i}));
    fireEvent.click(screen.getByRole('button', {name: 'Download selected items'}));

    await waitFor(() => expect(clickSpy).toHaveBeenCalledOnce());
    expect(mockGetDownloadUrl).toHaveBeenCalledWith({
      bucket: 'my-bucket',
      key: 'alice/report.pdf',
      fileName: 'report.pdf'
    });
    clickSpy.mockRestore();
  });

  it('does not show a per-row Download in the authenticated flow (Details only)', () => {
    mockUseFileBrowser.mockReturnValue({...base, files: [oneFile]});
    render(<FileBrowser {...authProps} />);
    expect(screen.getByRole('button', {name: /details for report\.pdf/i})).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /download report\.pdf/i})).not.toBeInTheDocument();
  });
});
