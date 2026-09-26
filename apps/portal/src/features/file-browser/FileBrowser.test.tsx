import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {act, screen, within, waitFor} from '@testing-library/react';
import type {ReactElement} from 'react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {FileBrowser} from './FileBrowser';
import {UploadQueueProvider} from './UploadQueueProvider';
import {toUserText} from '../../lib/errorMessages';
import {FileOpsInFlightProvider} from './FileOpsInFlightProvider';
import {UPLOAD_CONCURRENCY} from './upload.types';
import * as service from './fileBrowser.service';
import {triggerBrowserDownload} from './fileBrowser.download';
import {getIdToken} from '../../lib/idToken';
import * as dqService from '../data-quality/dataQuality.service';
import * as sendService from '../file-send/fileSend.service';
import {submitFileOperation} from './fileOps.service';
import {apiRequest} from '../../lib/apiClient';
import type {FileListPage, S3FileItem, S3FolderItem} from '../../types/s3.types';
import type {FeatureFlags} from '../feature-flags';

// Integration style (react.md §21): render the REAL FileBrowser tree — real
// hooks (useFileBrowser/useDelete/useMove/useCopy/useCreateFolder), real child
// dialogs (Create/Delete/Rename/Move/Copy/Metadata) — and mock ONLY the AWS
// service boundary. The pure helpers (validateFolderName/uploadPercent/…) stay
// real via importActual so the hooks behave normally.
vi.mock('./fileBrowser.service', async (importActual) => {
  const actual = await importActual<typeof service>();
  return {
    ...actual,
    listFiles: vi.fn(),
    getObjectMetadata: vi.fn(),
    deleteObject: vi.fn(),
    moveObject: vi.fn(),
    copyObject: vi.fn(),
    firstFreeName: vi.fn(),
    getDownloadUrl: vi.fn(),
    uploadFile: vi.fn(),
    createFolder: vi.fn()
  };
});
// triggerBrowserDownload navigates the browser — stub the side effect (its own
// unit test covers the anchor mechanics).
vi.mock('./fileBrowser.download', () => ({triggerBrowserDownload: vi.fn()}));
vi.mock('../../lib/idToken', () => ({
  getIdToken: vi.fn().mockResolvedValue({success: true, data: 'id-token'})
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
// The API client, watched but not replaced: every render already reads through it, and with no API
// origin configured here the real client answers `ApiUnavailable` without sending anything. A test
// that lets a REAL service write reads the attempted routes back, which is the only place a refused
// write can be seen not to happen.
vi.mock('../../lib/apiClient', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/apiClient')>();
  return {...actual, apiRequest: vi.fn(actual.apiRequest)};
});

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
function renderBrowser(
  props: Partial<Parameters<typeof FileBrowser>[0]> = {},
  featureFlags?: Partial<FeatureFlags>
): ReturnType<typeof renderWithProviders> {
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
  return renderWithProviders(ui, {featureFlags});
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
  mock.deleteObject.mockResolvedValue(ok({key: 'alice/report.csv'}));
  mock.moveObject.mockResolvedValue(ok({destKey: 'alice/docs/notes.txt'}));
  mock.copyObject.mockResolvedValue(ok({destKey: 'alice/docs/notes.txt'}));
  mock.firstFreeName.mockResolvedValue(ok('report (1).csv'));
  mock.createFolder.mockResolvedValue(ok({prefix: 'alice/new/'}));
  mock.uploadFile.mockResolvedValue(ok({key: 'alice/up.txt'}));
  mockQualityCheck.mockResolvedValue(ok({requestId: 'req-1'}));
});

afterEach(() => {
  window.innerWidth = 1024;
});

describe('FileBrowser — listing states', () => {
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
    expect(getIdToken).toHaveBeenCalledWith(true);
    expect(await screen.findByText('report.csv')).toBeInTheDocument();
  });

  it('shows one server page at a time: Next fetches and replaces, Prev returns from cache', async () => {
    mock.listFiles
      .mockResolvedValueOnce(
        ok(page({files: [file('page1.csv')], folders: [], isTruncated: true, nextContinuationToken: 't1'}))
      )
      .mockResolvedValueOnce(ok(page({files: [file('page2.csv')], folders: [], isTruncated: false})));
    const {user} = renderBrowser();
    await screen.findByText('page1.csv');
    // No page count is claimed while the server still has more.
    expect(screen.getByText('Page 1')).toBeInTheDocument();

    await user.click(screen.getByRole('button', {name: 'Next'}));
    expect(await screen.findByText('page2.csv')).toBeInTheDocument();
    expect(screen.queryByText('page1.csv')).not.toBeInTheDocument();
    expect(screen.getByText('Page 2 of 2')).toBeInTheDocument();
    expect(mock.listFiles).toHaveBeenLastCalledWith('my-bucket', 'alice/', 't1', expect.any(AbortSignal));

    await user.click(screen.getByRole('button', {name: 'Prev'}));
    expect(await screen.findByText('page1.csv')).toBeInTheDocument();
    expect(mock.listFiles).toHaveBeenCalledTimes(2);
  });

  it('omits the pager for a folder that fits on one page', async () => {
    renderBrowser();
    await screen.findByText('report.csv');
    expect(screen.queryByRole('button', {name: 'Next'})).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Prev'})).not.toBeInTheDocument();
  });

  it('drops the selection on a page turn, since the toolbar acts on rows the user can see', async () => {
    mock.listFiles
      .mockResolvedValueOnce(
        ok(page({files: [file('page1.csv')], folders: [], isTruncated: true, nextContinuationToken: 't1'}))
      )
      .mockResolvedValueOnce(ok(page({files: [file('page2.csv')], folders: [], isTruncated: false})));
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('checkbox', {name: 'Select page1.csv'}));
    expect(screen.getByText('1 selected')).toBeInTheDocument();

    await user.click(screen.getByRole('button', {name: 'Next'}));
    await screen.findByText('page2.csv');
    expect(screen.queryByText('1 selected')).not.toBeInTheDocument();
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

  it('shows a parent-folder (..) row below the root and navigates up on click', async () => {
    const {user} = renderBrowser({prefix: 'alice/docs/'});
    const up = await screen.findByRole('button', {name: /parent folder/i});
    await user.click(up);
    await waitFor(() =>
      expect(mock.listFiles).toHaveBeenLastCalledWith('my-bucket', 'alice/', undefined, expect.any(AbortSignal))
    );
  });
});

describe('FileBrowser — download', () => {
  it('downloads a file on double-click', async () => {
    const {user} = renderBrowser();
    await user.dblClick(await screen.findByText('report.csv'));
    await waitFor(() => expect(mock.getDownloadUrl).toHaveBeenCalled());
    expect(triggerBrowserDownload).toHaveBeenCalledWith('https://signed/report.csv');
  });

  it('exposes a per-row Download button only in read-only browse', async () => {
    renderBrowser({writable: false, username: undefined});
    expect(await screen.findByRole('button', {name: 'Download report.csv'})).toBeInTheDocument();
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
  it('creates a folder through the New folder dialog, and hands New folder back', async () => {
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'New folder'}));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('textbox'), 'photos');
    await user.click(within(dialog).getByRole('button', {name: /create/i}));
    await waitFor(() =>
      expect(mock.createFolder).toHaveBeenCalledWith(expect.objectContaining({name: 'photos', prefix: 'alice/'}))
    );
    await waitFor(() => expect(screen.getByRole('button', {name: 'New folder'})).toBeEnabled());
  });

  it('refuses the app’s own folder names inside system_settings, and issues no request', async () => {
    // `system_settings/` is writable, so without this the user mints a folder that every rule
    // then treats as the app's — read-only inside, undeletable, unrenamable, unarchivable, and
    // permanent — at the exact path the restore dialog sends them to for their archive ids.
    // Asserted on the CALL, not on the message: a dialog that shows an error and submits anyway
    // looks identical until the request lands.
    const {user} = renderBrowser({prefix: 'alice/system_settings/'});
    await user.click(await screen.findByRole('button', {name: 'New folder'}));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('textbox'), 'archive');
    await user.click(within(dialog).getByRole('button', {name: /create/i}));

    expect(within(dialog).getByText(/the app manages inside/i)).toBeInTheDocument();
    expect(mock.createFolder).not.toHaveBeenCalled();
  });

  it('refuses a new folder that would BE the app’s folder at the top of a space, and issues no request', async () => {
    // Made by hand, it is the app's folder rather than one sharing its name — and a hidden name
    // would vanish from the listing the moment it was created.
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'New folder'}));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('textbox'), '_config');
    await user.click(within(dialog).getByRole('button', {name: /create/i}));

    expect(
      within(dialog).getByText('“_config” is a folder the app manages at the top of a space. Pick another name.')
    ).toBeInTheDocument();
    expect(mock.createFolder).not.toHaveBeenCalled();
  });

  it('still creates a folder named user_settings below the top of a space, which its route writes', async () => {
    // The positive control for the plane-only rule: only a rename or copy lands a folder there
    // through the file-operations plane, whose role cannot write it.
    const {user} = renderBrowser({prefix: 'alice/projects/'});
    await user.click(await screen.findByRole('button', {name: 'New folder'}));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('textbox'), 'user_settings');
    await user.click(within(dialog).getByRole('button', {name: /create/i}));

    await waitFor(() =>
      expect(mock.createFolder).toHaveBeenCalledWith(
        expect.objectContaining({name: 'user_settings', prefix: 'alice/projects/'})
      )
    );
  });

  it('still creates an ordinary folder inside system_settings, which is not locked', async () => {
    // The positive control. Nothing denies writes under that prefix, so a guard that refused
    // everything there would be inventing a restriction IAM does not have.
    const {user} = renderBrowser({prefix: 'alice/system_settings/'});
    await user.click(await screen.findByRole('button', {name: 'New folder'}));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('textbox'), 'notes');
    await user.click(within(dialog).getByRole('button', {name: /create/i}));

    await waitFor(() =>
      expect(mock.createFolder).toHaveBeenCalledWith(
        expect.objectContaining({name: 'notes', prefix: 'alice/system_settings/'})
      )
    );
  });

  it('refuses New folder and Upload inside the query results folder, and says why', async () => {
    // IAM permits the write there and denies the delete, so a folder or file the user makes in it
    // can never be removed. Asserted on what the clicks DO — no dialog, no drawer, no request — and
    // on the folder the reason names, because the receipt folder's refusal would grey the same two.
    mock.listFiles.mockResolvedValue(
      ok(page({files: [file('system_settings/athenaresults/q1.csv', {name: 'q1.csv'})], folders: []}))
    );
    const {user} = renderBrowser({prefix: 'alice/system_settings/athenaresults/'});
    await screen.findByText('q1.csv');

    await user.click(screen.getByRole('button', {name: 'New folder'}));
    await user.click(screen.getByRole('button', {name: 'Upload'}));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(mock.createFolder).not.toHaveBeenCalled();
    for (const name of ['New folder', 'Upload']) {
      expect(screen.getByRole('button', {name})).toHaveAttribute('title', expect.stringMatching(/query results/i));
    }
    expect(screen.getByRole('note')).toHaveTextContent(/query results/i);
  });
});

describe('FileBrowser — selection + delete', () => {
  it('deletes the selected items after confirmation and reports the count', async () => {
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(screen.getByRole('button', {name: 'Delete selected items'}));
    // Nothing deleted until the confirm dialog is accepted.
    expect(mock.deleteObject).not.toHaveBeenCalled();
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    await waitFor(() =>
      expect(mock.deleteObject).toHaveBeenCalledWith(expect.objectContaining({key: 'alice/report.csv'}))
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
    mock.deleteObject.mockResolvedValue({
      success: false,
      error: {message: 'Access Denied', code: 'AccessDenied'}
    });
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(screen.getByRole('button', {name: 'Delete selected items'}));
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    // The reason is the mapped message, not raw S3 text.
    expect(await screen.findByText(/report\.csv — You don’t have permission/)).toBeInTheDocument();
    expect(screen.queryByText(/report\.csv — Access Denied/)).not.toBeInTheDocument();
  });

  // ── SPEC-186 FR-002 ────────────────────────────────────────────────────────
  // The file-operations plane refuses these too, per item, but only AFTER the user read "Delete
  // the folder … and everything inside it? This can't be undone." and pressed Delete. Removing
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
      expect(mock.deleteObject).not.toHaveBeenCalled();
    });

    it('states the MOVE reason on Move, which is worded for a rename too', async () => {
      mock.listFiles.mockResolvedValue(ok(page(withSavedQueries)));
      const {user} = renderBrowser();
      await user.click(await screen.findByRole('checkbox', {name: 'Select folder saved_queries'}));

      const move = screen.getByRole('button', {name: 'Move selected items'});
      expect(move).toHaveAttribute('title', 'Saved queries live in this folder, so it can’t be moved or renamed.');
      await user.click(move);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(mock.moveObject).not.toHaveBeenCalled();
    });

    it('refuses when EVERY selected folder is protected, and names one of them', async () => {
      mock.listFiles.mockResolvedValue(
        ok(page({files: [], folders: [folder('saved_queries'), folder('system_settings')], isTruncated: false}))
      );
      const {user} = renderBrowser();
      await user.click(await screen.findByRole('checkbox', {name: 'Select folder saved_queries'}));
      // `system_settings` rather than `athenaresults`: the results folder moved inside it, so the
      // depth-one name is an ordinary folder now and would not make the selection wholly protected.
      await user.click(screen.getByRole('checkbox', {name: 'Select folder system_settings'}));

      const del = screen.getByRole('button', {name: 'Delete selected items'});
      expect(del).toHaveAttribute('aria-disabled', 'true');
      expect(del).toHaveAttribute('title', 'Saved queries live in this folder, so it can’t be deleted.');
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
    // The dialog edits the STEM and keeps the extension; a bare "was called" once hid a
    // `renamed.csv.csv` here.
    await user.type(input, 'renamed');
    await user.click(within(dialog).getByRole('button', {name: /rename|save/i}));
    await waitFor(() =>
      expect(mock.moveObject).toHaveBeenCalledWith(
        expect.objectContaining({sourceKey: 'alice/report.csv', destKey: 'alice/renamed.csv'})
      )
    );
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
    expect(mock.moveObject).not.toHaveBeenCalled();
    expect(mockSubmitFileOp).toHaveBeenCalledTimes(1);
    expect(mockSubmitFileOp.mock.calls[0][0]).toMatchObject({
      operation: 'move',
      source: {items: [{kind: 'folder', key: 'alice/docs/', targetName: 'archive'}]},
      destination: {prefix: 'alice/'},
      onConflict: 'refuse'
    });
  });

  it('refuses renaming a folder onto the app’s folder at the top of a space, before anything is enqueued', async () => {
    // The plane would accept the request and refuse the item only in the run's notification.
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'Details for docs'}));
    await user.click(await screen.findByRole('button', {name: 'Rename docs'}));
    const dialog = await screen.findByRole('dialog', {name: /rename/i});
    const input = within(dialog).getByRole('textbox');
    await user.clear(input);
    await user.type(input, 'shared_tables{Enter}');

    expect(
      within(dialog).getByText('“shared_tables” is a folder the app manages at the top of a space. Pick another name.')
    ).toBeInTheDocument();
    expect(within(dialog).getByRole('button', {name: /rename|save/i})).toBeDisabled();
    expect(mockSubmitFileOp).not.toHaveBeenCalled();
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
    // The real UploadQueueProvider starts the queued item via uploadFile, under the chosen key.
    await waitFor(() => expect(mock.uploadFile).toHaveBeenCalledWith(expect.objectContaining({key: 'alice/up.txt'})));
  });
});

describe('FileBrowser — data quality (SPEC-113)', () => {
  const checkButton = () => screen.getByRole('button', {name: 'Check data quality of the selected item'});

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

  it('shows the action bar just "Restore", still named for the whole label', async () => {
    window.innerWidth = 500;
    renderBrowser();
    await screen.findByText('report.csv');
    const bar = screen.getByRole('toolbar', {name: 'File actions'});
    // In a third of a phone's width the whole label wraps to three lines and spills out of the
    // button. The visible word must begin the name, or voice control cannot reach it.
    expect(within(bar).getByRole('button', {name: 'Restore Archived Data'})).toHaveTextContent(/^Restore$/);
  });

  it('leaves Restore out of the action bar while the archive switch is off', async () => {
    window.innerWidth = 500;
    renderBrowser({}, {archive: false});
    await screen.findByText('report.csv');
    const bar = screen.getByRole('toolbar', {name: 'File actions'});

    expect(within(bar).getByRole('button', {name: 'New folder'})).toBeInTheDocument();
    expect(within(bar).queryByRole('button', {name: 'Restore Archived Data'})).not.toBeInTheDocument();
  });

  it('keeps the whole label on the top toolbar', async () => {
    renderBrowser();
    const restore = await screen.findByRole('button', {name: 'Restore Archived Data'});
    expect(restore).toHaveTextContent(/^Restore Archived Data$/);
    expect(restore).not.toHaveAttribute('aria-label');
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

  it('drops the item from the queue when the collision prompt is cancelled — no second upload', async () => {
    mock.uploadFile.mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}} as never);

    const {user} = renderBrowser();
    await uploadInto(user);

    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Cancel'}));

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', {name: 'Uploads'})).not.toBeInTheDocument();
    expect(mock.uploadFile).toHaveBeenCalledTimes(1);
  });

  it('refuses a new name containing a slash, says why, and keeps the prompt open', async () => {
    // The retried key is the original prefix plus this name, so a slash would land the file in a
    // subfolder rather than beside the one it collided with.
    mock.uploadFile.mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}} as never);

    const {user} = renderBrowser();
    await uploadInto(user);

    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Rename'}));
    const field = within(collisionPrompt()).getByLabelText('New name');
    await user.clear(field);
    await user.type(field, 'sub/notes.txt{Enter}');

    // The prompt still being there is what proves Enter did not rename: a rename re-queues the row.
    expect(within(collisionPrompt()).getByText('File name cannot contain “/”.')).toBeInTheDocument();
    expect(within(collisionPrompt()).getByRole('button', {name: 'Save as new name'})).toBeDisabled();
    expect(mock.uploadFile).toHaveBeenCalledTimes(1);
  });
});

describe('FileBrowser — resolving a folder-name collision through the UI', () => {
  const folderPrompt = () => screen.getByRole('alertdialog', {name: 'Folder already exists'});

  async function createAndRenameTo(user: ReturnType<typeof renderBrowser>['user'], newName: string) {
    await user.click(await screen.findByRole('button', {name: 'New folder'}));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('textbox'), 'notes');
    await user.click(within(dialog).getByRole('button', {name: /create/i}));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Rename'}));
    const field = within(folderPrompt()).getByLabelText('New name');
    await user.clear(field);
    await user.type(field, `${newName}{Enter}`);
  }

  it('refuses a new folder name containing a slash, in the folder wording, and creates nothing more', async () => {
    mock.createFolder.mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}} as never);

    const {user} = renderBrowser();
    await createAndRenameTo(user, 'sub/notes');

    expect(within(folderPrompt()).getByText('Folder name cannot contain “/”.')).toBeInTheDocument();
    expect(mock.createFolder).toHaveBeenCalledTimes(1);
  });

  it('refuses a new name that would BE the app’s folder at the top of a space, in the prompt itself', async () => {
    mock.createFolder.mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}} as never);

    const {user} = renderBrowser();
    await createAndRenameTo(user, 'user_settings');

    expect(
      within(folderPrompt()).getByText(
        '“user_settings” is a folder the app manages at the top of a space. Pick another name.'
      )
    ).toBeInTheDocument();
    expect(mock.createFolder).toHaveBeenCalledTimes(1);
  });

  it('checks a new name against the folder the retry writes into, not the one navigated to since', async () => {
    // The prompt is inline and outlives navigation, and its retry keeps the folder the collision
    // happened in — so checking the folder now on screen refuses a name that is legal where it lands.
    mock.createFolder.mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}} as never);

    const {user} = renderBrowser({prefix: 'alice/docs/'});
    await user.click(await screen.findByRole('button', {name: 'New folder'}));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('textbox'), 'notes');
    await user.click(within(dialog).getByRole('button', {name: /create/i}));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Rename'}));
    await user.click(screen.getByRole('button', {name: 'My Files'}));
    const field = within(folderPrompt()).getByLabelText('New name');
    await user.clear(field);
    await user.type(field, 'shared_tables{Enter}');

    await waitFor(() => expect(mock.createFolder).toHaveBeenCalledTimes(2));
    expect(mock.createFolder.mock.calls[1][0]).toMatchObject({prefix: 'alice/docs/', name: 'shared_tables'});
  });

  it('still retries an ordinary new name, without an overwrite', async () => {
    // The positive control: the same keystrokes with a valid name do reach the create, so the
    // refusal above is the rule firing rather than Enter doing nothing in this prompt.
    mock.createFolder.mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}} as never);

    const {user} = renderBrowser();
    await createAndRenameTo(user, 'notes-2');

    await waitFor(() => expect(mock.createFolder).toHaveBeenCalledTimes(2));
    expect(mock.createFolder.mock.calls[1][0]).toEqual({
      bucket: 'my-bucket',
      prefix: 'alice/',
      name: 'notes-2',
      overwrite: false
    });
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('closes the prompt on Cancel and hands New folder back, creating nothing more', async () => {
    // New folder is disabled while a create is in flight, so a create that ends in a collision
    // has to release it too: otherwise cancelling the prompt leaves the button dead for good.
    let answer!: (result: Awaited<ReturnType<typeof service.createFolder>>) => void;
    mock.createFolder.mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
    const newFolder = () => screen.getByRole('button', {name: 'New folder'});

    const {user} = renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'New folder'}));
    const dialog = await screen.findByRole('dialog');
    await user.type(within(dialog).getByRole('textbox'), 'notes');
    await user.click(within(dialog).getByRole('button', {name: /create/i}));
    expect(newFolder()).toBeDisabled();

    await act(async () => answer({success: false, error: {message: 'exists', code: 'Collision'}}));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Cancel'}));

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(newFolder()).toBeEnabled();
    await user.click(newFolder());
    expect(await screen.findByRole('dialog', {name: 'Create folder'})).toBeInTheDocument();
    expect(mock.createFolder).toHaveBeenCalledTimes(1);
  });

  describe('inside system_settings, where the retry reaches the real createFolder', () => {
    // The prompt is told the parent and refuses first; `createFolder`, which knows the prefix it
    // writes into, is the check behind it that every caller reaches. Reached through `importActual`
    // because this file mocks the module it lives in; the collision itself stays mocked.
    async function collideOnceThenCreateForReal() {
      const {createFolder: realCreateFolder} = await vi.importActual<typeof service>('./fileBrowser.service');
      mock.createFolder
        .mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}} as never)
        .mockImplementation(realCreateFolder);
    }
    const attemptedRoutes = () => vi.mocked(apiRequest).mock.calls.map(([route]) => route);

    it('refuses the app’s own folder name on the retry, says why, and writes nothing', async () => {
      await collideOnceThenCreateForReal();

      const {user} = renderBrowser({prefix: 'alice/system_settings/'});
      await createAndRenameTo(user, 'archive');

      expect(
        await screen.findByText('“archive” is a folder the app manages inside system_settings. Pick another name.')
      ).toBeInTheDocument();
      expect(attemptedRoutes()).not.toContain('objects.writeContent');
    });

    it('still writes an ordinary new name there', async () => {
      // The positive control, observed where the refusal above observes an absence — so that
      // absence is the rule firing, not a route this harness can never see.
      await collideOnceThenCreateForReal();

      const {user} = renderBrowser({prefix: 'alice/system_settings/'});
      await createAndRenameTo(user, 'notes-2');

      await waitFor(() =>
        expect(apiRequest).toHaveBeenCalledWith(
          'objects.writeContent',
          expect.objectContaining({
            body: expect.objectContaining({key: 'alice/system_settings/notes-2/', overwrite: false})
          })
        )
      );
    });
  });
});

// FR-003 AC3/AC5: the BATCH prompt, and the summary banner a user actually reads.
describe('FileBrowser — resolving a BATCH collision through the UI (SPEC-154 FR-003)', () => {
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
});

// ── SPEC-154 FR-004: an upload watched to completion ────────────────────────
//
// The most-used flow in the app once had one UI-level test whose only assertion was that
// `uploadFile` was called; the list's own suite mocked the context the provider supplies, so
// every visible state was asserted against hand-fed items, and `UploadQueueProvider.test.tsx`
// tests the reducer through `renderHook`. Nothing spanned them — so the real provider driving
// the real list was untested end to end. The list's behaviours now live here too.
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
    const denied = {message: 'AccessDenied: not authorized to perform s3:PutObject', code: 'AccessDenied'};
    mock.uploadFile.mockResolvedValue({success: false, error: denied} as never);

    const {user} = renderBrowser();
    await chooseFile(user);

    expect(await screen.findByText('Failed')).toBeInTheDocument();
    // The sentence a user reads is the mapper's, compared against the mapper's own output
    // rather than a second copy of it; the raw text must not survive beside it.
    expect(screen.getByText(toUserText(denied))).toBeInTheDocument();
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

  // The list's own behaviours, driven through the parent that wires the dropzone to the queue
  // rather than through a mocked `useUploadQueue`: what it shows per row is only meaningful
  // against items the real provider produced.
  it('lists uploads newest first, labelled with their destination space, and dismisses a finished one', async () => {
    // A NESTED prefix in a shared space: the label is the space (the key's first segment),
    // never the folder the upload landed in.
    const {user} = renderBrowser({prefix: 'team/sub/', rootPrefix: 'team/', rootLabel: 'team'});
    await chooseFile(user, 'first.txt');
    await screen.findByText('Uploaded');
    await user.upload(screen.getByLabelText('Choose files'), new File(['b'], 'second.txt', {type: 'text/plain'}));
    await waitFor(() => expect(screen.getAllByText('Uploaded')).toHaveLength(2));

    const list = screen.getByRole('region', {name: 'Uploads'});
    expect(
      within(list)
        .getAllByText(/\.txt$/)
        .map((el) => el.textContent)
    ).toEqual(['second.txt', 'first.txt']);
    expect(within(list).getAllByText('team')).toHaveLength(2);
    expect(within(list).queryByText('sub')).not.toBeInTheDocument();
    // A finished row offers Dismiss and never Cancel.
    expect(within(list).queryByRole('button', {name: /cancel upload/i})).not.toBeInTheDocument();
    await user.click(within(list).getByRole('button', {name: 'Dismiss first.txt'}));
    expect(within(list).queryByText('first.txt')).not.toBeInTheDocument();
  });

  it('shows the per-file cancel / dismiss button at rest where the primary input cannot hover', async () => {
    const {user} = renderBrowser();
    await chooseFile(user);
    const dismiss = await screen.findByRole('button', {name: 'Dismiss up.txt'});
    // jsdom evaluates no media query, so the contract is the class on whatever hides the button.
    expect(dismiss.closest('.opacity-0')).toHaveClass('[@media(hover:none)]:opacity-100');
  });

  it('offers Clear finished only once a row is terminal, and the list leaves with its last row', async () => {
    let finish!: (value: unknown) => void;
    mock.uploadFile.mockImplementation(
      (async () =>
        new Promise((resolve) => {
          finish = resolve;
        })) as never
    );

    const {user} = renderBrowser();
    await chooseFile(user);
    await screen.findByRole('progressbar', {name: 'Uploading up.txt'});
    expect(screen.queryByRole('button', {name: 'Clear finished uploads from the list'})).not.toBeInTheDocument();

    finish(ok({key: 'alice/up.txt'}));
    await user.click(await screen.findByRole('button', {name: 'Clear finished uploads from the list'}));
    expect(screen.queryByRole('region', {name: 'Uploads'})).not.toBeInTheDocument();
  });

  it('counts a row waiting on a name choice apart from the uploads in progress', async () => {
    // A collided row moves nowhere until the user answers it, so counting it as in progress
    // tells them to wait for something that is waiting for them.
    mock.uploadFile.mockImplementation((async (params: {key: string}) =>
      params.key === 'alice/notes.txt'
        ? {success: false, error: {message: 'exists', code: 'Collision'}}
        : new Promise(() => {})) as never);

    const {user} = renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'Upload'}));
    await user.upload(await screen.findByLabelText('Choose files'), [
      new File(['a'], 'notes.txt', {type: 'text/plain'}),
      new File(['b'], 'up.txt', {type: 'text/plain'})
    ]);

    const list = await screen.findByRole('region', {name: 'Uploads'});
    await within(list).findByRole('alertdialog', {name: 'File already exists'});
    // The whole status, matched exactly: counted as in progress, the waiting row would read "2 in progress".
    expect(within(list).getByText('1 in progress · 1 needs your choice')).toBeInTheDocument();
  });
});

describe('FileBrowser — send to… (SPEC-167)', () => {
  // THE JOURNEY, not the halves (SPEC-154's discipline): select real rows in the real browser,
  // open the real dialog, name a recipient through the real combobox, and assert what reached
  // the queue. Every piece between the checkbox and the enqueue is the shipped one.
  const sendButton = () => screen.getByRole('button', {name: 'Send to another user'});

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
    expect(await screen.findByText(/the outcome will arrive in your notifications/i)).toBeInTheDocument();
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

// The toolbar's actions are written out once per button across two features, and at `tablet`
// their padding, the bar's gap and the missing glyphs are the band's whole budget — a copy that
// drifts spends it where nothing shows. jsdom loads no Tailwind, so the classes are what can be
// asserted, and exactly, since an added class is as able to undo the band as a removed one.
describe('the selection toolbar across the tablet band', () => {
  const WORDS: Record<string, string> = {
    'Check data quality of the selected item': 'Check data quality',
    'Send to another user': 'Send to…',
    'Archive selected items': 'Archive',
    'Copy selected items': 'Copy',
    'Move selected items': 'Move',
    'Delete selected items': 'Delete'
  };

  it('gives every action one shape, and truncates the count only from tablet up', async () => {
    renderBrowser();
    const bar = (await screen.findByRole('button', {name: 'Delete selected items'})).parentElement as HTMLElement;

    const actions = within(bar).getAllByRole('button');
    expect(actions.map((a) => a.getAttribute('aria-label'))).toEqual(Object.keys(WORDS));
    for (const action of actions) {
      expect([...action.classList].filter((c) => /^(tablet|desktop):!px-/.test(c))).toEqual([
        'tablet:!px-2',
        'desktop:!px-3'
      ]);
      // The glyph is the whole control below `tablet`, so a `hidden` here empties it on a phone.
      expect(action.querySelector('svg')).toHaveAttribute('class', 'h-[15px] w-[15px] tablet:hidden desktop:block');
      expect(within(action).getByText(WORDS[action.getAttribute('aria-label') ?? ''])).toHaveAttribute(
        'class',
        'hidden whitespace-nowrap tablet:inline'
      );
    }
    expect([...bar.classList].filter((c) => /^(tablet:|desktop:)?gap-/.test(c))).toEqual(['gap-2', 'desktop:gap-3']);

    // Below `tablet` a truncated "128 selected" reads as "12…", so the count wraps there instead.
    expect(within(bar).getByText('Select all')).toHaveAttribute(
      'class',
      'text-sm font-semibold tablet:min-w-0 tablet:truncate text-text-3'
    );
  });
});
