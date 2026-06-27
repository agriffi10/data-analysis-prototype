import {render, screen, fireEvent} from '@testing-library/react';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {MoveDialog} from './MoveDialog';
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

function renderDialog(props?: Partial<React.ComponentProps<typeof MoveDialog>>) {
  const onMove = vi.fn();
  const onCancel = vi.fn();
  render(
    <MoveDialog
      bucket="us"
      items={[{type: 'file', key: 'alice/docs/f.txt'} satisfies SelectableItem]}
      rootPrefix="alice/"
      rootLabel="My Files"
      currentPrefix="alice/docs/"
      onMove={onMove}
      onCancel={onCancel}
      {...props}
    />
  );
  return {onMove, onCancel};
}

describe('MoveDialog', () => {
  it('lists navigable destination folders', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [folder('alice/archive/', 'archive')]
    });
    renderDialog();
    expect(screen.getByRole('button', {name: /open folder archive/i})).toBeInTheDocument();
  });

  it('moves to the browsed prefix when "Move here" is clicked', () => {
    const {onMove} = renderDialog();
    // At the root ("alice/"), which is not the items' current parent ("alice/docs/").
    const moveHere = screen.getByRole('button', {name: /move here/i});
    expect(moveHere).toBeEnabled();
    fireEvent.click(moveHere);
    expect(onMove).toHaveBeenCalledWith('alice/');
  });

  it('disables "Move here" at the items\' current parent', () => {
    renderDialog({currentPrefix: 'alice/'}); // browse starts at root = current parent
    expect(screen.getByRole('button', {name: /move here/i})).toBeDisabled();
    expect(screen.getByText(/already here/i)).toBeInTheDocument();
  });

  it('hides folders that are being moved (no descending into them)', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [folder('alice/archive/', 'archive'), folder('alice/photos/', 'photos')]
    });
    renderDialog({
      items: [{type: 'folder', prefix: 'alice/photos/'}],
      currentPrefix: 'alice/'
    });
    expect(screen.getByRole('button', {name: /open folder archive/i})).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /open folder photos/i})).not.toBeInTheDocument();
  });

  it('navigates back up to the root via the ".." row and can move there', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [folder('alice/archive/', 'archive')]
    });
    const {onMove} = renderDialog();

    // No ".." at the root (already at the navigation floor).
    expect(screen.queryByRole('button', {name: /go up to parent folder/i})).not.toBeInTheDocument();

    // Descend, then the ".." row appears and climbs back to root.
    fireEvent.click(screen.getByRole('button', {name: /open folder archive/i}));
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('us', 'alice/archive/', undefined);

    fireEvent.click(screen.getByRole('button', {name: /go up to parent folder/i}));
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('us', 'alice/', undefined);

    // Root is a valid destination for items that live in a subfolder.
    const moveHere = screen.getByRole('button', {name: /move here/i});
    expect(moveHere).toBeEnabled();
    fireEvent.click(moveHere);
    expect(onMove).toHaveBeenCalledWith('alice/');
  });

  it('navigates into a folder and moves there', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [folder('alice/archive/', 'archive')]
    });
    const {onMove} = renderDialog();

    fireEvent.click(screen.getByRole('button', {name: /open folder archive/i}));
    expect(mockUseFileBrowser).toHaveBeenLastCalledWith('us', 'alice/archive/', undefined);

    fireEvent.click(screen.getByRole('button', {name: /move here/i}));
    expect(onMove).toHaveBeenCalledWith('alice/archive/');
  });
});
