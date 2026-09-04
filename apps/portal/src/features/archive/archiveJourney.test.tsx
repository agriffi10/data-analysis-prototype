import {beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';

/**
 * The whole archive flow and the whole restore flow, performed (SPEC-172 FR-007 AC5).
 *
 * Real hooks, real dialogs, the real `FileBrowser` — only the service boundary is mocked, which
 * here is the S3 listing service and the API client the enqueue reaches through. Mocking
 * `archive.service` instead would leave the two things this test exists to check — that the
 * browser builds the right REQUEST, and that a success clears the selection — asserted against a
 * stub of itself.
 *
 * The enqueued body no longer carries `mode` or a token: the API stamps both from the route and
 * the verified bearer, and refuses a body that claims either.
 */
vi.mock('../file-browser/fileBrowser.service', async (importActual) => ({
  ...(await importActual<typeof import('../file-browser/fileBrowser.service')>()),
  ensurePrefixMarker: vi.fn().mockResolvedValue({success: true}),
  listFiles: vi.fn(),
  getObjectMetadata: vi.fn().mockResolvedValue({
    success: true,
    data: {
      key: 'alice/notes.txt',
      contentType: 'text/plain',
      size: 10,
      lastModified: new Date('2026-01-01'),
      etag: '"abc"',
      storageClass: 'STANDARD',
      userMetadata: {}
    }
  }),
  objectExists: vi.fn().mockResolvedValue({success: true, data: true})
}));
vi.mock('../../lib/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/apiClient')>()),
  apiRequest: vi.fn()
}));
import {FileOpsInFlightProvider, UploadQueueProvider} from '../file-browser';
import {FileBrowser} from '../file-browser/FileBrowser';
import {listFiles} from '../file-browser/fileBrowser.service';
import {apiRequest} from '../../lib/apiClient';
import {apiFailure, mockApi} from '../../test/apiMock';
import type {ApiMock} from '../../test/apiMock';

const ARCHIVE_ID = '3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93';

/**
 * The API, programmed by route id. Both archive routes answer success by default; a test that
 * needs a failure re-programs the one it drives.
 *
 * The notifications inbox is programmed too, and it is not incidental: the browser shell polls it
 * behind every one of these journeys, so an assertion written as "no request was made at all"
 * would be asserting the absence of a poll rather than the absence of an enqueue. Every count
 * below names its route for that reason.
 */
function programmedApi(): ApiMock {
  const api = mockApi(vi.mocked(apiRequest));
  api.on('archive.archive', {success: true, data: {requestId: 'r-1'}});
  api.on('archive.restore', {success: true, data: {requestId: 'r-2'}});
  api.on('objects.readContent', apiFailure('NotFound'));
  return api;
}

function listing(prefix: string) {
  const rows: Record<string, {files: unknown[]; folders: unknown[]}> = {
    'alice/': {
      files: [
        {type: 'file', key: 'alice/notes.txt', name: 'notes.txt', size: 10, lastModified: new Date('2026-01-01')}
      ],
      folders: [
        {type: 'folder', prefix: 'alice/reports/', name: 'reports'},
        {type: 'folder', prefix: 'alice/archive/', name: 'archive'},
        {type: 'folder', prefix: 'alice/athenaresults/', name: 'athenaresults'}
      ]
    },
    'alice/archive/': {
      files: [],
      folders: [{type: 'folder', prefix: `alice/archive/${ARCHIVE_ID}/`, name: ARCHIVE_ID}]
    },
    'alice/athenaresults/': {
      files: [
        {
          type: 'file',
          key: 'alice/athenaresults/q1.csv',
          name: 'q1.csv',
          size: 10,
          lastModified: new Date('2026-01-01')
        }
      ],
      folders: []
    }
  };
  return {success: true, data: {...(rows[prefix] ?? {files: [], folders: []}), nextToken: undefined}};
}

/**
 * Open the `system_settings` group row. `athenaresults/` and `archive/` are inside it, so
 * every path that reaches one of them starts here — which is also what these tests are
 * asserting stays reachable now that the row collapses them by default.
 */
async function expandSystemFolders(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', {name: /^system_settings:/}));
}

function renderBrowser(props: Partial<Parameters<typeof FileBrowser>[0]> = {}) {
  return renderWithProviders(
    <UploadQueueProvider>
      <FileOpsInFlightProvider>
        <FileBrowser
          bucket="user-space"
          rootPrefix="alice/"
          rootLabel="My Files"
          username="alice"
          writable
          spaceKind="personal"
          {...props}
        />
      </FileOpsInFlightProvider>
    </UploadQueueProvider>,
    {auth: authenticated('alice')}
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.mocked(listFiles).mockImplementation((_bucket, prefix) => Promise.resolve(listing(prefix ?? 'alice/')) as never);
});

describe('the archive journey', () => {
  it('selects, opens, confirms and enqueues — then clears the selection', async () => {
    const user = userEvent.setup();
    const api = programmedApi();
    renderBrowser();

    await user.click(await screen.findByRole('checkbox', {name: 'Select folder reports'}));
    await user.click(screen.getByRole('button', {name: 'Archive selected items'}));

    const dialog = await screen.findByRole('alertdialog', {name: 'Confirm archive'});
    expect(within(dialog).getByRole('heading', {name: /Archive the folder “reports\/”/})).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', {name: 'Archive'}));

    expect(api.countOf('archive.archive')).toBe(1);
    expect(api.bodyFor('archive.archive')).toEqual({
      requestId: expect.any(String),
      source: {space: {kind: 'personal', name: 'alice'}, items: [{kind: 'folder', key: 'alice/reports/'}]}
    });
    expect(screen.queryByRole('alertdialog', {name: 'Confirm archive'})).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', {name: 'Select folder reports'})).not.toBeChecked();
  });

  it('takes the WHOLE selection, unlike the data-quality check beside it', async () => {
    const user = userEvent.setup();
    const api = programmedApi();
    renderBrowser();

    await user.click(await screen.findByRole('checkbox', {name: 'Select folder reports'}));
    await user.click(screen.getByRole('checkbox', {name: 'Select notes.txt'}));
    await user.click(screen.getByRole('button', {name: 'Archive selected items'}));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Archive'}));

    expect((api.bodyFor('archive.archive') as {source: {items: unknown}}).source.items).toEqual([
      {kind: 'folder', key: 'alice/reports/'},
      {kind: 'file', key: 'alice/notes.txt'}
    ]);
  });

  it('confirms it STARTED, never that it finished', async () => {
    const user = userEvent.setup();
    programmedApi();
    renderBrowser();

    await user.click(await screen.findByRole('checkbox', {name: 'Select folder reports'}));
    await user.click(screen.getByRole('button', {name: 'Archive selected items'}));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Archive'}));

    expect(await screen.findByText(/Archive started/i)).toBeInTheDocument();
  });

  it('keeps the dialog and the selection when the enqueue fails', async () => {
    // The selection is what a retry needs. Clearing it on failure leaves a dialog with nothing
    // to send — the defect SPEC-167's own journey test caught on the send flow.
    const user = userEvent.setup();
    const api = programmedApi();
    api.on('archive.archive', apiFailure('ApiUnavailable'));
    renderBrowser();

    await user.click(await screen.findByRole('checkbox', {name: 'Select folder reports'}));
    await user.click(screen.getByRole('button', {name: 'Archive selected items'}));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Archive'}));

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.getByRole('alertdialog', {name: 'Confirm archive'})).toBeInTheDocument();
    expect(screen.getByRole('checkbox', {name: 'Select folder reports'})).toBeChecked();
  });

  it('archives one item from its details panel, without a selection', async () => {
    // The other of the two homes a per-item action has here: there is no context menu, so this
    // is the only route to archiving something you have not ticked.
    const user = userEvent.setup();
    const api = programmedApi();
    renderBrowser();

    await user.click(await screen.findByRole('button', {name: 'Details for notes.txt'}));
    await user.click(await screen.findByRole('button', {name: 'Archive this item'}));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Archive'}));

    expect((api.bodyFor('archive.archive') as {source: {items: unknown}}).source.items).toEqual([
      {kind: 'file', key: 'alice/notes.txt'}
    ]);
  });

  it('refuses a portal-managed root with an explanation rather than a silent no-op', async () => {
    // FR-001 AC5, mirroring the plane's own `reserved_folder` refusal. Disabled and SAYING WHY:
    // the control stays focusable, so the reason is reachable rather than only visible on hover.
    const user = userEvent.setup();
    const api = programmedApi();
    renderBrowser();

    await expandSystemFolders(user);
    await user.click(await screen.findByRole('checkbox', {name: 'Select folder athenaresults'}));
    const archive = screen.getByRole('button', {name: 'Archive selected items'});

    expect(archive).toHaveAttribute('aria-disabled', 'true');
    expect(archive).toHaveAttribute('title', expect.stringContaining('athenaresults'));
    await user.click(archive);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(api.countOf('archive.archive')).toBe(0);
  });

  it('refuses a file inside a reserved root FROM ITS DETAILS PANEL too', async () => {
    // Found in review, and it is the failure FR-001 AC5's list-equality test exists to prevent
    // arriving through the entry point that test does not walk: `athenaresults/` is VISIBLE, so a
    // file inside it is reachable and openable, and the panel offered an Archive the plane then
    // refused as `reserved_folder`. The toolbar had the guard; the file panel had none.
    const user = userEvent.setup();
    const api = programmedApi();
    renderBrowser();

    await expandSystemFolders(user);
    await user.click(await screen.findByRole('button', {name: 'Open folder athenaresults'}));
    await user.click(await screen.findByRole('button', {name: 'Details for q1.csv'}));
    const archive = await screen.findByRole('button', {name: 'Archive this item'});

    expect(archive).toHaveAttribute('aria-disabled', 'true');
    expect(archive).toHaveAttribute('title', expect.stringContaining('athenaresults'));
    await user.click(archive);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(api.countOf('archive.archive')).toBe(0);
  });

  it('is absent entirely in a read-only space', async () => {
    // Removed, not disabled — SPEC-163's rule, and here it is also simply true: the dev-unauth
    // path has no username and therefore no space to archive from.
    renderBrowser({writable: false, username: undefined});

    expect(await screen.findByText('notes.txt')).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Archive selected items'})).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Restore Archived Data'})).not.toBeInTheDocument();
  });
});

describe('the restore journey', () => {
  it('opens from the toolbar, validates the id and enqueues a restore', async () => {
    const user = userEvent.setup();
    const api = programmedApi();
    renderBrowser();

    await user.click(await screen.findByRole('button', {name: 'Restore Archived Data'}));
    const dialog = await screen.findByRole('dialog', {name: 'Restore archived data'});

    await user.type(within(dialog).getByLabelText('Archive id'), 'nope');
    await user.click(within(dialog).getByRole('button', {name: 'Restore'}));
    expect(api.countOf('archive.restore')).toBe(0);

    await user.clear(within(dialog).getByLabelText('Archive id'));
    await user.type(within(dialog).getByLabelText('Archive id'), ARCHIVE_ID);
    await user.click(within(dialog).getByRole('button', {name: 'Restore'}));

    expect(api.countOf('archive.restore')).toBe(1);
    expect(api.bodyFor('archive.restore')).toEqual({
      requestId: expect.any(String),
      space: {kind: 'personal', name: 'alice'},
      archiveId: ARCHIVE_ID
    });
    expect(screen.queryByRole('dialog', {name: 'Restore archived data'})).not.toBeInTheDocument();
    expect(await screen.findByText(/Restore started/i)).toBeInTheDocument();
  });

  it('names the space it will restore into', async () => {
    const user = userEvent.setup();
    programmedApi();
    renderBrowser();

    await user.click(await screen.findByRole('button', {name: 'Restore Archived Data'}));

    expect(within(await screen.findByRole('dialog')).getByText('My Files')).toBeInTheDocument();
  });
});

describe('the archive folder is read-only in the browser', () => {
  async function browseIntoArchive(user: ReturnType<typeof userEvent.setup>) {
    renderBrowser();
    await expandSystemFolders(user);
    await user.click(await screen.findByRole('button', {name: 'Open folder archive'}));
    return screen.findByText(ARCHIVE_ID);
  }

  it('is reachable in one click, because the folder names ARE the archive ids', async () => {
    const user = userEvent.setup();
    await browseIntoArchive(user);

    expect(screen.getByText(ARCHIVE_ID)).toBeInTheDocument();
  });

  it('disables Upload and New folder with a reason, rather than producing an AccessDenied', async () => {
    // FR-004 AC4. IAM denies the write; without this the user meets a bare AccessDenied for a
    // rule this application itself wrote.
    const user = userEvent.setup();
    await browseIntoArchive(user);

    for (const name of ['Upload', 'New folder']) {
      const control = screen.getByRole('button', {name});
      expect(control).toHaveAttribute('aria-disabled', 'true');
      expect(control).toHaveAttribute('title', expect.stringMatching(/read-only/i));
    }
  });

  it('removes Archive inside it — an archive of an archive is not a thing', async () => {
    const user = userEvent.setup();
    await browseIntoArchive(user);

    expect(screen.queryByRole('button', {name: 'Archive selected items'})).not.toBeInTheDocument();
  });

  it('refuses Move and Delete on a selection inside it, with the same reason', async () => {
    const user = userEvent.setup();
    await browseIntoArchive(user);
    await user.click(screen.getByRole('checkbox', {name: `Select folder ${ARCHIVE_ID}`}));

    for (const name of ['Move selected items', 'Delete selected items']) {
      expect(screen.getByRole('button', {name})).toHaveAttribute('aria-disabled', 'true');
    }
  });

  it('KEEPS Restore Archived Data, which is the whole reason to be in this folder', async () => {
    // Found in review. A restore writes into the space ROOT, never into the folder being browsed,
    // so the write lock is the wrong gate for it — and gating it here removed the button from the
    // one place the dialog itself tells the user to go and find an id.
    const user = userEvent.setup();
    await browseIntoArchive(user);

    expect(screen.getByRole('button', {name: 'Restore Archived Data'})).toBeInTheDocument();
  });

  it('says why, VISIBLY, not only in a tooltip', async () => {
    // FR-004 AC4 asks for an explanation. A `title` needs a hover, so at the 400px width this
    // feature's own live check is run at, the greyed controls would say nothing at all: the tap
    // does nothing and no reason appears anywhere.
    const user = userEvent.setup();
    await browseIntoArchive(user);

    expect(screen.getByRole('note')).toHaveTextContent(/read-only/i);
  });

  it('leaves Details available, because a receipt is meant to be read', async () => {
    // FR-004 AC6. The whole point of the folder being visible: the receipt downloads through the
    // existing path, and the id is readable from the folder name without opening anything.
    const user = userEvent.setup();
    await browseIntoArchive(user);

    expect(screen.getByRole('button', {name: `Details for ${ARCHIVE_ID}`})).toBeInTheDocument();
  });
});
