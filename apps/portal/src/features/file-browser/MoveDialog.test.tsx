import {describe, it, expect, vi, beforeEach} from 'vitest';
import {screen, waitFor} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {MoveDialog} from './MoveDialog';
import * as service from './fileBrowser.service';
import type {SelectableItem} from './selectionContext';
import type {FileListPage, S3FolderItem} from '../../types/s3.types';

// Integration style (react.md §21): render the REAL MoveDialog → real
// DestinationPicker → real useFileBrowser, mocking ONLY the AWS boundary
// (listFiles). Navigation re-queries the mocked service per browsed prefix.
vi.mock('./fileBrowser.service', async (importActual) => {
  const actual = await importActual<typeof service>();
  return {...actual, listFiles: vi.fn()};
});
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}})
}));

const mock = vi.mocked(service);

const folder = (prefix: string, name: string): S3FolderItem => ({type: 'folder', prefix, name});
const ok = <T,>(data: T) => ({success: true as const, data});
const pageOf = (folders: S3FolderItem[] = []): FileListPage => ({files: [], folders, isTruncated: false});

/** Drives listFiles by browsed prefix so navigation surfaces different listings. */
function listing(map: Record<string, FileListPage>) {
  mock.listFiles.mockImplementation((_bucket, prefix) => Promise.resolve(ok(map[prefix ?? ''] ?? pageOf())));
}

function renderDialog(props?: Partial<React.ComponentProps<typeof MoveDialog>>) {
  const onMove = vi.fn();
  const onCancel = vi.fn();
  const result = renderWithProviders(
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
  return {...result, onMove, onCancel};
}

beforeEach(() => {
  vi.clearAllMocks();
  mock.listFiles.mockResolvedValue(ok(pageOf()));
});

describe('MoveDialog', () => {
  it('navigates into a folder and moves there', async () => {
    listing({'alice/': pageOf([folder('alice/archive/', 'archive')]), 'alice/archive/': pageOf()});
    const {user, onMove} = renderDialog();

    await user.click(await screen.findByRole('button', {name: /open folder archive/i}));
    await waitFor(() =>
      expect(mock.listFiles).toHaveBeenCalledWith('us', 'alice/archive/', undefined, expect.any(AbortSignal))
    );

    await user.click(screen.getByRole('button', {name: /move here/i}));
    expect(onMove).toHaveBeenCalledWith('alice/archive/', 'us', undefined);
  });

  it('climbs back to the root via the ".." row and can move there', async () => {
    listing({'alice/': pageOf([folder('alice/archive/', 'archive')]), 'alice/archive/': pageOf()});
    const {user, onMove} = renderDialog();

    // No ".." at the root (already at the navigation floor).
    await screen.findByRole('button', {name: /open folder archive/i});
    expect(screen.queryByRole('button', {name: /go up to parent folder/i})).not.toBeInTheDocument();

    // Descend, then the ".." row appears and climbs back to the root.
    await user.click(screen.getByRole('button', {name: /open folder archive/i}));
    await waitFor(() =>
      expect(mock.listFiles).toHaveBeenLastCalledWith('us', 'alice/archive/', undefined, expect.any(AbortSignal))
    );
    await user.click(await screen.findByRole('button', {name: /go up to parent folder/i}));
    await waitFor(() =>
      expect(mock.listFiles).toHaveBeenLastCalledWith('us', 'alice/', undefined, expect.any(AbortSignal))
    );

    // The root is a valid destination for items that live in a subfolder.
    const moveHere = screen.getByRole('button', {name: /move here/i});
    expect(moveHere).toBeEnabled();
    await user.click(moveHere);
    expect(onMove).toHaveBeenCalledWith('alice/', 'us', undefined);
  });

  it('disables "Move here" at the items\' current parent', () => {
    // Browse starts at the root = the items' current parent → forbidden (no-op).
    renderDialog({currentPrefix: 'alice/'});
    expect(screen.getByRole('button', {name: /move here/i})).toBeDisabled();
    expect(screen.getByText(/already here/i)).toBeInTheDocument();
  });

  it('hides the folders being moved (no descending into them)', async () => {
    listing({'alice/': pageOf([folder('alice/archive/', 'archive'), folder('alice/photos/', 'photos')])});
    renderDialog({items: [{type: 'folder', prefix: 'alice/photos/'}], currentPrefix: 'alice/'});
    expect(await screen.findByRole('button', {name: /open folder archive/i})).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /open folder photos/i})).not.toBeInTheDocument();
  });
});
