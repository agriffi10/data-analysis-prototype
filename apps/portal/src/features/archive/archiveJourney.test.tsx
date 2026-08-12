import {beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';

/**
 * The whole archive flow and the whole restore flow, performed (SPEC-172 FR-007 AC5).
 *
 * Real hooks, real dialogs, the real `FileBrowser` — only the AWS boundary is mocked, which here
 * is the S3 listing service and the SQS client the enqueue reaches through (SPEC-154's
 * discipline). Mocking `archive.service` instead would leave the two things this test exists to
 * check — that the browser builds the right REQUEST, and that a success clears the selection —
 * asserted against a stub of itself.
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
vi.mock('../../lib/sqsClient', () => ({getSqsClient: vi.fn()}));
vi.mock('../../lib/awsCredentials', () => ({
  getIdToken: vi.fn().mockResolvedValue({success: true, data: 'id-token-abc'}),
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}})
}));

import {UploadQueueProvider} from '../file-browser';
import {FileBrowser} from '../file-browser/FileBrowser';
import {listFiles} from '../file-browser/fileBrowser.service';
import {getSqsClient} from '../../lib/sqsClient';

const ARCHIVE_ID = '3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93';

type Cmd = {input: Record<string, unknown>};

function fakeQueue() {
  const send = vi.fn<(cmd: Cmd) => Promise<{MessageId: string}>>().mockResolvedValue({MessageId: 'm1'});
  vi.mocked(getSqsClient).mockResolvedValue({success: true, data: {send}} as never);
  return send;
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
    }
  };
  return {success: true, data: {...(rows[prefix] ?? {files: [], folders: []}), nextToken: undefined}};
}

function renderBrowser(props: Partial<Parameters<typeof FileBrowser>[0]> = {}) {
  return renderWithProviders(
    <UploadQueueProvider>
      <FileBrowser
        bucket="user-space"
        rootPrefix="alice/"
        rootLabel="My Files"
        username="alice"
        writable
        spaceKind="personal"
        {...props}
      />
    </UploadQueueProvider>,
    {auth: authenticated('alice')}
  );
}

/** The parsed body of the one message the browser enqueued. */
function enqueued(send: ReturnType<typeof fakeQueue>) {
  return JSON.parse(send.mock.calls[0][0].input.MessageBody as string);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv('VITE_ARCHIVE_QUEUE_URL', 'https://sqs.us-east-1.amazonaws.com/1/dat-prod-archive-requests.fifo');
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.mocked(listFiles).mockImplementation((_bucket, prefix) => Promise.resolve(listing(prefix ?? 'alice/')) as never);
});

describe('the archive journey', () => {
  it('selects, opens, confirms and enqueues — then clears the selection', async () => {
    const user = userEvent.setup();
    const send = fakeQueue();
    renderBrowser();

    await user.click(await screen.findByRole('checkbox', {name: 'Select folder reports'}));
    await user.click(screen.getByRole('button', {name: 'Archive selected items'}));

    const dialog = await screen.findByRole('alertdialog', {name: 'Confirm archive'});
    expect(within(dialog).getByRole('heading', {name: /Archive the folder “reports\/”/})).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', {name: 'Archive'}));

    expect(send).toHaveBeenCalledTimes(1);
    expect(enqueued(send)).toEqual({
      requestId: expect.any(String),
      mode: 'archive',
      actor: 'id-token-abc',
      source: {space: {kind: 'personal', name: 'alice'}, items: [{kind: 'folder', key: 'alice/reports/'}]}
    });
    expect(screen.queryByRole('alertdialog', {name: 'Confirm archive'})).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', {name: 'Select folder reports'})).not.toBeChecked();
  });

  it('takes the WHOLE selection, unlike the data-quality check beside it', async () => {
    const user = userEvent.setup();
    const send = fakeQueue();
    renderBrowser();

    await user.click(await screen.findByRole('checkbox', {name: 'Select folder reports'}));
    await user.click(screen.getByRole('checkbox', {name: 'Select notes.txt'}));
    await user.click(screen.getByRole('button', {name: 'Archive selected items'}));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Archive'}));

    expect(enqueued(send).source.items).toEqual([
      {kind: 'folder', key: 'alice/reports/'},
      {kind: 'file', key: 'alice/notes.txt'}
    ]);
  });

  it('confirms it STARTED, never that it finished', async () => {
    const user = userEvent.setup();
    fakeQueue();
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
    const send = fakeQueue();
    send.mockRejectedValueOnce(new Error('network down'));
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
    const send = fakeQueue();
    renderBrowser();

    await user.click(await screen.findByRole('button', {name: 'Details for notes.txt'}));
    await user.click(await screen.findByRole('button', {name: 'Archive this item'}));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', {name: 'Archive'}));

    expect(enqueued(send).source.items).toEqual([{kind: 'file', key: 'alice/notes.txt'}]);
  });

  it('refuses a portal-managed root with an explanation rather than a silent no-op', async () => {
    // FR-001 AC5, mirroring the plane's own `reserved_folder` refusal. Disabled and SAYING WHY:
    // the control stays focusable, so the reason is reachable rather than only visible on hover.
    const user = userEvent.setup();
    const send = fakeQueue();
    renderBrowser();

    await user.click(await screen.findByRole('checkbox', {name: 'Select folder athenaresults'}));
    const archive = screen.getByRole('button', {name: 'Archive selected items'});

    expect(archive).toHaveAttribute('aria-disabled', 'true');
    expect(archive).toHaveAttribute('title', expect.stringContaining('athenaresults'));
    await user.click(archive);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(send).not.toHaveBeenCalled();
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
    const send = fakeQueue();
    renderBrowser();

    await user.click(await screen.findByRole('button', {name: 'Restore Archived Data'}));
    const dialog = await screen.findByRole('dialog', {name: 'Restore archived data'});

    await user.type(within(dialog).getByLabelText('Archive id'), 'nope');
    await user.click(within(dialog).getByRole('button', {name: 'Restore'}));
    expect(send).not.toHaveBeenCalled();

    await user.clear(within(dialog).getByLabelText('Archive id'));
    await user.type(within(dialog).getByLabelText('Archive id'), ARCHIVE_ID);
    await user.click(within(dialog).getByRole('button', {name: 'Restore'}));

    expect(enqueued(send)).toEqual({
      requestId: expect.any(String),
      mode: 'restore',
      actor: 'id-token-abc',
      space: {kind: 'personal', name: 'alice'},
      archiveId: ARCHIVE_ID
    });
    expect(screen.queryByRole('dialog', {name: 'Restore archived data'})).not.toBeInTheDocument();
    expect(await screen.findByText(/Restore started/i)).toBeInTheDocument();
  });

  it('names the space it will restore into', async () => {
    const user = userEvent.setup();
    fakeQueue();
    renderBrowser();

    await user.click(await screen.findByRole('button', {name: 'Restore Archived Data'}));

    expect(within(await screen.findByRole('dialog')).getByText('My Files')).toBeInTheDocument();
  });
});

describe('the archive folder is read-only in the browser', () => {
  async function browseIntoArchive(user: ReturnType<typeof userEvent.setup>) {
    renderBrowser();
    await user.click(await screen.findByRole('button', {name: 'Open folder archive'}));
    return screen.findByText(ARCHIVE_ID);
  }

  it('is visible, because the folder names ARE the archive ids', async () => {
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

  it('leaves Details available, because a receipt is meant to be read', async () => {
    // FR-004 AC6. The whole point of the folder being visible: the receipt downloads through the
    // existing path, and the id is readable from the folder name without opening anything.
    const user = userEvent.setup();
    await browseIntoArchive(user);

    expect(screen.getByRole('button', {name: `Details for ${ARCHIVE_ID}`})).toBeInTheDocument();
  });
});
