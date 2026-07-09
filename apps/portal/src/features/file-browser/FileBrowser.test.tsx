import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {screen, within, waitFor} from '@testing-library/react';
import type {ReactElement} from 'react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {FileBrowser} from './FileBrowser';
import {UploadQueueProvider} from './UploadQueueProvider';
import * as service from './fileBrowser.service';
import {triggerBrowserDownload} from './fileBrowser.download';
import {getSessionCredentials} from '../../lib/awsCredentials';
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

const mock = vi.mocked(service);

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
      <FileBrowser
        bucket="my-bucket"
        prefix="alice/"
        rootPrefix="alice/"
        rootLabel="My Files"
        markerKey="alice/DO_NOT_DELETE.txt"
        writable
        username="alice"
        {...props}
      />
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

  it('shows an empty-folder message when the listing is empty', async () => {
    mock.listFiles.mockResolvedValue(ok(page({files: [], folders: []})));
    renderBrowser();
    expect(await screen.findByText('This folder is empty')).toBeInTheDocument();
  });

  it('surfaces a listing error as an alert', async () => {
    mock.listFiles.mockResolvedValue(fail('Bucket is on fire'));
    renderBrowser();
    const alert = await screen.findByRole('alert');
    expect(within(alert).getByText('Bucket is on fire')).toBeInTheDocument();
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
    expect(mock.listFiles).toHaveBeenLastCalledWith('my-bucket', 'alice/', 't1');
  });
});

describe('FileBrowser — navigation', () => {
  it('drills into a folder and back out via the breadcrumb', async () => {
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'Open folder docs'}));
    await waitFor(() => expect(mock.listFiles).toHaveBeenLastCalledWith('my-bucket', 'alice/docs/', undefined));
    expect(screen.getByText('docs', {selector: '[aria-current="page"]'})).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'My Files'}));
    await waitFor(() => expect(mock.listFiles).toHaveBeenLastCalledWith('my-bucket', 'alice/', undefined));
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
    await waitFor(() => expect(mock.listFiles).toHaveBeenLastCalledWith('my-bucket', 'alice/', undefined));
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

  it('renames a folder from its details panel', async () => {
    const {user} = renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'Details for docs'}));
    await user.click(await screen.findByRole('button', {name: 'Rename docs'}));
    const dialog = await screen.findByRole('dialog', {name: /rename/i});
    const input = within(dialog).getByRole('textbox');
    await user.clear(input);
    await user.type(input, 'archive');
    await user.click(within(dialog).getByRole('button', {name: /rename|save/i}));
    await waitFor(() => expect(mock.moveFolder).toHaveBeenCalled());
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
