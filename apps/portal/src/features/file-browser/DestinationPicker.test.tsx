import {describe, it, expect, vi, beforeEach} from 'vitest';
import {screen, waitFor} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {DestinationPicker} from './DestinationPicker';
import * as service from './fileBrowser.service';
import type {SelectableItem} from './selectionContext';
import type {FileListPage, S3FileItem, S3FolderItem} from '../../types/s3.types';

// Integration style (react.md §21): render the REAL DestinationPicker driving the
// REAL useFileBrowser hook, and mock ONLY the AWS boundary (listFiles). Navigation
// re-queries the mocked service per browsed prefix; the pure helpers stay real via
// importActual.
vi.mock('./fileBrowser.service', async (importActual) => {
  const actual = await importActual<typeof service>();
  return {...actual, listFiles: vi.fn()};
});
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}})
}));

const mock = vi.mocked(service);

const folder = (prefix: string, name: string): S3FolderItem => ({type: 'folder', prefix, name});
const file = (key: string, name: string): S3FileItem => ({
  type: 'file',
  key,
  name,
  size: 0,
  lastModified: new Date(0)
});
const ok = <T,>(data: T) => ({success: true as const, data});
const pageOf = (folders: S3FolderItem[] = [], files: S3FileItem[] = []): FileListPage => ({
  files,
  folders,
  isTruncated: false
});

/** Drives listFiles by browsed prefix so navigation surfaces different listings. */
function listing(map: Record<string, FileListPage>) {
  mock.listFiles.mockImplementation((_bucket, prefix) => Promise.resolve(ok(map[prefix ?? ''] ?? pageOf())));
}

// `Props` is a union (selectableFiles ⇒ markerKey required), which `Partial<>` can't
// express usefully for a test helper — the override bag is loosened to a record and
// re-widened at the spread. The union is still enforced at every real call site.
type PickerProps = React.ComponentProps<typeof DestinationPicker>;

function renderPicker(props?: Record<string, unknown>) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  const base = {
    bucket: 'us',
    items: [{type: 'file', key: 'alice/docs/f.txt'} satisfies SelectableItem],
    rootPrefix: 'alice/',
    rootLabel: 'My Files',
    currentPrefix: 'alice/docs/',
    confirmLabel: 'Copy here',
    busyLabel: 'Copying…',
    onConfirm,
    onCancel
  };
  const result = renderWithProviders(<DestinationPicker {...({...base, ...props} as PickerProps)} />);
  return {...result, onConfirm, onCancel};
}

beforeEach(() => {
  vi.clearAllMocks();
  mock.listFiles.mockResolvedValue(ok(pageOf()));
});

describe('DestinationPicker', () => {
  it('navigates into a folder and confirms the browsed prefix', async () => {
    listing({'alice/': pageOf([folder('alice/archive/', 'archive')]), 'alice/archive/': pageOf()});
    const {user, onConfirm} = renderPicker();

    await user.click(await screen.findByRole('button', {name: /open folder archive/i}));
    await waitFor(() => expect(mock.listFiles).toHaveBeenCalledWith('us', 'alice/archive/', undefined));

    await user.click(screen.getByRole('button', {name: /copy here/i}));
    expect(onConfirm).toHaveBeenCalledWith('alice/archive/', 'us', undefined);
  });

  it('excludes the protected athenaresults folder from the listing', async () => {
    listing({'alice/': pageOf([folder('alice/athenaresults/', 'athenaresults'), folder('alice/x/', 'x')])});
    renderPicker();
    expect(await screen.findByRole('button', {name: /open folder x/i})).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /open folder athenaresults/i})).not.toBeInTheDocument();
  });

  it('gates the current parent by allowCurrentParent (Move blocks, Copy allows)', () => {
    // Confirm-state is a render-time gate off browsePrefix vs currentPrefix.
    const {unmount} = renderPicker({currentPrefix: 'alice/', allowCurrentParent: false});
    expect(screen.getByRole('button', {name: /copy here/i})).toBeDisabled();
    expect(screen.getByText(/already here/i)).toBeInTheDocument();
    unmount();

    renderPicker({currentPrefix: 'alice/', allowCurrentParent: true});
    expect(screen.getByRole('button', {name: /copy here/i})).toBeEnabled();
  });

  it("blocks confirming inside a copied folder's own subtree", async () => {
    listing({'alice/photos/': pageOf([folder('alice/photos/sub/', 'sub')])});
    renderPicker({
      items: [{type: 'folder', prefix: 'alice/photos/'}],
      currentPrefix: 'alice/',
      rootPrefix: 'alice/photos/',
      allowCurrentParent: true,
      selfMessage: "You can't copy a folder into itself."
    });
    // Browsing starts at rootPrefix = the folder's own prefix → inside its subtree.
    expect(screen.getByRole('button', {name: /copy here/i})).toBeDisabled();
    expect(await screen.findByText(/can't copy a folder into itself/i)).toBeInTheDocument();
  });

  it('shows existing files as non-interactive, unselectable rows', async () => {
    listing({'alice/': pageOf([folder('alice/archive/', 'archive')], [file('alice/report.csv', 'report.csv')])});
    renderPicker();

    // The file is visible so the destination's contents aren't a mystery…
    expect(await screen.findByText('report.csv')).toBeInTheDocument();
    // …but it's not a button (you pick a folder, not a file).
    expect(screen.queryByRole('button', {name: /report\.csv/i})).not.toBeInTheDocument();
    // The folder is still navigable.
    expect(screen.getByRole('button', {name: /open folder archive/i})).toBeInTheDocument();
  });

  it('shows the empty message only when there are no folders and no files', async () => {
    const {unmount} = renderPicker(); // default listing = empty
    expect(await screen.findByText(/this folder is empty/i)).toBeInTheDocument();
    unmount();

    listing({'alice/': pageOf([], [file('alice/a.txt', 'a.txt')])});
    renderPicker();
    expect(await screen.findByText('a.txt')).toBeInTheDocument();
    expect(screen.queryByText(/this folder is empty/i)).not.toBeInTheDocument();
  });

  it('shows a connection selector and browses/confirms into another connection', async () => {
    const destinations = [
      {id: 'personal', bucket: 'us', rootPrefix: 'alice/', label: 'My Files', kind: 'personal' as const},
      {id: 'team', bucket: 'shared', rootPrefix: 'team/', label: 'team', kind: 'shared' as const}
    ];
    // No selector with a single (implicit) destination.
    const {unmount} = renderPicker();
    expect(screen.queryByLabelText(/destination connection/i)).not.toBeInTheDocument();
    unmount();

    const {user, onConfirm} = renderPicker({destinations, currentPrefix: 'alice/docs/'});
    const selector = screen.getByLabelText(/destination connection/i);
    // Default selection is the source space (us / alice/).
    await waitFor(() => expect(mock.listFiles).toHaveBeenCalledWith('us', 'alice/', undefined));

    // Switch to the shared connection: browsing re-targets its bucket + root.
    await user.selectOptions(selector, 'team');
    await waitFor(() => expect(mock.listFiles).toHaveBeenCalledWith('shared', 'team/', undefined));

    // Confirming reports the shared bucket as the destination bucket.
    await user.click(screen.getByRole('button', {name: /copy here/i}));
    expect(onConfirm).toHaveBeenCalledWith('team/', 'shared', undefined);
  });
});

// SPEC-124 FR-003. The mode is opt-in precisely BECAUSE three shipped dialogs depend
// on files being inert, so the first test here is a regression guard on them, not a
// feature test.
describe('DestinationPicker — selectable-files mode (SPEC-124)', () => {
  const selectable = {selectableFiles: true, markerKey: 'alice/DO_NOT_DELETE.txt', allowCurrentParent: true};

  it('leaves the three default-mode callers (Move / Copy / Save results) unaffected', async () => {
    listing({'alice/': pageOf([folder('alice/archive/', 'archive')], [file('alice/report.csv', 'report.csv')])});
    // Every shipped caller omits `selectableFiles`, so the default IS their behaviour:
    // the file is visible, not a button, and not selectable by any means.
    const {user, onConfirm} = renderPicker({currentPrefix: 'alice/docs/'});

    expect(await screen.findByText('report.csv')).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /report\.csv/i})).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /select file/i})).not.toBeInTheDocument();
    // The list keeps its destination-shaped label when the caller doesn't override it.
    expect(screen.getByRole('list', {name: 'Destination folders'})).toBeInTheDocument();

    // And confirm still reports a folder — never a file key — for those callers.
    await user.click(screen.getByRole('button', {name: /copy here/i}));
    expect(onConfirm).toHaveBeenCalledWith('alice/', 'us', undefined);
  });

  it('selects a file, deselects it, and clears the selection on navigation', async () => {
    listing({
      'alice/': pageOf([folder('alice/archive/', 'archive')], [file('alice/report.csv', 'report.csv')]),
      'alice/archive/': pageOf([], [file('alice/archive/old.csv', 'old.csv')])
    });
    const {user, onConfirm} = renderPicker({...selectable, currentPrefix: 'alice/'});

    // No selection → the browsed folder is the target.
    const row = await screen.findByRole('button', {name: 'Select file report.csv'});
    expect(row).toHaveAttribute('aria-pressed', 'false');

    // Select → the file is the target.
    await user.click(row);
    expect(screen.getByRole('button', {name: 'Select file report.csv'})).toHaveAttribute('aria-pressed', 'true');

    // Click again → deselected, target back to the folder.
    await user.click(screen.getByRole('button', {name: 'Select file report.csv'}));
    expect(screen.getByRole('button', {name: 'Select file report.csv'})).toHaveAttribute('aria-pressed', 'false');

    // Re-select, then navigate: the selection must NOT survive into the new folder.
    await user.click(screen.getByRole('button', {name: 'Select file report.csv'}));
    await user.click(screen.getByRole('button', {name: /open folder archive/i}));
    const moved = await screen.findByRole('button', {name: 'Select file old.csv'});
    expect(moved).toHaveAttribute('aria-pressed', 'false');

    await user.click(screen.getByRole('button', {name: /copy here/i}));
    expect(onConfirm).toHaveBeenCalledWith('alice/archive/', 'us', undefined);
  });

  it('confirms with the selected file key only while a file is selected', async () => {
    listing({'alice/': pageOf([], [file('alice/report.csv', 'report.csv')])});
    const {user, onConfirm} = renderPicker({...selectable, currentPrefix: 'alice/'});

    await user.click(await screen.findByRole('button', {name: 'Select file report.csv'}));
    await user.click(screen.getByRole('button', {name: /copy here/i}));
    expect(onConfirm).toHaveBeenCalledWith('alice/', 'us', 'alice/report.csv');
  });

  it('reports the target on mount and on every navigation/selection change', async () => {
    listing({
      'alice/': pageOf([folder('alice/archive/', 'archive')], [file('alice/report.csv', 'report.csv')]),
      'alice/archive/': pageOf([], [file('alice/archive/old.csv', 'old.csv')])
    });
    const onTargetChange = vi.fn();
    const {user} = renderPicker({...selectable, currentPrefix: 'alice/', onTargetChange});

    expect(onTargetChange).toHaveBeenCalledWith({prefix: 'alice/', fileKey: undefined});

    await user.click(await screen.findByRole('button', {name: 'Select file report.csv'}));
    expect(onTargetChange).toHaveBeenLastCalledWith({prefix: 'alice/', fileKey: 'alice/report.csv'});

    await user.click(screen.getByRole('button', {name: /open folder archive/i}));
    expect(onTargetChange).toHaveBeenLastCalledWith({prefix: 'alice/archive/', fileKey: undefined});
  });

  it('hides the prefix marker, so it can never be selected as a target', async () => {
    listing({
      'alice/': pageOf(
        [],
        [file('alice/DO_NOT_DELETE.txt', 'DO_NOT_DELETE.txt'), file('alice/report.csv', 'report.csv')]
      )
    });
    renderPicker({...selectable, currentPrefix: 'alice/'});

    expect(await screen.findByRole('button', {name: 'Select file report.csv'})).toBeInTheDocument();
    expect(screen.queryByText('DO_NOT_DELETE.txt')).not.toBeInTheDocument();
  });

  it('disables confirm in an empty folder, and only in selectable-files mode', async () => {
    // Empty listing is the default mock.
    const {unmount} = renderPicker({...selectable, currentPrefix: 'alice/'});
    await waitFor(() => expect(screen.getByRole('button', {name: /copy here/i})).toBeDisabled());
    expect(screen.getByText(/nothing here to check/i)).toBeInTheDocument();
    unmount();

    // Save results targets an empty folder all the time — the guard must not leak.
    renderPicker({currentPrefix: 'alice/', allowCurrentParent: true});
    await waitFor(() => expect(screen.getByRole('button', {name: /copy here/i})).toBeEnabled());
  });

  it('renders a listing failure through toUserMessage, never the raw AWS text', async () => {
    mock.listFiles.mockResolvedValue({
      success: false,
      error: {message: 'User: arn:aws:sts::1:assumed-role/x is not authorized', code: 'AccessDenied'}
    });
    renderPicker({...selectable, currentPrefix: 'alice/'});

    expect(await screen.findByRole('alert')).toHaveTextContent(/don't have permission/i);
    expect(screen.queryByText(/assumed-role/)).not.toBeInTheDocument();
  });
});
