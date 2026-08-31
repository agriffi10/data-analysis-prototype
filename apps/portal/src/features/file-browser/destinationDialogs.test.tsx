import {beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {CopyDialog} from './CopyDialog';
import {DestinationPicker} from './DestinationPicker';
import {MoveDialog} from './MoveDialog';
import type {SelectableItem} from './selectionContext';
import type {FileListPage, S3FileItem, S3FolderItem} from '../../types/s3.types';
import * as service from './fileBrowser.service';

// ─── from CopyDialog.test.tsx ───
vi.mock('./fileBrowser.service', async (importActual) => {
  const actual = await importActual<typeof service>();
  return {...actual, listFiles: vi.fn()};
});
describe('CopyDialog', () => {
  // Integration style (react.md §21): render the REAL CopyDialog → real
  // DestinationPicker → real useFileBrowser, mocking ONLY the AWS boundary
  // (listFiles). Pure helpers stay real via importActual.

  const mock = vi.mocked(service);

  const folder = (prefix: string, name: string): S3FolderItem => ({type: 'folder', prefix, name});
  const ok = <T,>(data: T) => ({success: true as const, data});
  const pageOf = (folders: S3FolderItem[] = []): FileListPage => ({files: [], folders, isTruncated: false});

  function renderDialog(props?: Partial<React.ComponentProps<typeof CopyDialog>>) {
    const onCopy = vi.fn();
    const onCancel = vi.fn();
    const result = renderWithProviders(
      <CopyDialog
        bucket="us"
        items={[{type: 'file', key: 'alice/docs/f.txt'} satisfies SelectableItem]}
        rootPrefix="alice/"
        rootLabel="My Files"
        currentPrefix="alice/docs/"
        onCopy={onCopy}
        onCancel={onCancel}
        {...props}
      />
    );
    return {...result, onCopy, onCancel};
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mock.listFiles.mockResolvedValue(ok(pageOf()));
  });

  describe('CopyDialog — destination picker', () => {
    it('copies to the browsed prefix, including the current parent (same-folder allowed)', async () => {
      // Browse starts at the root; the current parent is the root here, and Copy
      // permits it (→ same-folder auto-number), so "Copy here" is enabled.
      const {user, onCopy} = renderDialog({currentPrefix: 'alice/'});
      const copyHere = screen.getByRole('button', {name: /copy here/i});
      expect(copyHere).toBeEnabled();
      await user.click(copyHere);
      expect(onCopy).toHaveBeenCalledWith('alice/', 'us', undefined);
    });

    it('filters protected (athenaresults) and the folders being copied from the picker', async () => {
      mock.listFiles.mockResolvedValue(
        ok(
          pageOf([
            folder('alice/athenaresults/', 'athenaresults'),
            folder('alice/photos/', 'photos'),
            folder('alice/docs2/', 'docs2')
          ])
        )
      );
      renderDialog({items: [{type: 'folder', prefix: 'alice/photos/'}], currentPrefix: 'alice/'});
      expect(await screen.findByRole('button', {name: /open folder docs2/i})).toBeInTheDocument();
      expect(screen.queryByRole('button', {name: /open folder athenaresults/i})).not.toBeInTheDocument();
      expect(screen.queryByRole('button', {name: /open folder photos/i})).not.toBeInTheDocument();
    });
  });

  describe('CopyDialog — same-folder name prompt', () => {
    function promptProps() {
      const onConfirm = vi.fn();
      const onCancel = vi.fn();
      return {
        onConfirm,
        onCancel,
        sameFolderPrompt: {
          kind: 'file' as const,
          proposedName: 'report (1).pdf',
          validate: (name: string) => (name.includes('/') ? "no '/'" : name.trim() ? null : 'empty'),
          onConfirm,
          onCancel
        }
      };
    }

    it('disables Copy when the proposed name is invalid', async () => {
      const {sameFolderPrompt} = promptProps();
      const {user} = renderDialog({sameFolderPrompt});
      const input = screen.getByLabelText(/name for the copy/i);
      await user.clear(input);
      await user.type(input, 'a/b');
      expect(screen.getByRole('button', {name: /^copy$/i})).toBeDisabled();
    });
  });
});

// ─── from DestinationPicker.test.tsx ───

describe('DestinationPicker', () => {
  // Integration style (react.md §21): render the REAL DestinationPicker driving the
  // REAL useFileBrowser hook, and mock ONLY the AWS boundary (listFiles). Navigation
  // re-queries the mocked service per browsed prefix; the pure helpers stay real via
  // importActual.

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

  // `Props` used to be a union (selectable files required an exact marker key), which
  // `Partial<>` can't
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
      listing({'alice/': pageOf([folder('alice/backups/', 'backups')], [file('alice/report.csv', 'report.csv')])});
      renderPicker();

      // The file is visible so the destination's contents aren't a mystery…
      expect(await screen.findByText('report.csv')).toBeInTheDocument();
      // …but it's not a button (you pick a folder, not a file).
      expect(screen.queryByRole('button', {name: /report\.csv/i})).not.toBeInTheDocument();
      // The folder is still navigable.
      expect(screen.getByRole('button', {name: /open folder backups/i})).toBeInTheDocument();
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
      await waitFor(() =>
        expect(mock.listFiles).toHaveBeenCalledWith('us', 'alice/', undefined, expect.any(AbortSignal))
      );

      // Switch to the shared connection: browsing re-targets its bucket + root.
      await user.selectOptions(selector, 'team');
      await waitFor(() =>
        expect(mock.listFiles).toHaveBeenCalledWith('shared', 'team/', undefined, expect.any(AbortSignal))
      );

      // Confirming reports the shared bucket as the destination bucket.
      await user.click(screen.getByRole('button', {name: /copy here/i}));
      expect(onConfirm).toHaveBeenCalledWith('team/', 'shared', undefined);
    });
  });

  // SPEC-173 FR-002/FR-008. The saved-queries folder is an ORDINARY paste target — the
  // one thing that removes it is the `query` flag, and that is presentation: it removes a
  // way of ASKING, and revokes no grant.
  describe('DestinationPicker — the saved_queries/ folder (SPEC-173)', () => {
    const withFolder = () =>
      listing({
        'alice/': pageOf([folder('alice/saved_queries/', 'saved_queries'), folder('alice/docs/', 'docs')]),
        'alice/saved_queries/': pageOf()
      });

    it('IS offered as a destination, and can be pasted into', async () => {
      withFolder();
      const {user, onConfirm} = renderPicker({currentPrefix: 'alice/docs/'});

      await user.click(await screen.findByRole('button', {name: 'Open folder saved_queries'}));
      await user.click(screen.getByRole('button', {name: /copy here/i}));

      expect(onConfirm).toHaveBeenCalledWith('alice/saved_queries/', 'us', undefined);
    });
  });

  // SPEC-124 FR-003. The mode is opt-in precisely BECAUSE three shipped dialogs depend
  // on files being inert, so the first test here is a regression guard on them, not a
  // feature test.
  describe('DestinationPicker — selectable-files mode (SPEC-124)', () => {
    const selectable = {selectableFiles: true, allowCurrentParent: true};

    it('leaves the three default-mode callers (Move / Copy / Save results) unaffected', async () => {
      listing({'alice/': pageOf([folder('alice/backups/', 'backups')], [file('alice/report.csv', 'report.csv')])});
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

    it('confirms with the selected file key only while a file is selected', async () => {
      listing({'alice/': pageOf([], [file('alice/report.csv', 'report.csv')])});
      const {user, onConfirm} = renderPicker({...selectable, currentPrefix: 'alice/'});

      await user.click(await screen.findByRole('button', {name: 'Select file report.csv'}));
      await user.click(screen.getByRole('button', {name: /copy here/i}));
      expect(onConfirm).toHaveBeenCalledWith('alice/', 'us', 'alice/report.csv');
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
});

// ─── from MoveDialog.test.tsx ───

describe('MoveDialog', () => {
  // Integration style (react.md §21): render the REAL MoveDialog → real
  // DestinationPicker → real useFileBrowser, mocking ONLY the AWS boundary
  // (listFiles). Navigation re-queries the mocked service per browsed prefix.

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
    it('climbs back to the root via the ".." row and can move there', async () => {
      listing({'alice/': pageOf([folder('alice/backups/', 'backups')]), 'alice/backups/': pageOf()});
      const {user, onMove} = renderDialog();

      // No ".." at the root (already at the navigation floor).
      await screen.findByRole('button', {name: /open folder backups/i});
      expect(screen.queryByRole('button', {name: /go up to parent folder/i})).not.toBeInTheDocument();

      // Descend, then the ".." row appears and climbs back to the root.
      await user.click(screen.getByRole('button', {name: /open folder backups/i}));
      await waitFor(() =>
        expect(mock.listFiles).toHaveBeenLastCalledWith('us', 'alice/backups/', undefined, expect.any(AbortSignal))
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

    it('hides the folders being moved (no descending into them)', async () => {
      listing({'alice/': pageOf([folder('alice/backups/', 'backups'), folder('alice/photos/', 'photos')])});
      renderDialog({items: [{type: 'folder', prefix: 'alice/photos/'}], currentPrefix: 'alice/'});
      expect(await screen.findByRole('button', {name: /open folder backups/i})).toBeInTheDocument();
      expect(screen.queryByRole('button', {name: /open folder photos/i})).not.toBeInTheDocument();
    });
  });
});
