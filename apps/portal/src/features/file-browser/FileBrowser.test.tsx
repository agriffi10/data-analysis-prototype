import { render, screen, fireEvent, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { FileBrowser } from './FileBrowser';
import { useFileBrowser } from './useFileBrowser';
import type { UseFileBrowserResult } from './useFileBrowser';

vi.mock('./useFileBrowser');

const mockUseFileBrowser = vi.mocked(useFileBrowser);

const base: UseFileBrowserResult = {
  files: [],
  folders: [],
  isLoading: false,
  error: null,
  refresh: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
  mockUseFileBrowser.mockReturnValue(base);
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

    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('my-bucket', 'photos/');
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
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('my-bucket', 'project-alpha/docs/');

    // Navigate back to root via the leftmost breadcrumb crumb
    const nav = screen.getByRole('navigation', { name: /breadcrumb/i });
    fireEvent.click(within(nav).getByRole('button', { name: 'project-alpha' }));
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('my-bucket', 'project-alpha/');
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
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('my-bucket', 'archive/');

    // navigate back via breadcrumb
    const nav = screen.getByRole('navigation', { name: /breadcrumb/i });
    fireEvent.click(within(nav).getByRole('button', { name: 'Home' }));
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('my-bucket', undefined);
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
