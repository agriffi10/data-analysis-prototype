import {render, screen, fireEvent} from '@testing-library/react';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {DestinationPicker} from './DestinationPicker';
import {useFileBrowser} from './useFileBrowser';
import type {UseFileBrowserResult} from './useFileBrowser';
import type {SelectableItem} from './selectionContext';

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
  isLoadingMore: false
};

const folder = (prefix: string, name: string) => ({type: 'folder' as const, prefix, name});

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
      items={[{type: 'file', key: 'alice/docs/f.txt'} satisfies SelectableItem]}
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
  return {onConfirm, onCancel};
}

describe('DestinationPicker', () => {
  it('navigates into a folder and confirms there', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [folder('alice/archive/', 'archive')]
    });
    const {onConfirm} = renderPicker();

    fireEvent.click(screen.getByRole('button', {name: /open folder archive/i}));
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('us', 'alice/archive/', undefined);

    fireEvent.click(screen.getByRole('button', {name: /copy here/i}));
    expect(onConfirm).toHaveBeenCalledWith('alice/archive/', 'us');
  });

  it('excludes the protected athenaresults folder from the listing', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [folder('alice/athenaresults/', 'athenaresults'), folder('alice/x/', 'x')]
    });
    renderPicker();
    expect(screen.queryByRole('button', {name: /open folder athenaresults/i})).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: /open folder x/i})).toBeInTheDocument();
  });

  it('blocks the current parent when allowCurrentParent is false (Move semantics)', () => {
    renderPicker({currentPrefix: 'alice/', allowCurrentParent: false});
    expect(screen.getByRole('button', {name: /copy here/i})).toBeDisabled();
    expect(screen.getByText(/already here/i)).toBeInTheDocument();
  });

  it('permits the current parent when allowCurrentParent is true (Copy semantics)', () => {
    renderPicker({currentPrefix: 'alice/', allowCurrentParent: true});
    expect(screen.getByRole('button', {name: /copy here/i})).toBeEnabled();
  });

  it("blocks confirming inside a copied folder's own subtree", () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [folder('alice/photos/sub/', 'sub')]
    });
    renderPicker({
      items: [{type: 'folder', prefix: 'alice/photos/'}],
      currentPrefix: 'alice/',
      rootPrefix: 'alice/photos/',
      allowCurrentParent: true,
      selfMessage: "You can't copy a folder into itself."
    });
    // Browsing starts at rootPrefix = the folder's own prefix → inside its subtree.
    expect(screen.getByRole('button', {name: /copy here/i})).toBeDisabled();
    expect(screen.getByText(/can't copy a folder into itself/i)).toBeInTheDocument();
  });

  // ── Cross-connection destinations (feedback 2026-06-30) ────────────────────
  const destinations = [
    {id: 'personal', bucket: 'us', rootPrefix: 'alice/', label: 'My Files', kind: 'personal' as const},
    {id: 'team', bucket: 'shared', rootPrefix: 'team/', label: 'team', kind: 'shared' as const}
  ];

  it('shows a connection selector only when more than one destination is given', () => {
    renderPicker(); // no destinations → no selector
    expect(screen.queryByLabelText(/destination connection/i)).not.toBeInTheDocument();

    renderPicker({destinations});
    expect(screen.getByLabelText(/destination connection/i)).toBeInTheDocument();
  });

  it('browses and confirms into another connection (different bucket + root)', () => {
    const {onConfirm} = renderPicker({destinations, currentPrefix: 'alice/docs/'});

    // Default selection is the source space (us / alice/).
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('us', 'alice/', undefined);

    // Switch to the shared connection: browsing re-targets its bucket + root.
    fireEvent.change(screen.getByLabelText(/destination connection/i), {target: {value: 'team'}});
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('shared', 'team/', undefined);

    // Confirming reports the shared bucket as the destination bucket.
    fireEvent.click(screen.getByRole('button', {name: /copy here/i}));
    expect(onConfirm).toHaveBeenCalledWith('team/', 'shared');
  });
});
