import { render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { FileBrowser } from './FileBrowser';
import { useFileBrowser } from './useFileBrowser';
import type { UseFileBrowserResult } from './useFileBrowser';
import { getDownloadUrl } from './fileBrowser.service';
import { useFileUpload } from './useFileUpload';
import type { UseFileUploadResult } from './useFileUpload';
import { useDelete } from './useDelete';
import type { UseDeleteResult } from './useDelete';
import { useMove } from './useMove';
import type { UseMoveResult } from './useMove';

vi.mock('./useFileBrowser');
vi.mock('./fileBrowser.service');
vi.mock('./useFileUpload');
vi.mock('./useDelete');
vi.mock('./useMove');
// Stub the move dialog's folder picker so these tests don't pull in useFileBrowser
// twice; MoveDialog itself is covered by MoveDialog.test.tsx.
vi.mock('./MoveDialog', () => ({
  MoveDialog: ({
    items,
    onMove,
    onCancel,
  }: {
    items: { type: string }[];
    onMove: (destPrefix: string) => void;
    onCancel: () => void;
  }) => (
    <div role="dialog" aria-label="Move to folder">
      <span>moving {items.length}</span>
      <button onClick={() => onMove('alice/dest/')}>move-here-stub</button>
      <button onClick={onCancel}>move-cancel-stub</button>
    </div>
  ),
}));
// Stub the rename dialog — its validation uses validateFolderName, which is
// auto-mocked by the wholesale ./fileBrowser.service mock below. The real dialog
// (and its validation) is covered by RenameDialog.test.tsx.
vi.mock('./RenameDialog', () => ({
  RenameDialog: ({
    currentName,
    onRename,
    onCancel,
  }: {
    currentName: string;
    onRename: (newName: string) => void;
    onCancel: () => void;
  }) => (
    <div role="dialog" aria-label="Rename">
      <span>renaming {currentName}</span>
      <button onClick={() => onRename('renamed')}>rename-submit-stub</button>
      <button onClick={onCancel}>rename-cancel-stub</button>
    </div>
  ),
}));
// Stub the metadata drawer so these tests don't pull in its TanStack Query hook
// (covered by MetadataPanel.test.tsx). The stub echoes the file it was opened for.
vi.mock('./MetadataPanel', () => ({
  MetadataPanel: ({
    file,
    onClose,
  }: {
    file: { name: string };
    onClose: () => void;
  }) => (
    <div role="dialog" aria-label={`Details for ${file.name}`}>
      <button onClick={onClose}>close-stub</button>
    </div>
  ),
}));

const mockUseFileBrowser = vi.mocked(useFileBrowser);
const mockGetDownloadUrl = vi.mocked(getDownloadUrl);
const mockUseFileUpload = vi.mocked(useFileUpload);
const mockUseDelete = vi.mocked(useDelete);
const mockUseMove = vi.mocked(useMove);

const base: UseFileBrowserResult = {
  files: [],
  folders: [],
  isLoading: false,
  error: null,
  refresh: vi.fn(),
  hasMore: false,
  loadMore: vi.fn(),
  isLoadingMore: false,
};

const uploadBase: UseFileUploadResult = {
  progress: null,
  pendingCollision: null,
  error: null,
  isBusy: false,
  uploadOne: vi.fn(),
  createNewFolder: vi.fn(),
  cancelCollision: vi.fn(),
  dismissError: vi.fn(),
};

const deleteBase: UseDeleteResult = {
  isDeleting: false,
  summary: null,
  error: null,
  runDelete: vi.fn().mockResolvedValue({ deletedCount: 0, errors: [] }),
  dismissSummary: vi.fn(),
  dismissError: vi.fn(),
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
  cancelCollision: vi.fn(),
};

// A file + folder fixture used by the selection/delete tests. The delete UI is
// only offered when both `writable` and `username` are set (authenticated flow).
const oneFile = {
  type: 'file' as const,
  key: 'alice/report.pdf',
  name: 'report.pdf',
  size: 1024,
  lastModified: new Date('2024-01-01'),
};
const oneFolder = { type: 'folder' as const, prefix: 'alice/photos/', name: 'photos' };

beforeEach(() => {
  vi.clearAllMocks();
  mockUseFileBrowser.mockReturnValue(base);
  mockUseFileUpload.mockReturnValue(uploadBase);
  mockUseDelete.mockReturnValue(deleteBase);
  mockUseMove.mockReturnValue(moveBase);
});

// ─── Loading ──────────────────────────────────────────────────────────────────

describe('loading state', () => {
  it('shows a loading indicator when isLoading is true', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, isLoading: true });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.getByRole('status', { name: /loading/i })).toBeInTheDocument();
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
          lastModified: new Date(),
        },
      ],
    });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.queryByText('secret.txt')).not.toBeInTheDocument();
  });
});

// ─── Error ────────────────────────────────────────────────────────────────────

describe('error state', () => {
  it('shows an alert with the error message', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, error: 'Access Denied' });
    render(<FileBrowser bucket="my-bucket" />);
    const alert = screen.getByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent('Access Denied');
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
      folders: [{ type: 'folder', prefix: 'docs/', name: 'docs' }],
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
          lastModified: new Date(),
        },
      ],
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
          lastModified: new Date(),
        },
      ],
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
          lastModified: new Date('2024-06-15T00:00:00Z'),
        },
      ],
    });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.getByText(/2024/)).toBeInTheDocument();
  });

  it('renders folders before files', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [{ type: 'folder', prefix: 'archive/', name: 'archive' }],
      files: [
        {
          type: 'file',
          key: 'notes.txt',
          name: 'notes.txt',
          size: 10,
          lastModified: new Date(),
        },
      ],
    });
    render(<FileBrowser bucket="my-bucket" />);
    const list = screen.getByRole('list', { name: /file list/i });
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
      folders: [{ type: 'folder', prefix: 'photos/', name: 'photos' }],
    });
    render(<FileBrowser bucket="my-bucket" />);

    fireEvent.click(screen.getByRole('button', { name: /open folder photos/i }));

    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('my-bucket', 'photos/', undefined);
  });
});

// ─── Root prefix clamping ─────────────────────────────────────────────────────

describe('root prefix clamping', () => {
  it('shows the root prefix folder name instead of Home when rootPrefix is set', () => {
    render(
      <FileBrowser bucket="my-bucket" prefix="project-alpha/" rootPrefix="project-alpha/" />,
    );
    const nav = screen.getByRole('navigation', { name: /breadcrumb/i });
    expect(nav).toHaveTextContent('project-alpha');
    expect(within(nav).queryByText('Home')).not.toBeInTheDocument();
    // At root prefix the root crumb is aria-current="page", not a button
    expect(
      within(nav).queryByRole('button', { name: 'project-alpha' }),
    ).not.toBeInTheDocument();
  });

  it('uses rootLabel for the root crumb, hiding the raw prefix segment (SPEC-013)', () => {
    // The username is the navigation floor but must never be shown to the user.
    render(
      <FileBrowser
        bucket="my-bucket"
        prefix="alice/"
        rootPrefix="alice/"
        rootLabel="My Files"
      />,
    );
    const nav = screen.getByRole('navigation', { name: /breadcrumb/i });
    expect(within(nav).getByText('My Files')).toBeInTheDocument();
    // The raw username segment is never rendered.
    expect(within(nav).queryByText('alice')).not.toBeInTheDocument();
  });

  it('keeps showing the username segment as the floor label when browsing deeper, still hidden', () => {
    mockUseFileBrowser.mockImplementation((_bucket, prefix) => ({
      ...base,
      folders:
        prefix === 'alice/'
          ? [{ type: 'folder', prefix: 'alice/docs/', name: 'docs' }]
          : [],
    }));
    render(
      <FileBrowser
        bucket="my-bucket"
        prefix="alice/"
        rootPrefix="alice/"
        rootLabel="My Files"
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /open folder docs/i }));

    const nav = screen.getByRole('navigation', { name: /breadcrumb/i });
    expect(within(nav).getByRole('button', { name: 'My Files' })).toBeInTheDocument();
    expect(within(nav).queryByText('alice')).not.toBeInTheDocument();
    expect(within(nav).getByText('docs')).toHaveAttribute('aria-current', 'page');
  });

  it('does not show path segments above rootPrefix when browsing deeper', () => {
    mockUseFileBrowser.mockImplementation((_bucket, prefix) => ({
      ...base,
      folders:
        prefix === 'project-alpha/'
          ? [{ type: 'folder', prefix: 'project-alpha/docs/', name: 'docs' }]
          : [],
    }));
    render(
      <FileBrowser bucket="my-bucket" prefix="project-alpha/" rootPrefix="project-alpha/" />,
    );

    fireEvent.click(screen.getByRole('button', { name: /open folder docs/i }));

    const nav = screen.getByRole('navigation', { name: /breadcrumb/i });
    expect(within(nav).queryByText('Home')).not.toBeInTheDocument();
    expect(within(nav).getByRole('button', { name: 'project-alpha' })).toBeInTheDocument();
    expect(within(nav).getByText('docs')).toHaveAttribute('aria-current', 'page');
  });

  it('clicking the root prefix crumb navigates to rootPrefix not bucket root', () => {
    mockUseFileBrowser.mockImplementation((_bucket, prefix) => ({
      ...base,
      folders:
        prefix === 'project-alpha/'
          ? [{ type: 'folder', prefix: 'project-alpha/docs/', name: 'docs' }]
          : [],
    }));
    render(
      <FileBrowser bucket="my-bucket" prefix="project-alpha/" rootPrefix="project-alpha/" />,
    );

    // Drill into docs/
    fireEvent.click(screen.getByRole('button', { name: /open folder docs/i }));
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('my-bucket', 'project-alpha/docs/', undefined);

    // Navigate back to root via the leftmost breadcrumb crumb
    const nav = screen.getByRole('navigation', { name: /breadcrumb/i });
    fireEvent.click(within(nav).getByRole('button', { name: 'project-alpha' }));
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('my-bucket', 'project-alpha/', undefined);
  });
});

// ─── Breadcrumb ───────────────────────────────────────────────────────────────

describe('breadcrumb', () => {
  it('shows only "Home" at the root level', () => {
    render(<FileBrowser bucket="my-bucket" />);
    const nav = screen.getByRole('navigation', { name: /breadcrumb/i });
    expect(nav).toHaveTextContent('Home');
    // Home is aria-current="page" at root, not a button
    expect(
      within(nav).queryByRole('button', { name: 'Home' }),
    ).not.toBeInTheDocument();
  });

  it('updates to show the folder name after drilling in', () => {
    mockUseFileBrowser.mockImplementation((_bucket, prefix) => ({
      ...base,
      folders:
        prefix === undefined
          ? [{ type: 'folder', prefix: 'reports/', name: 'reports' }]
          : [],
    }));
    render(<FileBrowser bucket="my-bucket" />);

    fireEvent.click(
      screen.getByRole('button', { name: /open folder reports/i }),
    );

    const nav = screen.getByRole('navigation', { name: /breadcrumb/i });
    expect(nav).toHaveTextContent('Home');
    expect(
      within(nav).getByText('reports'),
    ).toHaveAttribute('aria-current', 'page');
    // Home is now a clickable button
    expect(within(nav).getByRole('button', { name: 'Home' })).toBeInTheDocument();
  });

  it('clicking an ancestor crumb navigates back up', () => {
    mockUseFileBrowser.mockImplementation((_bucket, prefix) => ({
      ...base,
      folders:
        prefix === undefined
          ? [{ type: 'folder', prefix: 'archive/', name: 'archive' }]
          : [],
    }));
    render(<FileBrowser bucket="my-bucket" />);

    // drill in
    fireEvent.click(
      screen.getByRole('button', { name: /open folder archive/i }),
    );
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('my-bucket', 'archive/', undefined);

    // navigate back via breadcrumb
    const nav = screen.getByRole('navigation', { name: /breadcrumb/i });
    fireEvent.click(within(nav).getByRole('button', { name: 'Home' }));
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('my-bucket', undefined, undefined);
  });

  it('builds multi-level breadcrumbs for nested prefixes', () => {
    mockUseFileBrowser.mockImplementation((_bucket, prefix) => ({
      ...base,
      folders:
        prefix === 'docs/'
          ? [{ type: 'folder', prefix: 'docs/2024/', name: '2024' }]
          : prefix === undefined
            ? [{ type: 'folder', prefix: 'docs/', name: 'docs' }]
            : [],
    }));
    render(<FileBrowser bucket="my-bucket" />);

    // first level
    fireEvent.click(screen.getByRole('button', { name: /open folder docs/i }));
    // second level
    fireEvent.click(screen.getByRole('button', { name: /open folder 2024/i }));

    const nav = screen.getByRole('navigation', { name: /breadcrumb/i });
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
        lastModified: new Date('2024-01-01'),
      },
    ],
  };

  it('shows "Load more" only when hasMore is true', () => {
    mockUseFileBrowser.mockReturnValue({ ...withFile, hasMore: true });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.getByRole('button', { name: /load more/i })).toBeInTheDocument();
  });

  it('hides "Load more" when fully loaded', () => {
    mockUseFileBrowser.mockReturnValue({ ...withFile, hasMore: false });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.queryByRole('button', { name: /load more/i })).not.toBeInTheDocument();
  });

  it('calls loadMore when clicked', () => {
    const loadMore = vi.fn();
    mockUseFileBrowser.mockReturnValue({ ...withFile, hasMore: true, loadMore });
    render(<FileBrowser bucket="my-bucket" />);
    fireEvent.click(screen.getByRole('button', { name: /load more/i }));
    expect(loadMore).toHaveBeenCalledOnce();
  });

  it('disables the control while a page is loading', () => {
    mockUseFileBrowser.mockReturnValue({
      ...withFile,
      hasMore: true,
      isLoadingMore: true,
    });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.getByRole('button', { name: /loading/i })).toBeDisabled();
  });
});

// ─── Download (SPEC-015 FR-003) ────────────────────────────────────────────────

describe('download', () => {
  const fileItem = {
    type: 'file' as const,
    key: 'alice/docs/report.pdf',
    name: 'report.pdf',
    size: 1024,
    lastModified: new Date('2024-01-01'),
  };

  beforeEach(() => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [fileItem] });
  });

  it('exposes a Download action per file', () => {
    render(<FileBrowser bucket="my-bucket" />);
    expect(
      screen.getByRole('button', { name: /download report\.pdf/i }),
    ).toBeInTheDocument();
  });

  it('folders expose no Download action', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [{ type: 'folder', prefix: 'docs/', name: 'docs' }],
    });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.queryByRole('button', { name: /download/i })).not.toBeInTheDocument();
  });

  it('requests a presigned URL and triggers the browser download on success', async () => {
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});
    mockGetDownloadUrl.mockResolvedValue({
      success: true,
      data: { url: 'https://signed.example/report.pdf', expiresAt: '2026-01-01T00:00:00Z' },
    });

    render(<FileBrowser bucket="my-bucket" />);
    fireEvent.click(screen.getByRole('button', { name: /download report\.pdf/i }));

    await waitFor(() => expect(clickSpy).toHaveBeenCalledOnce());
    expect(mockGetDownloadUrl).toHaveBeenCalledWith({
      bucket: 'my-bucket',
      key: 'alice/docs/report.pdf',
      fileName: 'report.pdf',
    });
    clickSpy.mockRestore();
  });

  it('surfaces a download error inline without throwing', async () => {
    mockGetDownloadUrl.mockResolvedValue({
      success: false,
      error: { message: 'No AWS credentials — sign in required' },
    });

    render(<FileBrowser bucket="my-bucket" />);
    fireEvent.click(screen.getByRole('button', { name: /download report\.pdf/i }));

    expect(
      await screen.findByText(/could not download report\.pdf/i),
    ).toBeInTheDocument();
  });
});

// ─── Details / metadata panel (SPEC-017) ───────────────────────────────────────

describe('details panel', () => {
  const fileItem = {
    type: 'file' as const,
    key: 'alice/docs/report.pdf',
    name: 'report.pdf',
    size: 1024,
    lastModified: new Date('2024-01-01'),
  };

  it('exposes a Details action per file', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [fileItem] });
    render(<FileBrowser bucket="my-bucket" />);
    expect(
      screen.getByRole('button', { name: /details for report\.pdf/i }),
    ).toBeInTheDocument();
  });

  it('folders expose no Details action', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [{ type: 'folder', prefix: 'docs/', name: 'docs' }],
    });
    render(<FileBrowser bucket="my-bucket" />);
    expect(
      screen.queryByRole('button', { name: /details for/i }),
    ).not.toBeInTheDocument();
  });

  it('opens the metadata drawer for the file when Details is clicked', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [fileItem] });
    render(<FileBrowser bucket="my-bucket" />);

    expect(
      screen.queryByRole('dialog', { name: /details for report\.pdf/i }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', { name: /details for report\.pdf/i }),
    );

    expect(
      screen.getByRole('dialog', { name: /details for report\.pdf/i }),
    ).toBeInTheDocument();
  });

  it('closes the drawer when the panel requests close', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [fileItem] });
    render(<FileBrowser bucket="my-bucket" />);

    fireEvent.click(
      screen.getByRole('button', { name: /details for report\.pdf/i }),
    );
    fireEvent.click(screen.getByRole('button', { name: /close-stub/i }));

    expect(
      screen.queryByRole('dialog', { name: /details for report\.pdf/i }),
    ).not.toBeInTheDocument();
  });
});

// ─── Write controls gating (SPEC-016) ──────────────────────────────────────────

describe('write controls', () => {
  it('are hidden when not writable (read-only / dev-unauth)', () => {
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.queryByRole('button', { name: /new folder/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/choose a file/i)).not.toBeInTheDocument();
  });

  it('show the New folder button and upload dropzone when writable', () => {
    render(<FileBrowser bucket="my-bucket" writable />);
    expect(screen.getByRole('button', { name: /new folder/i })).toBeInTheDocument();
    expect(screen.getByText(/choose a file/i)).toBeInTheDocument();
  });

  it('renders an upload progress bar while a file is uploading', () => {
    mockUseFileUpload.mockReturnValue({ ...uploadBase, progress: 42 });
    render(<FileBrowser bucket="my-bucket" writable />);
    const bar = screen.getByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '42');
  });
});

// ─── Selection + delete (SPEC-018) ──────────────────────────────────────────────

describe('selection + delete', () => {
  const authProps = { bucket: 'my-bucket', writable: true, username: 'alice' } as const;

  it('shows no selection checkboxes when not writable (read-only)', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [oneFile] });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('shows no selection checkboxes when writable but unauthenticated (no username)', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [oneFile] });
    render(<FileBrowser bucket="my-bucket" writable />);
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('renders per-row + select-all checkboxes in the authenticated writable flow', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      files: [oneFile],
      folders: [oneFolder],
    });
    render(<FileBrowser {...authProps} />);
    expect(screen.getByRole('checkbox', { name: /select all/i })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /select report\.pdf/i })).toBeInTheDocument();
    expect(
      screen.getByRole('checkbox', { name: /select folder photos/i }),
    ).toBeInTheDocument();
  });

  it('disables Delete until something is selected', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [oneFile] });
    render(<FileBrowser {...authProps} />);

    expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: /select report\.pdf/i }));
    expect(screen.getByRole('button', { name: 'Delete' })).toBeEnabled();
  });

  it('select-all toggles every row', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      files: [oneFile],
      folders: [oneFolder],
    });
    render(<FileBrowser {...authProps} />);

    fireEvent.click(screen.getByRole('checkbox', { name: /select all/i }));
    expect(screen.getByRole('checkbox', { name: /select report\.pdf/i })).toBeChecked();
    expect(
      screen.getByRole('checkbox', { name: /select folder photos/i }),
    ).toBeChecked();
  });

  it('opens a confirmation naming the item and deletes nothing until confirmed', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [oneFile] });
    render(<FileBrowser {...authProps} />);

    fireEvent.click(screen.getByRole('checkbox', { name: /select report\.pdf/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    const dialog = screen.getByRole('alertdialog', { name: /confirm delete/i });
    expect(dialog).toHaveTextContent(/report\.pdf/);
    expect(dialog).toHaveTextContent(/can.t be undone/i);
    expect(deleteBase.runDelete).not.toHaveBeenCalled();
  });

  it('confirming deletes exactly the selected files and folders', async () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      files: [oneFile],
      folders: [oneFolder],
    });
    render(<FileBrowser {...authProps} />);

    fireEvent.click(screen.getByRole('checkbox', { name: /select report\.pdf/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /select folder photos/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    const dialog = screen.getByRole('alertdialog', { name: /confirm delete/i });
    fireEvent.click(within(dialog).getByRole('button', { name: /^delete$/i }));

    await waitFor(() => expect(deleteBase.runDelete).toHaveBeenCalledTimes(1));
    const items = vi.mocked(deleteBase.runDelete).mock.calls[0][0];
    expect(items).toEqual(
      expect.arrayContaining([
        { type: 'file', key: 'alice/report.pdf' },
        { type: 'folder', prefix: 'alice/photos/' },
      ]),
    );
    expect(items).toHaveLength(2);
  });

  it('cancelling the confirmation deletes nothing and closes the dialog', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [oneFile] });
    render(<FileBrowser {...authProps} />);

    fireEvent.click(screen.getByRole('checkbox', { name: /select report\.pdf/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    const dialog = screen.getByRole('alertdialog', { name: /confirm delete/i });
    fireEvent.click(within(dialog).getByRole('button', { name: /cancel/i }));

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(deleteBase.runDelete).not.toHaveBeenCalled();
  });

  it('shows a success summary with the deleted count', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [oneFile] });
    mockUseDelete.mockReturnValue({
      ...deleteBase,
      summary: { deletedCount: 3, errors: [] },
    });
    render(<FileBrowser {...authProps} />);

    expect(screen.getByRole('status')).toHaveTextContent(/deleted 3 items/i);
  });

  it('shows a partial-failure summary listing what failed and why', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [oneFile] });
    mockUseDelete.mockReturnValue({
      ...deleteBase,
      summary: {
        deletedCount: 1,
        errors: [{ key: 'alice/locked.txt', message: 'Access Denied' }],
      },
    });
    render(<FileBrowser {...authProps} />);

    expect(screen.getByText(/could not delete 1/i)).toBeInTheDocument();
    expect(screen.getByText(/locked\.txt — access denied/i)).toBeInTheDocument();
  });
});

// ─── Rename + move (SPEC-019) ───────────────────────────────────────────────────

describe('rename + move', () => {
  const authProps = { bucket: 'my-bucket', writable: true, username: 'alice' } as const;

  it('shows no Rename action when read-only', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [oneFile] });
    render(<FileBrowser bucket="my-bucket" />);
    expect(screen.queryByRole('button', { name: /rename/i })).not.toBeInTheDocument();
  });

  it('exposes a Rename action per file and folder in the authenticated flow', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      files: [oneFile],
      folders: [oneFolder],
    });
    render(<FileBrowser {...authProps} />);
    expect(
      screen.getByRole('button', { name: /rename report\.pdf/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /rename folder photos/i }),
    ).toBeInTheDocument();
  });

  it('renaming a file opens the dialog and calls renameItem on submit', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [oneFile] });
    render(<FileBrowser {...authProps} />);

    fireEvent.click(screen.getByRole('button', { name: /rename report\.pdf/i }));
    const dialog = screen.getByRole('dialog', { name: /rename/i });
    fireEvent.click(within(dialog).getByRole('button', { name: /rename-submit-stub/i }));

    expect(moveBase.renameItem).toHaveBeenCalledWith(
      { type: 'file', key: 'alice/report.pdf' },
      'renamed',
    );
  });

  it('disables Move until something is selected', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [oneFile] });
    render(<FileBrowser {...authProps} />);
    expect(screen.getByRole('button', { name: 'Move' })).toBeDisabled();
  });

  it('Move opens the destination picker and calls moveItems on confirm', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [oneFile], folders: [oneFolder] });
    render(<FileBrowser {...authProps} />);

    fireEvent.click(screen.getByRole('checkbox', { name: /select report\.pdf/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Move' }));

    const dialog = screen.getByRole('dialog', { name: /move to folder/i });
    expect(dialog).toHaveTextContent(/moving 1/i);
    fireEvent.click(within(dialog).getByRole('button', { name: /move-here-stub/i }));

    expect(moveBase.moveItems).toHaveBeenCalledWith(
      [{ type: 'file', key: 'alice/report.pdf' }],
      'alice/dest/',
    );
  });

  it('shows a move result summary with the moved count', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [oneFile] });
    mockUseMove.mockReturnValue({
      ...moveBase,
      summary: { movedCount: 2, errors: [] },
    });
    render(<FileBrowser {...authProps} />);
    expect(screen.getByText(/moved 2 items/i)).toBeInTheDocument();
  });

  it('renders the rename-collision prompt from the move hook', () => {
    mockUseFileBrowser.mockReturnValue({ ...base, files: [oneFile] });
    mockUseMove.mockReturnValue({
      ...moveBase,
      renameCollision: {
        kind: 'file',
        label: 'taken.pdf',
        onOverwrite: vi.fn(),
        onRename: vi.fn(),
        onCancel: vi.fn(),
      },
    });
    render(<FileBrowser {...authProps} />);
    expect(
      screen.getByRole('alertdialog', { name: /already exists/i }),
    ).toBeInTheDocument();
  });
});
