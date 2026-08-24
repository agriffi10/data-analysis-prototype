import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {screen, within, waitFor} from '@testing-library/react';
import type {ReactElement} from 'react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {FileBrowser} from './FileBrowser';
import {UploadQueueProvider} from './UploadQueueProvider';
import {FileOpsInFlightProvider} from './FileOpsInFlightProvider';
import {UPLOAD_CONCURRENCY} from './upload.types';
import * as service from './fileBrowser.service';
import {triggerBrowserDownload} from './fileBrowser.download';
import {getSessionCredentials} from '../../lib/awsCredentials';
import * as dqService from '../data-quality/dataQuality.service';
import * as sendService from '../file-send/fileSend.service';
import {submitFileOperation} from './fileOps.service';
import type {FileListPage, S3FileItem, S3FolderItem} from '../../types/s3.types';

// Integration style (react.md §21): render the REAL FileBrowser tree — real
// hooks (useFileBrowser/useDelete/useMove/useCopy/useFileUpload), real child
// dialogs (Create/Delete/Rename/Move/Copy/Metadata) — and mock ONLY the AWS
// service boundary. The pure helpers (validateFolderName/uploadPercent/…) stay
// real via importActual so the hooks behave normally.
vi.mock('./fileBrowser.service', async (importActual) => {
  const actual = await importActual<typeof service>();
  return {
    ...actual,
    listFiles: vi.fn(),
    getObjectMetadata: vi.fn(),
    deleteObjects: vi.fn(),
    deleteFolder: vi.fn(),
    moveObject: vi.fn(),
    moveFolder: vi.fn(),
    copyObject: vi.fn(),
    copyFolder: vi.fn(),
    objectExists: vi.fn(),
    getDownloadUrl: vi.fn(),
    uploadFile: vi.fn(),
    createFolder: vi.fn()
  };
});
// triggerBrowserDownload navigates the browser — stub the side effect (its own
// unit test covers the anchor mechanics).
vi.mock('./fileBrowser.download', () => ({triggerBrowserDownload: vi.fn()}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}})
}));
// SPEC-113: the data-quality enqueue is another AWS boundary — mock it, and let the
// real DataQualityDialog and useDataQualityCheck render.
vi.mock('../data-quality/dataQuality.service', () => ({enqueueQualityCheck: vi.fn()}));
// SPEC-167: the send's enqueue is the same kind of boundary — mock it, and let the real
// SendFilesDialog, useFileSend and the suggestion sources render. The two suggestion services
// are mocked because they are AWS reads too, not because the field is being avoided.
vi.mock('../file-send/fileSend.service', () => ({enqueueFileSend: vi.fn()}));
// SPEC-190: the file-operations enqueue is the same kind of boundary. Anything that is not
// exactly one file now goes through it rather than through the service mocks above.
vi.mock('./fileOps.service', () => ({submitFileOperation: vi.fn().mockResolvedValue({success: true})}));
vi.mock('../user-directory/userDirectory.service', () => ({
  getUserDirectory: vi.fn().mockResolvedValue({success: true, data: {usernames: ['bob'], generatedAt: null}}),
  DIRECTORY_KEY: '_directory/usernames.json'
}));
vi.mock('../shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn().mockResolvedValue({
    success: true,
    data: {version: 1, connections: [{name: 'finance', role: 'member', status: 'active'}]}
  }),
  enqueueSharedSpaceRequest: vi.fn()
}));

const mock = vi.mocked(service);
const mockQualityCheck = vi.mocked(dqService.enqueueQualityCheck);
const mockSend = vi.mocked(sendService.enqueueFileSend);
const mockSubmitFileOp = vi.mocked(submitFileOperation);

// ── Builders ────────────────────────────────────────────────────────────────
const file = (name: string, over: Partial<S3FileItem> = {}): S3FileItem => ({
  type: 'file',
  key: `alice/${name}`,
  name,
  size: 2048,
  lastModified: new Date('2026-03-04T00:00:00Z'),
  ...over
});
const folder = (name: string, over: Partial<S3FolderItem> = {}): S3FolderItem => ({
  type: 'folder',
  prefix: `alice/${name}/`,
  name,
  ...over
});
const page = (over: Partial<FileListPage> = {}): FileListPage => ({
  files: [file('report.csv'), file('notes.txt')],
  folders: [folder('docs')],
  isTruncated: false,
  ...over
});
const ok = <T,>(data: T) => ({success: true as const, data});
const fail = (message: string) => ({success: false as const, error: {message}});

/** Renders the browser inside the app provider stack + the real upload queue.
 *  Authenticated/writable personal space by default. */
function renderBrowser(props: Partial<Parameters<typeof FileBrowser>[0]> = {}): ReturnType<typeof renderWithProviders> {
  const ui: ReactElement = (
    <UploadQueueProvider>
      <FileOpsInFlightProvider>
        <FileBrowser
          bucket="my-bucket"
          prefix="alice/"
          rootPrefix="alice/"
          rootLabel="My Files"
          writable
          username="alice"
          {...props}
        />
      </FileOpsInFlightProvider>
    </UploadQueueProvider>
  );
  return renderWithProviders(ui);
}

beforeEach(() => {
  vi.clearAllMocks();
  window.innerWidth = 1024; // ≥900 → desktop table (not the mobile card list)
  mock.listFiles.mockResolvedValue(ok(page()));
  mock.getObjectMetadata.mockResolvedValue(
    ok({
      key: 'alice/report.csv',
      contentType: 'text/csv',
      size: 2048,
      lastModified: new Date('2026-03-04T00:00:00Z'),
      etag: '"abc"',
      storageClass: 'STANDARD',
      userMetadata: {}
    })
  );
  mock.getDownloadUrl.mockResolvedValue(ok({url: 'https://signed/report.csv', expiresAt: '2026-03-04T01:00:00Z'}));
  mock.deleteObjects.mockResolvedValue(ok({deleted: ['alice/report.csv'], errors: []}));
  mock.deleteFolder.mockResolvedValue(ok({deleted: ['alice/docs/x'], errors: []}));
  mock.moveObject.mockResolvedValue(ok({destKey: 'alice/docs/notes.txt'}));
  mock.moveFolder.mockResolvedValue(ok({moved: ['alice/docs/x'], errors: []}));
  mock.copyObject.mockResolvedValue(ok({destKey: 'alice/docs/notes.txt'}));
  mock.copyFolder.mockResolvedValue(ok({copied: ['alice/docs/x'], errors: []}));
  mock.objectExists.mockResolvedValue(ok(false));
  mock.createFolder.mockResolvedValue(ok({prefix: 'alice/new/'}));
  mock.uploadFile.mockResolvedValue(ok({key: 'alice/up.txt'}));
  mockQualityCheck.mockResolvedValue(ok({requestId: 'req-1'}));
});

afterEach(() => {
  window.innerWidth = 1024;
});

describe('FileBrowser — listing states', () => {
  it('shows a loading indicator until the listing resolves', () => {
    mock.listFiles.mockReturnValue(new Promise(() => {})); // never resolves
    renderBrowser();
    expect(screen.getByRole('status', {name: 'Loading'})).toBeInTheDocument();
    expect(screen.queryByText('report.csv')).not.toBeInTheDocument();
  });

  it('renders a populated folder: folders before files, with size and modified date', async () => {
    renderBrowser();
    const list = await screen.findByRole('list', {name: 'File list'});
    const names = within(list)
      .getAllByText(/^(docs|report\.csv|notes\.txt)$/)
      .map((el) => el.textContent);
    // Folder first, then files sorted alphabetically (notes before report).
    expect(names).toEqual(['docs', 'notes.txt', 'report.csv']);
    expect(screen.getAllByText('2.0 KB')).toHaveLength(2); // both files, 2048 B
    expect(screen.getAllByText(/2026/).length).toBeGreaterThan(0);
  });

  it('hides the app-managed folders from a listing that contains them (SPEC-113 FR-004)', async () => {
    mock.listFiles.mockResolvedValue(
      ok(page({folders: [folder('docs'), folder('user_settings'), folder('_data-quality-reports')]}))
    );
    renderBrowser();
    const list = await screen.findByRole('list', {name: 'File list'});
    expect(within(list).getByText('docs')).toBeInTheDocument();
    expect(within(list).queryByText('_data-quality-reports')).not.toBeInTheDocument();
    expect(within(list).queryByText('user_settings')).not.toBeInTheDocument();
  });

  it('shows an empty-folder message when the listing is empty', async () => {
    mock.listFiles.mockResolvedValue(ok(page({files: [], folders: []})));
    renderBrowser();
    expect(await screen.findByText('This folder is empty')).toBeInTheDocument();
  });

  it('surfaces a listing error as a user-safe alert, never the raw AWS text', async () => {
    // SPEC-106: an unrecognized raw message maps to the generic user-safe fallback;
    // the raw text ('on fire') never reaches the DOM.
    mock.listFiles.mockResolvedValue(fail('Bucket is on fire'));
    renderBrowser();
    const alert = await screen.findByRole('alert');
    expect(within(alert).getByText('Failed to load files')).toBeInTheDocument();
    expect(alert).toHaveTextContent(/contact the administrator/i);
    expect(alert).not.toHaveTextContent(/on fire/i);
  });

  it('offers "Refresh access" for a just-added shared space and re-lists on click', async () => {
    mock.listFiles.mockResolvedValue(fail('User is not authorized to perform s3:ListBucket'));
    const {user} = renderBrowser({spaceKind: 'shared'});
    const refresh = await screen.findByRole('button', {name: 'Refresh access'});
    mock.listFiles.mockResolvedValue(ok(page()));
    await user.click(refresh);
    expect(getSessionCredentials).toHaveBeenCalledWith(true);
    expect(await screen.findByText('report.csv')).toBeInTheDocument();
  });

  it('paginates with "Load more"', async () => {
    mock.listFiles
      .mockResolvedValueOnce(
        ok(page({files: [file('page1.csv')], folders: [], isTruncated: true, nextContinuationToken: 't1'}))
      )
      .mockResolvedValueOnce(ok(page({files: [file('page2.csv')], folders: [], isTruncated: false})));
    const {user} = renderBrowser();
    await screen.findByText('page1.csv');
    await user.click(screen.getByRole('button', {name: 'Load more'}));
    expect(await screen.findByText('page2.csv')).toBeInTheDocument();
    expect(mock.listFiles).toHaveBeenCalledTimes(2);
    expect(mock.listFiles).toHaveBeenLastCalledWith('my-bucket', 'alice/', 't1', expect.any(AbortSignal));
  });
});

describe('FileBrowser — navigation', () => {
  it('drills into a folder and back out via the breadcrumb', async () => {
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'Open folder docs'}));
    await waitFor(() =>
      expect(mock.listFiles).toHaveBeenLastCalledWith('my-bucket', 'alice/docs/', undefined, expect.any(AbortSignal))
    );
    expect(screen.getByText('docs', {selector: '[aria-current="page"]'})).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'My Files'}));
    await waitFor(() =>
      expect(mock.listFiles).toHaveBeenLastCalledWith('my-bucket', 'alice/', undefined, expect.any(AbortSignal))
    );
  });

  it('hides the raw username segment behind rootLabel and never shows Home', async () => {
    renderBrowser();
    await screen.findByText('report.csv');
    expect(screen.getByText('My Files')).toBeInTheDocument();
    expect(screen.queryByText('Home')).not.toBeInTheDocument();
    expect(screen.queryByText('alice')).not.toBeInTheDocument();
  });

  it('shows a parent-folder (..) row below the root and navigates up on click', async () => {
    const {user} = renderBrowser({prefix: 'alice/docs/'});
    const up = await screen.findByRole('button', {name: /parent folder/i});
    await user.click(up);
    await waitFor(() =>
      expect(mock.listFiles).toHaveBeenLastCalledWith('my-bucket', 'alice/', undefined, expect.any(AbortSignal))
    );
  });

  it('does not show a .. row at the space root', async () => {
    renderBrowser();
    await screen.findByText('report.csv');
    expect(screen.queryByRole('button', {name: /parent folder/i})).not.toBeInTheDocument();
  });
});

describe('FileBrowser — download', () => {
  it('downloads a file on double-click', async () => {
    const {user} = renderBrowser();
    await user.dblClick(await screen.findByText('report.csv'));
    await waitFor(() => expect(mock.getDownloadUrl).toHaveBeenCalled());
    expect(triggerBrowserDownload).toHaveBeenCalledWith('https://signed/report.csv');
  });

  it('surfaces a download failure inline', async () => {
    mock.getDownloadUrl.mockResolvedValue(fail('gone'));
    const {user} = renderBrowser();
    await user.dblClick(await screen.findByText('report.csv'));
    expect(await screen.findByText(/Could not download report\.csv/)).toBeInTheDocument();
  });

  it('exposes a per-row Download button only in read-only browse', async () => {
    renderBrowser({writable: false, username: undefined});
    expect(await screen.findByRole('button', {name: 'Download report.csv'})).toBeInTheDocument();
  });

  it('has no per-row Download in the authenticated flow (toolbar only)', async () => {
    renderBrowser();
    await screen.findByText('report.csv');
    expect(screen.queryByRole('button', {name: 'Download report.csv'})).not.toBeInTheDocument();
  });
});

describe('FileBrowser — details drawer', () => {
  it('opens the file metadata drawer from its Details action', async () => {
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'Details for report.csv'}));
    expect(await screen.findByRole('dialog', {name: 'Details for report.csv'})).toBeInTheDocument();
    await waitFor(() => expect(mock.getObjectMetadata).toHaveBeenCalled());
  });

  it('opens the folder details drawer from its Details action', async () => {
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'Details for docs'}));
    expect(await screen.findByRole('dialog', {name: 'Details for docs'})).toBeInTheDocument();
  });
});

describe('FileBrowser — write controls', () => {
  it('hides New folder + Upload in read-only browse', async () => {
    renderBrowser({writable: false, username: undefined});
    await screen.findByText('report.csv');
    expect(screen.queryByRole('button', {name: 'New folder'})).not.toBeInTheDocument();
  });

  it('shows New folder + Upload when writable', async () => {
    renderBrowser();
    expect(await screen.findByRole('button', {name: 'New folder'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Upload'})).toBeInTheDocument();
  });

  it('creates a folder through the New folder dialog', async () => {
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'New folder'}));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('textbox'), 'photos');
    await user.click(within(dialog).getByRole('button', {name: /create/i}));
    await waitFor(() =>
      expect(mock.createFolder).toHaveBeenCalledWith(expect.objectContaining({name: 'photos', prefix: 'alice/'}))
    );
  });
});

describe('FileBrowser — selection + delete', () => {
  it('has no selection checkboxes in read-only browse', async () => {
    renderBrowser({writable: false, username: undefined});
    await screen.findByText('report.csv');
    expect(screen.queryByRole('checkbox', {name: 'Select all'})).not.toBeInTheDocument();
  });

  it('deletes the selected items after confirmation and reports the count', async () => {
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(screen.getByRole('button', {name: 'Delete selected items'}));
    // Nothing deleted until the confirm dialog is accepted.
    expect(mock.deleteObjects).not.toHaveBeenCalled();
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    await waitFor(() =>
      expect(mock.deleteObjects).toHaveBeenCalledWith(expect.objectContaining({keys: ['alice/report.csv']}))
    );
    expect(await screen.findByText(/Deleted 1/)).toBeInTheDocument();
  });

  it('select-all toggles every row and Delete is disabled with nothing selected', async () => {
    const {user} = renderBrowser();
    const del = await screen.findByRole('button', {name: 'Delete selected items'});
    expect(del).toBeDisabled();
    await user.click(screen.getByRole('checkbox', {name: 'Select all'}));
    expect(screen.getByRole('checkbox', {name: 'Select report.csv'})).toBeChecked();
    expect(screen.getByRole('checkbox', {name: 'Select folder docs'})).toBeChecked();
    expect(del).toBeEnabled();
  });

  it('reports a partial delete failure with friendly, mapped text (SPEC-106)', async () => {
    mock.deleteObjects.mockResolvedValue(
      ok({deleted: [], errors: [{key: 'alice/report.csv', message: 'Access Denied', code: 'AccessDenied'}]})
    );
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(screen.getByRole('button', {name: 'Delete selected items'}));
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    // The reason is the mapped message, not raw S3 text.
    expect(await screen.findByText(/report\.csv — You don't have permission/)).toBeInTheDocument();
    expect(screen.queryByText(/report\.csv — Access Denied/)).not.toBeInTheDocument();
  });

  // ── SPEC-186 FR-002 ────────────────────────────────────────────────────────
  // The service has always refused these, but only AFTER the user read "Delete the folder
  // … and everything inside it? This can't be undone." and pressed Delete. Removing
  // `deleteDisabledReason`/`moveDisabledReason` from SelectionToolbar, or dropping
  // `undeletableSelectionRefusal`, reddens all three of these.
  describe('an undeletable root folder refuses BEFORE the confirm', () => {
    const withSavedQueries = {
      files: [file('report.csv')],
      folders: [folder('saved_queries'), folder('docs')],
      isTruncated: false
    };

    it('states the reason on Delete and opens no confirm dialog at all', async () => {
      mock.listFiles.mockResolvedValue(ok(page(withSavedQueries)));
      const {user} = renderBrowser();
      await user.click(await screen.findByRole('checkbox', {name: 'Select folder saved_queries'}));

      const del = screen.getByRole('button', {name: 'Delete selected items'});
      expect(del).toHaveAttribute('aria-disabled', 'true');
      expect(del).toHaveAttribute('title', 'Saved queries live in this folder, so it can’t be deleted.');
      // aria-disabled, NOT disabled: the reason has to stay reachable in the tab order.
      expect(del).not.toBeDisabled();
      // …and the reason is a DESCRIPTION, never the accessible name (SPEC-172's registry rule).
      expect(del).toHaveAccessibleName('Delete selected items');

      await user.click(del);
      // `alertdialog` is the role the delete confirm actually carries — querying only for
      // `dialog` would pass whatever happened, which is the whole point of this assertion.
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(mock.deleteFolder).not.toHaveBeenCalled();
    });

    it('states the MOVE reason on Move, which is worded for a rename too', async () => {
      mock.listFiles.mockResolvedValue(ok(page(withSavedQueries)));
      const {user} = renderBrowser();
      await user.click(await screen.findByRole('checkbox', {name: 'Select folder saved_queries'}));

      const move = screen.getByRole('button', {name: 'Move selected items'});
      expect(move).toHaveAttribute('title', 'Saved queries live in this folder, so it can’t be moved or renamed.');
      await user.click(move);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(mock.moveFolder).not.toHaveBeenCalled();
    });

    // Found in review: refusing on the FIRST protected item killed Delete for a selection the
    // service would have carried out per item — and at a space root, select-all takes in
    // `athenaresults/`, `saved_queries/` and `archive/` together, so select-all → Delete went
    // dead with a reason about saved queries. Restoring the first-match version reddens this.
    it('does NOT refuse a mixed selection — the service is per item, and it does something', async () => {
      mock.listFiles.mockResolvedValue(ok(page(withSavedQueries)));
      const {user} = renderBrowser();
      await user.click(await screen.findByRole('checkbox', {name: 'Select folder saved_queries'}));
      await user.click(screen.getByRole('checkbox', {name: 'Select report.csv'}));

      const del = screen.getByRole('button', {name: 'Delete selected items'});
      expect(del).not.toHaveAttribute('aria-disabled');
      await user.click(del);
      expect(await screen.findByRole('alertdialog')).toBeInTheDocument();
    });

    it('refuses when EVERY selected folder is protected, and names one of them', async () => {
      mock.listFiles.mockResolvedValue(
        ok(page({files: [], folders: [folder('saved_queries'), folder('athenaresults')], isTruncated: false}))
      );
      const {user} = renderBrowser();
      await user.click(await screen.findByRole('checkbox', {name: 'Select folder saved_queries'}));
      await user.click(screen.getByRole('checkbox', {name: 'Select folder athenaresults'}));

      const del = screen.getByRole('button', {name: 'Delete selected items'});
      expect(del).toHaveAttribute('aria-disabled', 'true');
      expect(del).toHaveAttribute('title', 'Saved queries live in this folder, so it can’t be deleted.');
    });

    it('leaves an ordinary folder alone — the control is the guard, not the folder count', async () => {
      mock.listFiles.mockResolvedValue(ok(page(withSavedQueries)));
      const {user} = renderBrowser();
      await user.click(await screen.findByRole('checkbox', {name: 'Select folder docs'}));

      const del = screen.getByRole('button', {name: 'Delete selected items'});
      expect(del).not.toHaveAttribute('aria-disabled');
      await user.click(del);
      // The confirm is an `alertdialog` — this is the control that the two cases above
      // must NOT reach.
      expect(await screen.findByRole('alertdialog')).toBeInTheDocument();
    });
  });
});

describe('FileBrowser — move / copy / rename', () => {
  it('moves selected items into a chosen folder', async () => {
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('checkbox', {name: 'Select notes.txt'}));
    await user.click(screen.getByRole('button', {name: 'Move selected items'}));
    // Real MoveDialog + DestinationPicker (scoped to the modal — the list behind
    // it also has an "Open folder docs" button): descend into docs/, then confirm.
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', {name: 'Open folder docs'}));
    await user.click(await within(dialog).findByRole('button', {name: 'Move here'}));
    await waitFor(() =>
      expect(mock.moveObject).toHaveBeenCalledWith(
        expect.objectContaining({sourceKey: 'alice/notes.txt', destKey: 'alice/docs/notes.txt'})
      )
    );
    expect(await screen.findByText(/Moved 1/)).toBeInTheDocument();
  });

  it('copies selected items into a chosen folder', async () => {
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('checkbox', {name: 'Select notes.txt'}));
    await user.click(screen.getByRole('button', {name: 'Copy selected items'}));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', {name: 'Open folder docs'}));
    await user.click(await within(dialog).findByRole('button', {name: 'Copy here'}));
    await waitFor(() => expect(mock.copyObject).toHaveBeenCalled());
    expect(await screen.findByText(/Copied 1/)).toBeInTheDocument();
  });

  it('renames a file from its details panel', async () => {
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'Details for report.csv'}));
    await user.click(await screen.findByRole('button', {name: 'Rename report.csv'}));
    const dialog = await screen.findByRole('dialog', {name: /rename/i});
    const input = within(dialog).getByRole('textbox');
    await user.clear(input);
    await user.type(input, 'renamed.csv');
    await user.click(within(dialog).getByRole('button', {name: /rename|save/i}));
    await waitFor(() => expect(mock.moveObject).toHaveBeenCalled());
  });

  it('renames a folder from its details panel — ENQUEUED, never a browser-side recursive move', async () => {
    // A folder rename is one CopyObject per contained object, so it cannot be bounded without
    // listing the folder first. It is the case a reader assumes is synchronous.
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'Details for docs'}));
    await user.click(await screen.findByRole('button', {name: 'Rename docs'}));
    const dialog = await screen.findByRole('dialog', {name: /rename/i});
    const input = within(dialog).getByRole('textbox');
    await user.clear(input);
    await user.type(input, 'archive');
    await user.click(within(dialog).getByRole('button', {name: /rename|save/i}));
    await waitFor(() => expect(mockSubmitFileOp).toHaveBeenCalled());
    expect(mock.moveFolder).not.toHaveBeenCalled();
    expect(mockSubmitFileOp.mock.calls[0][0]).toMatchObject({
      operation: 'move',
      source: {items: [{kind: 'folder', key: 'alice/docs/', targetName: 'archive'}]},
      destination: {prefix: 'alice/'},
      onConflict: 'refuse'
    });
  });

  it('shows the same-folder auto-number prompt for a copy into the current folder', async () => {
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('checkbox', {name: 'Select notes.txt'}));
    await user.click(screen.getByRole('button', {name: 'Copy selected items'}));
    const dialog = await screen.findByRole('dialog');
    // "Copy here" at the current folder (allowed for copy) → same-folder prompt.
    await user.click(within(dialog).getByRole('button', {name: 'Copy here'}));
    expect(await screen.findByText(/Copying into the same folder/)).toBeInTheDocument();
  });
});

describe('FileBrowser — upload', () => {
  it('enqueues chosen files onto the upload queue from the drawer', async () => {
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'Upload'}));
    const input = await screen.findByLabelText('Choose files');
    await user.upload(input, new File(['data'], 'up.txt', {type: 'text/plain'}));
    // The real UploadQueueProvider starts the queued item via uploadFile.
    await waitFor(() => expect(mock.uploadFile).toHaveBeenCalled());
  });
});

describe('FileBrowser — data quality (SPEC-113)', () => {
  const checkButton = () => screen.getByRole('button', {name: 'Check data quality of the selected item'});

  it('offers the check only on exactly one selected item', async () => {
    const {user} = renderBrowser();
    await screen.findByText('report.csv');

    // Empty selection — present but inert, like its Copy/Move/Delete neighbours.
    expect(checkButton()).toBeDisabled();

    await user.click(screen.getByRole('checkbox', {name: 'Select report.csv'}));
    expect(checkButton()).toBeEnabled();

    // Multi-select disables it again: one file or one folder per request in v1.
    await user.click(screen.getByRole('checkbox', {name: 'Select notes.txt'}));
    expect(checkButton()).toBeDisabled();
  });

  it('enqueues a check for a selected FILE, naming it and promising nothing changes', async () => {
    const {user} = renderBrowser();
    await screen.findByText('report.csv');
    await user.click(screen.getByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(checkButton());

    const dialog = await screen.findByRole('alertdialog', {name: 'Confirm data quality check'});
    // Shown space-relative, as the breadcrumbs are — not the raw `alice/` key.
    expect(within(dialog).getByText('report.csv')).toBeInTheDocument();
    expect(dialog).toHaveTextContent(/only reads/i);

    await user.click(within(dialog).getByRole('button', {name: 'Start check'}));
    await waitFor(() => expect(mockQualityCheck).toHaveBeenCalledTimes(1));
    expect(mockQualityCheck.mock.calls[0][0]).toMatchObject({
      // The SPACE ROOT identifies the space to the control plane, not the current folder.
      space: {kind: 'personal', bucket: 'my-bucket', prefix: 'alice/'},
      location: 'alice/report.csv'
    });
  });

  it('enqueues a check for a selected FOLDER, using its prefix as the location', async () => {
    const {user} = renderBrowser();
    await screen.findByText('docs');
    await user.click(screen.getByRole('checkbox', {name: 'Select folder docs'}));
    await user.click(checkButton());

    const dialog = await screen.findByRole('alertdialog', {name: 'Confirm data quality check'});
    await user.click(within(dialog).getByRole('button', {name: 'Start check'}));

    await waitFor(() => expect(mockQualityCheck).toHaveBeenCalledTimes(1));
    expect(mockQualityCheck.mock.calls[0][0]).toMatchObject({location: 'alice/docs/'});
  });

  it('sends the SPACE ROOT even when browsing a subfolder, not the current folder', async () => {
    // Every other test browses at the root, where the two are identical — so without
    // this one, sending `currentPrefix` as the space prefix would pass unnoticed and
    // validate-authorize would be handed a space that isn't one.
    const {user} = renderBrowser({prefix: 'alice/docs/'});
    await screen.findByText('report.csv');
    await user.click(screen.getByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(checkButton());
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Start check'}));

    await waitFor(() => expect(mockQualityCheck).toHaveBeenCalledTimes(1));
    expect(mockQualityCheck.mock.calls[0][0].space.prefix).toBe('alice/');
  });

  it('targets the shared-space root when browsing a shared space', async () => {
    const {user} = renderBrowser({
      spaceKind: 'shared',
      bucket: 'shared-bucket',
      prefix: 'team-data/',
      rootPrefix: 'team-data/',
      username: 'team-data'
    });
    await screen.findByText('report.csv');
    await user.click(screen.getByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(checkButton());
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Start check'}));

    await waitFor(() => expect(mockQualityCheck).toHaveBeenCalledTimes(1));
    expect(mockQualityCheck.mock.calls[0][0]).toMatchObject({
      space: {kind: 'shared', bucket: 'shared-bucket', prefix: 'team-data/'}
    });
  });

  it('drops the selection once the check is on its way, but not when cancelled', async () => {
    const {user} = renderBrowser();
    await screen.findByText('report.csv');
    const row = () => screen.getByRole('checkbox', {name: 'Select report.csv'});

    // Cancel leaves the selection alone — nothing happened, so nothing changes.
    await user.click(row());
    await user.click(checkButton());
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Cancel'}));
    expect(row()).toBeChecked();

    await user.click(checkButton());
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Start check'}));
    await waitFor(() => expect(row()).not.toBeChecked());
    expect(checkButton()).toBeDisabled();
  });

  it('keeps the selection when the enqueue fails, so the user can retry', async () => {
    mockQualityCheck.mockResolvedValue(fail('AWS.SimpleQueueService.NonExistentQueue'));
    const {user} = renderBrowser();
    await screen.findByText('report.csv');
    await user.click(screen.getByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(checkButton());
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Start check'}));

    await waitFor(() => expect(mockQualityCheck).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('checkbox', {name: 'Select report.csv'})).toBeChecked();
  });

  it('is absent entirely in read-only browse, where there is no space to check', async () => {
    renderBrowser({writable: false, username: undefined});
    await screen.findByText('report.csv');
    expect(screen.queryByRole('button', {name: 'Check data quality of the selected item'})).not.toBeInTheDocument();
  });

  it('is reachable on mobile as an icon-only control in the same toolbar', async () => {
    // ONE component tree: the label is hidden below tablet, the button is not.
    window.innerWidth = 500;
    const {user} = renderBrowser();
    await screen.findByText('report.csv');
    await user.click(screen.getByRole('checkbox', {name: 'Select report.csv'}));
    const button = checkButton();
    expect(button).toBeEnabled();
    expect(within(button).getByText('Check quality')).toHaveClass('hidden', 'tablet:inline');
    // And exactly one exists — it is not duplicated into the MobileActionBar.
    expect(screen.getAllByRole('button', {name: 'Check data quality of the selected item'})).toHaveLength(1);
  });
});

describe('FileBrowser — responsive', () => {
  it('renders the mobile card list and action bar below the tablet breakpoint', async () => {
    window.innerWidth = 500;
    renderBrowser();
    await screen.findByText('report.csv');
    // Card list has no desktop column header.
    expect(screen.queryByText('Modified')).not.toBeInTheDocument();
    expect(screen.getByLabelText('File actions')).toBeInTheDocument();
  });

  it('does not render the mobile action bar in read-only browse', async () => {
    window.innerWidth = 500;
    renderBrowser({writable: false, username: undefined});
    await screen.findByText('report.csv');
    expect(screen.queryByLabelText('File actions')).not.toBeInTheDocument();
  });
});

// ── SPEC-154 FR-003: a collision is RESOLVED through the UI ─────────────────
//
// The suite asserted the prompt APPEARS and stopped there; resolution was invoked on hook
// internals (`act(() => result.current.collision?.onOverwriteAll())`). So the
// retry-with-`overwrite: true` round trip had never been observed by a user-driven test — on
// a flow CLAUDE.md flags as non-atomic and collision-prone, where the wrong answer silently
// destroys a file.
describe('FileBrowser — resolving a collision through the UI (SPEC-154 FR-003)', () => {
  const collisionPrompt = () => screen.getByRole('alertdialog', {name: 'File already exists'});

  async function uploadInto(user: ReturnType<typeof renderBrowser>['user'], name = 'notes.txt') {
    await user.click(await screen.findByRole('button', {name: 'Upload'}));
    const input = await screen.findByLabelText('Choose files');
    await user.upload(input, new File(['data'], name, {type: 'text/plain'}));
  }

  it('drives an upload collision to Overwrite and retries with overwrite: true', async () => {
    // The provider routes on the error CODE, so the first result has to carry it.
    mock.uploadFile
      .mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}} as never)
      .mockResolvedValue(ok({key: 'alice/notes.txt'}) as never);

    const {user} = renderBrowser();
    await uploadInto(user);

    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Overwrite the existing notes.txt'})
    );

    await waitFor(() => expect(mock.uploadFile).toHaveBeenCalledTimes(2));
    expect(mock.uploadFile.mock.calls[0][0]).toMatchObject({key: 'alice/notes.txt', overwrite: false});
    expect(mock.uploadFile.mock.calls[1][0]).toMatchObject({key: 'alice/notes.txt', overwrite: true});
    // The user-visible result, not just the call: the item reaches its terminal state.
    expect(await screen.findByText('Uploaded')).toBeInTheDocument();
  });

  it('drives the same collision to Rename and retries under the new key', async () => {
    mock.uploadFile
      .mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}} as never)
      .mockResolvedValue(ok({key: 'alice/notes-2.txt'}) as never);

    const {user} = renderBrowser();
    await uploadInto(user);

    const prompt = await screen.findByRole('alertdialog');
    await user.click(within(prompt).getByRole('button', {name: 'Rename'}));
    const field = within(collisionPrompt()).getByLabelText('New name');
    await user.clear(field);
    await user.type(field, 'notes-2.txt');
    await user.click(within(collisionPrompt()).getByRole('button', {name: 'Save as new name'}));

    await waitFor(() => expect(mock.uploadFile).toHaveBeenCalledTimes(2));
    // A rename must NOT smuggle an overwrite in with it — that is the whole point of
    // offering the choice.
    expect(mock.uploadFile.mock.calls[1][0]).toMatchObject({key: 'alice/notes-2.txt', overwrite: false});
    expect(await screen.findByText('Uploaded')).toBeInTheDocument();
  });

  it('cancels a collision without writing anything', async () => {
    mock.uploadFile.mockResolvedValue({
      success: false,
      error: {message: 'exists', code: 'Collision'}
    } as never);

    const {user} = renderBrowser();
    await uploadInto(user);
    await screen.findByRole('alertdialog');

    await user.click(within(collisionPrompt()).getByRole('button', {name: 'Cancel'}));

    expect(mock.uploadFile).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
  });
});

// FR-003 AC3/AC5: the BATCH prompt, and the summary banner a user actually reads.
describe('FileBrowser — resolving a BATCH collision through the UI (SPEC-154 FR-003)', () => {
  const batchPrompt = () => screen.getByRole('alertdialog', {name: 'Destination already has items'});

  async function copySelectionToDocs(user: ReturnType<typeof renderBrowser>['user']) {
    await user.click(await screen.findByRole('checkbox', {name: 'Select notes.txt'}));
    await user.click(screen.getByRole('button', {name: 'Copy selected items'}));
    const picker = await screen.findByRole('dialog');
    await user.click(within(picker).getByRole('button', {name: 'Open folder docs'}));
    await user.click(await within(picker).findByRole('button', {name: 'Copy here'}));
  }

  it('drives a batch copy collision to Overwrite all and retries the collided items', async () => {
    mock.copyObject
      .mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}} as never)
      .mockResolvedValue(ok({destKey: 'alice/docs/notes.txt'}) as never);

    const {user} = renderBrowser();
    await copySelectionToDocs(user);

    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Overwrite all'}));

    await waitFor(() => expect(mock.copyObject).toHaveBeenCalledTimes(2));
    expect(mock.copyObject.mock.calls[0][0]).toMatchObject({overwrite: false});
    expect(mock.copyObject.mock.calls[1][0]).toMatchObject({overwrite: true});
    // AC5: the user-visible result, not only the service call.
    expect(await screen.findByText(/Copied 1 item/)).toBeInTheDocument();
  });

  it('drives a batch MOVE collision to Overwrite all', async () => {
    // `useMove` has its own `runMove`/`finalizeMove` pair behind the same BatchOverwritePrompt,
    // so a copy-only test leaves the move retry path untested — and a move that quietly
    // overwrote (or quietly did not) is the more destructive of the two.
    mock.moveObject
      .mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}} as never)
      .mockResolvedValue(ok({destKey: 'alice/docs/notes.txt'}) as never);

    const {user} = renderBrowser();
    await user.click(await screen.findByRole('checkbox', {name: 'Select notes.txt'}));
    await user.click(screen.getByRole('button', {name: 'Move selected items'}));
    const picker = await screen.findByRole('dialog');
    await user.click(within(picker).getByRole('button', {name: 'Open folder docs'}));
    await user.click(await within(picker).findByRole('button', {name: 'Move here'}));

    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Overwrite all'}));

    await waitFor(() => expect(mock.moveObject).toHaveBeenCalledTimes(2));
    expect(mock.moveObject.mock.calls[0][0]).toMatchObject({overwrite: false});
    expect(mock.moveObject.mock.calls[1][0]).toMatchObject({overwrite: true});
    expect(await screen.findByText(/Moved 1 item/)).toBeInTheDocument();
  });

  it('cancels a batch collision without copying the collided item', async () => {
    mock.copyObject.mockResolvedValue({success: false, error: {message: 'exists', code: 'Collision'}} as never);

    const {user} = renderBrowser();
    await copySelectionToDocs(user);
    await screen.findByRole('alertdialog');

    await user.click(within(batchPrompt()).getByRole('button', {name: 'Cancel'}));

    expect(mock.copyObject).toHaveBeenCalledTimes(1);
    // Cancelling still finalises: nothing was copied, and the banner says so rather than
    // leaving the user with a dialog that vanished and no account of what happened.
    expect(await screen.findByText(/Copied 0 items/)).toBeInTheDocument();
  });
});

// ── SPEC-154 FR-004: an upload watched to completion ────────────────────────
//
// The most-used flow in the app had one UI-level test whose only assertion was
// `expect(mock.uploadFile).toHaveBeenCalled()`. Above it, `UploadList.test.tsx` mocks the
// context the provider supplies, so every visible state was asserted against hand-fed items;
// below it, `UploadQueueProvider.test.tsx` tests the reducer through `renderHook`. Nothing
// spanned them — so the real provider driving the real list was untested end to end.
//
// This renders the REAL `UploadQueueProvider` behind the REAL `UploadList` (both already in
// `renderBrowser`'s tree) and watches one file through the states a user sees.
describe('FileBrowser — an upload watched to completion (SPEC-154 FR-004)', () => {
  async function chooseFile(user: ReturnType<typeof renderBrowser>['user'], name = 'up.txt') {
    await user.click(await screen.findByRole('button', {name: 'Upload'}));
    const input = await screen.findByLabelText('Choose files');
    await user.upload(input, new File(['data'], name, {type: 'text/plain'}));
  }

  it('progresses queued → uploading (with progress) → Uploaded', async () => {
    // Hold the upload open so the intermediate state is observable rather than skipped:
    // a resolved-immediately mock would go straight to Uploaded and the progress bar — the
    // thing a user stares at — would never render.
    let finish!: (value: unknown) => void;
    mock.uploadFile.mockImplementation((async (params: {onProgress?: (l: number, t: number) => void}) => {
      params.onProgress?.(50, 100);
      return new Promise((resolve) => {
        finish = resolve;
      });
    }) as never);

    const {user} = renderBrowser();
    await chooseFile(user);

    const progress = await screen.findByRole('progressbar', {name: 'Uploading up.txt'});
    expect(progress).toHaveAttribute('aria-valuenow', '50');

    finish(ok({key: 'alice/up.txt'}));

    expect(await screen.findByText('Uploaded')).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('shows the Failed state with the MAPPED message, never the raw AWS text', async () => {
    mock.uploadFile.mockResolvedValue({
      success: false,
      error: {message: 'AccessDenied: not authorized to perform s3:PutObject', code: 'AccessDenied'}
    } as never);

    const {user} = renderBrowser();
    await chooseFile(user);

    expect(await screen.findByText('Failed')).toBeInTheDocument();
    // SPEC-106: `toUserMessage` wording is what reaches the user.
    expect(screen.queryByText(/s3:PutObject/)).not.toBeInTheDocument();
  });

  it('cancelling an in-flight upload aborts the request and marks the item Cancelled', async () => {
    // The mock honours the signal, because the transition depends on it: the provider only
    // aborts, and it is the SERVICE resolving with code `Cancelled` that moves the row. A
    // mock that ignored the signal would leave the item stuck at uploading and the test would
    // be asserting the abort call alone.
    //
    // NOTE ON THE SPEC: FR-004 AC3 says cancelling "removes it". It does not — the row stays,
    // labelled Cancelled, until the user dismisses it or clears finished uploads. That is
    // deliberate in `UploadQueueProvider` (an in-flight cancel transitions; only a QUEUED item
    // is dropped), and it is the better behaviour — a row that vanishes gives no confirmation
    // the cancel took. Asserted as it is, and recorded in the delivery doc.
    let seenSignal: AbortSignal | undefined;
    mock.uploadFile.mockImplementation((async (params: {signal?: AbortSignal}) => {
      seenSignal = params.signal;
      return new Promise((resolve) => {
        params.signal?.addEventListener('abort', () =>
          resolve({success: false, error: {message: 'aborted', code: 'Cancelled'}})
        );
      });
    }) as never);

    const {user} = renderBrowser();
    await chooseFile(user);
    await screen.findByRole('progressbar', {name: 'Uploading up.txt'});

    await user.click(screen.getByRole('button', {name: 'Cancel upload of up.txt'}));

    expect(seenSignal?.aborted).toBe(true);
    // The badge and the row's subtext both read "Cancelled" — the point is that the row is
    // still there and says so, not which of the two elements says it.
    expect(await screen.findAllByText('Cancelled')).not.toHaveLength(0);
    expect(screen.getByText('up.txt')).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('a QUEUED upload is dropped outright when cancelled', async () => {
    // The other half of the cancel contract, and the half FR-004 AC3 describes: nothing was
    // written for a queued item, so it leaves no trace rather than a Cancelled row.
    mock.uploadFile.mockImplementation((async () => new Promise(() => {})) as never);

    const {user} = renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'Upload'}));
    const input = await screen.findByLabelText('Choose files');
    await user.upload(input, [
      new File(['a'], 'a.txt', {type: 'text/plain'}),
      new File(['b'], 'b.txt', {type: 'text/plain'}),
      new File(['c'], 'c.txt', {type: 'text/plain'}),
      new File(['d'], 'd.txt', {type: 'text/plain'})
    ]);
    await screen.findByText('Queued');

    await user.click(screen.getByRole('button', {name: 'Cancel upload of d.txt'}));

    await waitFor(() => expect(screen.queryByText('d.txt')).not.toBeInTheDocument());
    expect(screen.queryAllByText('Cancelled')).toHaveLength(0);
  });

  it('holds the fourth file at Queued while three are in flight (UPLOAD_CONCURRENCY)', async () => {
    // AC4: the gate IS observable at this level, so it is asserted here rather than left to
    // the provider test. Four files, a mock that never settles, and the fourth must not start.
    mock.uploadFile.mockImplementation((async () => new Promise(() => {})) as never);

    const {user} = renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'Upload'}));
    const input = await screen.findByLabelText('Choose files');
    await user.upload(input, [
      new File(['a'], 'a.txt', {type: 'text/plain'}),
      new File(['b'], 'b.txt', {type: 'text/plain'}),
      new File(['c'], 'c.txt', {type: 'text/plain'}),
      new File(['d'], 'd.txt', {type: 'text/plain'})
    ]);

    await waitFor(() => expect(mock.uploadFile).toHaveBeenCalledTimes(UPLOAD_CONCURRENCY));
    expect(await screen.findByText('Queued')).toBeInTheDocument();
    // Guards the guard: three really did start, so the fourth being Queued means the gate
    // held rather than the whole batch having stalled.
    expect(screen.getAllByRole('progressbar')).toHaveLength(UPLOAD_CONCURRENCY);
  });
});

describe('FileBrowser — send to… (SPEC-167)', () => {
  // THE JOURNEY, not the halves (SPEC-154's discipline): select real rows in the real browser,
  // open the real dialog, name a recipient through the real combobox, and assert what reached
  // the queue. Every piece between the checkbox and the enqueue is the shipped one.
  const sendButton = () => screen.getByRole('button', {name: 'Send selected items to someone'});

  beforeEach(() => {
    mockSend.mockResolvedValue({success: true, data: undefined});
  });

  it('sends a MIXED selection, with each item as the kind the browser knows it to be', async () => {
    const {user} = renderBrowser();
    await screen.findByText('report.csv');

    expect(sendButton()).toBeDisabled();
    await user.click(screen.getByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(screen.getByRole('checkbox', {name: 'Select folder docs'}));
    await user.click(sendButton());

    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('combobox'));
    await user.keyboard('bob');
    await user.click(within(dialog).getByRole('button', {name: 'Add'}));
    await user.click(within(dialog).getByRole('button', {name: 'Send'}));

    await waitFor(() => expect(mockSend).toHaveBeenCalledTimes(1));
    expect(mockSend.mock.calls[0][0]).toMatchObject({
      // The SPACE, not the current folder: the control plane resolves the source from the
      // verified username and the space name.
      space: {kind: 'personal', name: 'alice'},
      items: [
        {kind: 'file', key: 'alice/report.csv'},
        {kind: 'folder', key: 'alice/docs/'}
      ],
      recipients: [{kind: 'user', name: 'bob'}]
    });
  });

  it('closes, clears the selection and says the send was REQUESTED', async () => {
    const {user} = renderBrowser();
    await screen.findByText('report.csv');
    await user.click(screen.getByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(sendButton());

    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('combobox'));
    await user.keyboard('bob');
    await user.click(within(dialog).getByRole('button', {name: 'Add'}));
    await user.click(within(dialog).getByRole('button', {name: 'Send'}));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByRole('checkbox', {name: 'Select report.csv'})).not.toBeChecked();
    expect(await screen.findByText(/you'll get a notification/i)).toBeInTheDocument();
  });

  it('sends from a SHARED space as that space, not as the signed-in user', async () => {
    // The one derivation a refactor could silently invert: the source is the space the browser
    // is pointed at, and its name is the root prefix's own segment — `{username}/` for a
    // personal space and `{spaceName}/` for a shared one. Sending a shared space's files as
    // `personal` would make the control plane authorize the wrong space entirely.
    const {user} = renderBrowser({rootPrefix: 'finance/', username: 'finance', spaceKind: 'shared'});
    await screen.findByText('report.csv');
    await user.click(screen.getByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(sendButton());

    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('combobox'));
    await user.keyboard('bob');
    await user.click(within(dialog).getByRole('button', {name: 'Add'}));
    await user.click(within(dialog).getByRole('button', {name: 'Send'}));

    await waitFor(() => expect(mockSend).toHaveBeenCalledTimes(1));
    expect(mockSend.mock.calls[0][0]).toMatchObject({space: {kind: 'shared', name: 'finance'}});
  });

  it('keeps the dialog and the recipients on a failure, with no raw AWS text', async () => {
    mockSend.mockResolvedValue({
      success: false,
      error: {message: 'AccessDenied: User arn:aws:sts::1:assumed-role/x is not authorized'}
    });
    const {user} = renderBrowser();
    await screen.findByText('report.csv');
    await user.click(screen.getByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(sendButton());

    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('combobox'));
    await user.keyboard('bob');
    await user.click(within(dialog).getByRole('button', {name: 'Add'}));
    await user.click(within(dialog).getByRole('button', {name: 'Send'}));

    const alert = await within(dialog).findByRole('alert');
    expect(alert).not.toHaveTextContent(/arn:aws/);
    expect(within(dialog).getByRole('button', {name: 'Remove user bob'})).toBeInTheDocument();
    expect(screen.getByRole('checkbox', {name: 'Select report.csv'})).toBeChecked();
  });
});
