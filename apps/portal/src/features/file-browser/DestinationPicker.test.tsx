import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { DestinationPicker } from './DestinationPicker';
import { useFileBrowser } from './useFileBrowser';
import type { UseFileBrowserResult } from './useFileBrowser';
import type { SelectableItem } from './selectionContext';

vi.mock('./useFileBrowser');
const mockUseFileBrowser = vi.mocked(useFileBrowser);

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

const folder = (prefix: string, name: string) => ({ type: 'folder' as const, prefix, name });

beforeEach(() => {
  vi.clearAllMocks();
  mockUseFileBrowser.mockReturnValue(base);
});

function renderPicker(props?: Partial<React.ComponentProps<typeof DestinationPicker>>) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <DestinationPicker
      bucket="us"
      items={[{ type: 'file', key: 'alice/docs/f.txt' } satisfies SelectableItem]}
      rootPrefix="alice/"
      rootLabel="My Files"
      currentPrefix="alice/docs/"
      confirmLabel="Copy here"
      busyLabel="Copying…"
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...props}
    />
  );
  return { onConfirm, onCancel };
}

describe('DestinationPicker', () => {
  it('navigates into a folder and confirms there', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [folder('alice/archive/', 'archive')],
    });
    const { onConfirm } = renderPicker();

    fireEvent.click(screen.getByRole('button', { name: /open folder archive/i }));
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('us', 'alice/archive/', undefined);

    fireEvent.click(screen.getByRole('button', { name: /copy here/i }));
    expect(onConfirm).toHaveBeenCalledWith('alice/archive/');
  });

  it('excludes the protected athenaresults folder from the listing', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [folder('alice/athenaresults/', 'athenaresults'), folder('alice/x/', 'x')],
    });
    renderPicker();
    expect(screen.queryByRole('button', { name: /open folder athenaresults/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /open folder x/i })).toBeInTheDocument();
  });

  it('blocks the current parent when allowCurrentParent is false (Move semantics)', () => {
    renderPicker({ currentPrefix: 'alice/', allowCurrentParent: false });
    expect(screen.getByRole('button', { name: /copy here/i })).toBeDisabled();
    expect(screen.getByText(/already here/i)).toBeInTheDocument();
  });

  it('permits the current parent when allowCurrentParent is true (Copy semantics)', () => {
    renderPicker({ currentPrefix: 'alice/', allowCurrentParent: true });
    expect(screen.getByRole('button', { name: /copy here/i })).toBeEnabled();
  });

  it("blocks confirming inside a copied folder's own subtree", () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [folder('alice/photos/sub/', 'sub')],
    });
    renderPicker({
      items: [{ type: 'folder', prefix: 'alice/photos/' }],
      currentPrefix: 'alice/',
      rootPrefix: 'alice/photos/',
      allowCurrentParent: true,
      selfMessage: "You can't copy a folder into itself.",
    });
    // Browsing starts at rootPrefix = the folder's own prefix → inside its subtree.
    expect(screen.getByRole('button', { name: /copy here/i })).toBeDisabled();
    expect(screen.getByText(/can't copy a folder into itself/i)).toBeInTheDocument();
  });
});
