import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {toUserMessage} from '../../lib/errorMessages';
import type {ReactElement} from 'react';
import {act} from '@testing-library/react';
import {createTestQueryClient, renderWithProviders} from '../../test/renderWithProviders';
import {notificationsKeys} from '../notifications';
import {authenticated} from '../../test/authFixtures';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {FileBrowser} from './FileBrowser';
import {UploadQueueProvider} from './UploadQueueProvider';
import {FileOpsInFlightProvider} from './FileOpsInFlightProvider';
import {InFlightOperations} from './InFlightOperations';
import * as service from './fileBrowser.service';
import {submitFileOperation} from './fileOps.service';
import {getNotifications} from '../notifications/notifications.service';
import {getFeatureFlags} from '../feature-flags/featureFlags.service';
import {FEATURE_FLAG_DEFAULTS} from '../feature-flags';
import type {FileListPage, S3FileItem, S3FolderItem} from '../../types/s3.types';

/**
 * SPEC-190 — the browser's async model, driven through the real file browser.
 *
 * Integration style (react.md §21): the REAL dispatcher, the REAL dialogs, the REAL in-flight
 * store, and only the AWS boundary mocked. Two boundaries matter here and they are asserted
 * AGAINST each other throughout: `submitFileOperation` (the plane) and the synchronous
 * copy/move/delete primitives (the browser's own loop). "It worked" is never the assertion —
 * WHICH of the two ran is.
 */
vi.mock('./fileBrowser.service', async (importActual) => {
  const actual = await importActual<typeof service>();
  return {
    ...actual,
    listFiles: vi.fn(),
    getObjectMetadata: vi.fn(),
    folderExists: vi.fn(),
    deleteObject: vi.fn(),
    moveObject: vi.fn(),
    copyObject: vi.fn(),
    firstFreeName: vi.fn(),
    getDownloadUrl: vi.fn(),
    uploadFile: vi.fn(),
    createFolder: vi.fn()
  };
});
vi.mock('./fileOps.service', () => ({submitFileOperation: vi.fn()}));
vi.mock('./fileBrowser.download', () => ({triggerBrowserDownload: vi.fn()}));
vi.mock('../data-quality/dataQuality.service', () => ({enqueueQualityCheck: vi.fn()}));
vi.mock('../file-send/fileSend.service', () => ({enqueueFileSend: vi.fn()}));
vi.mock('../user-directory/userDirectory.service', () => ({
  getUserDirectory: vi.fn().mockResolvedValue({success: true, data: {usernames: [], generatedAt: null}}),
  DIRECTORY_KEY: '_directory/usernames.json'
}));
vi.mock('../shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn().mockResolvedValue({success: true, data: {version: 1, connections: []}}),
  enqueueSharedSpaceRequest: vi.fn()
}));
vi.mock('../notifications/notifications.service', () => ({
  getNotifications: vi.fn(),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));
vi.mock('../feature-flags/featureFlags.service', async (importActual) => ({
  ...(await importActual<typeof import('../feature-flags/featureFlags.service')>()),
  getFeatureFlags: vi.fn()
}));

const mock = vi.mocked(service);
const mockSubmit = vi.mocked(submitFileOperation);
const ok = <T,>(data: T) => ({success: true as const, data});

const file = (name: string): S3FileItem => ({
  type: 'file',
  key: `alice/${name}`,
  name,
  size: 10,
  lastModified: new Date('2026-03-04T00:00:00Z')
});
const folder = (name: string): S3FolderItem => ({type: 'folder', prefix: `alice/${name}/`, name});
const page = (over: Partial<FileListPage> = {}): FileListPage => ({
  files: [file('report.csv'), file('notes.txt')],
  folders: [folder('docs')],
  isTruncated: false,
  ...over
});

function browser(props: Partial<Parameters<typeof FileBrowser>[0]> = {}): ReactElement {
  return (
    <UploadQueueProvider>
      <FileOpsInFlightProvider>
        <FileBrowser
          bucket="user-space"
          prefix="alice/"
          rootPrefix="alice/"
          rootLabel="My Files"
          writable
          username="alice"
          spaceKind="personal"
          destinations={[
            {id: 'personal', bucket: 'user-space', rootPrefix: 'alice/', kind: 'personal', label: 'alice'},
            {id: 'finance', bucket: 'shared-space', rootPrefix: 'finance/', kind: 'shared', label: 'finance'}
          ]}
          {...props}
        />
        {/* Mounted at the app shell in production, beside the provider — supplied here so the
            surface the browser's own gestures fill is in the tree. */}
        <InFlightOperations />
      </FileOpsInFlightProvider>
    </UploadQueueProvider>
  );
}

const render = (props: Partial<Parameters<typeof FileBrowser>[0]> = {}, queryClient = createTestQueryClient()) => ({
  ...renderWithProviders(browser(props), {auth: authenticated('alice'), seedFeatureFlags: false, queryClient}),
  queryClient
});

/**
 * Bring in whatever `getNotifications` now answers.
 *
 * Stands in for the header bell's own 60-second poll, which is what delivers an outcome in
 * production — mounted on every page, and the only always-mounted poller there is.
 */
async function pollNotifications(queryClient: ReturnType<typeof createTestQueryClient>) {
  await act(async () => {
    await queryClient.invalidateQueries({queryKey: notificationsKeys.list('alice')});
  });
}

/** Point the mocked reader at one flag set, as the real one would resolve it. */
function withFlags(overrides: Partial<typeof FEATURE_FLAG_DEFAULTS> = {}) {
  vi.mocked(getFeatureFlags).mockResolvedValue(ok({...FEATURE_FLAG_DEFAULTS, ...overrides}));
}

/** Tick one item and open the named bulk action. */
async function selectAnd(user: ReturnType<typeof render>['user'], itemLabel: string, action: string) {
  await user.click(await screen.findByRole('checkbox', {name: `Select ${itemLabel}`}));
  await user.click(screen.getByRole('button', {name: action}));
}

beforeEach(() => {
  vi.clearAllMocks();
  window.innerWidth = 1024;
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  withFlags();
  vi.mocked(getNotifications).mockResolvedValue(ok([]));
  mock.listFiles.mockResolvedValue(ok(page()));
  mock.folderExists.mockResolvedValue(ok(true));
  mock.deleteObject.mockResolvedValue(ok({key: 'alice/report.csv'}));
  mock.moveObject.mockResolvedValue(ok({destKey: 'alice/docs/report.csv'}));
  mock.copyObject.mockResolvedValue(ok({destKey: 'alice/docs/report.csv'}));
  mock.firstFreeName.mockImplementation(async ({baseName, kind}) => {
    const dot = kind === 'folder' ? -1 : baseName.lastIndexOf('.');
    return ok(dot <= 0 ? `${baseName} (1)` : `${baseName.slice(0, dot)} (1)${baseName.slice(dot)}`);
  });
  mockSubmit.mockResolvedValue({success: true, data: undefined});
});

afterEach(() => {
  vi.unstubAllEnvs();
});

// ─── FR-001: the routing decision ───────────────────────────────────────────

describe('exactly one FILE stays in the browser, byte for byte (FR-001 AC8)', () => {
  it('deletes one file synchronously', async () => {
    const {user} = render();
    await selectAnd(user, 'report.csv', 'Delete selected items');
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    await waitFor(() => expect(mock.deleteObject).toHaveBeenCalled());
    expect(mockSubmit).not.toHaveBeenCalled();
  });

  it('copies one file into another folder synchronously', async () => {
    const {user} = render();
    await selectAnd(user, 'report.csv', 'Copy selected items');
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', {name: 'Open folder docs'}));
    await user.click(within(dialog).getByRole('button', {name: 'Copy here'}));
    await waitFor(() => expect(mock.copyObject).toHaveBeenCalled());
    expect(mockSubmit).not.toHaveBeenCalled();
  });
});

describe('everything else is enqueued (FR-001 AC9)', () => {
  it('enqueues a delete of a single folder — and its body carries NONE of the copy/move fields', async () => {
    const {user} = render();
    await selectAnd(user, 'folder docs', 'Delete selected items');
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    await waitFor(() => expect(mockSubmit).toHaveBeenCalled());
    expect(mock.deleteObject).not.toHaveBeenCalled();
    expect(mockSubmit).toHaveBeenCalledTimes(1);
    expect(Object.keys(mockSubmit.mock.calls[0][0]).sort()).toEqual(['operation', 'requestId', 'source']);
  });

  it('enqueues a multi-item move with the chosen destination and NO targetName', async () => {
    const {user} = render();
    await user.click(await screen.findByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(await screen.findByRole('checkbox', {name: 'Select notes.txt'}));
    await user.click(screen.getByRole('button', {name: 'Move selected items'}));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', {name: 'Open folder docs'}));
    await user.click(within(dialog).getByRole('button', {name: 'Move here'}));
    await waitFor(() => expect(mockSubmit).toHaveBeenCalled());
    expect(mockSubmit).toHaveBeenCalledTimes(1);
    const request = mockSubmit.mock.calls[0][0];
    expect(request.operation !== 'delete' && request.destination.prefix).toBe('alice/docs/');
    expect(request.source.items.every((item) => item.targetName === undefined)).toBe(true);
  });

  it('sends onConflict "refuse" on a first submit — nothing here can flip it (FR-002 AC7)', async () => {
    const {user} = render();
    await user.click(await screen.findByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(await screen.findByRole('checkbox', {name: 'Select notes.txt'}));
    await user.click(screen.getByRole('button', {name: 'Copy selected items'}));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', {name: 'Open folder docs'}));
    await user.click(within(dialog).getByRole('button', {name: 'Copy here'}));
    await waitFor(() => expect(mockSubmit).toHaveBeenCalled());
    expect(mockSubmit).toHaveBeenCalledTimes(1);
    const request = mockSubmit.mock.calls[0][0];
    expect(request.operation !== 'delete' && request.onConflict).toBe('refuse');
  });
});

describe('the same-folder copy probes FIRST, then forks on the item kind (FR-001 AC2, AC4, AC5)', () => {
  it('a FOLDER is enqueued with the probed name, and the probe runs once', async () => {
    const {user} = render();
    await selectAnd(user, 'folder docs', 'Copy selected items');
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', {name: 'Copy here'}));
    expect(await screen.findByText(/Copying into the same folder/)).toBeInTheDocument();
    // ONE request, where it used to be up to 999 sequential HeadObjects. A second same-folder
    // branch downstream would ask again and could propose a different name from the confirmed one.
    expect(mock.firstFreeName).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', {name: 'Copy'}));
    await waitFor(() => expect(mockSubmit).toHaveBeenCalled());
    expect(mock.firstFreeName).toHaveBeenCalledTimes(1);
    expect(mock.copyObject).not.toHaveBeenCalled();
    expect(mockSubmit).toHaveBeenCalledTimes(1);
    expect(mockSubmit.mock.calls[0][0].source.items).toEqual([
      {kind: 'folder', key: 'alice/docs/', targetName: 'docs (1)'}
    ]);
  });

  it('a FILE takes the synchronous same-folder copy under the confirmed name', async () => {
    const {user} = render();
    await selectAnd(user, 'notes.txt', 'Copy selected items');
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', {name: 'Copy here'}));
    expect(await screen.findByText(/Copying into the same folder/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'Copy'}));
    await waitFor(() => expect(mock.copyObject).toHaveBeenCalled());
    expect(mockSubmit).not.toHaveBeenCalled();
    expect(mock.copyObject).toHaveBeenCalledTimes(1);
    expect(mock.copyObject.mock.calls[0][0]).toMatchObject({destKey: 'alice/notes (1).txt'});
  });

  // A FILE named like the app's folder is not that folder, and nothing downstream refuses it, but
  // `system_settings` is refused by name alone, and a file's refusal names a file.
  it.each([
    {
      label: 'folder docs',
      prefix: 'alice/',
      opens: [],
      value: 'shared_tables',
      refusal: '“shared_tables” is a folder the app manages at the top of a space. Pick another name.'
    },
    {
      label: 'folder q1',
      prefix: 'alice/docs/',
      opens: ['docs'],
      value: 'user_settings',
      refusal: '“user_settings” is a name the app keeps for its own folders. Pick another name.'
    },
    {label: 'notes.txt', prefix: 'alice/', opens: [], value: 'shared_tables', refusal: null},
    {
      label: 'notes.txt',
      prefix: 'alice/',
      opens: [],
      value: 'system_settings',
      refusal: '“system_settings” is a folder the app manages. Pick another name.'
    },
    {label: 'notes.txt', prefix: 'alice/', opens: [], value: 'a/b', refusal: 'File name cannot contain “/”.'}
  ])(
    'checks the name a copy of $label would land under as “$value” in $prefix',
    async ({label, prefix, opens, value, refusal}) => {
      // The picker starts at the space root, so a copy into a subfolder opens its way back there.
      const q1: S3FolderItem = {type: 'folder', prefix: 'alice/docs/q1/', name: 'q1'};
      mock.listFiles.mockImplementation(async (_bucket, listed) =>
        ok(listed === 'alice/docs/' ? page({files: [], folders: [q1]}) : page())
      );
      const {user} = render({prefix});
      await selectAnd(user, label, 'Copy selected items');
      const picker = await screen.findByRole('dialog');
      for (const name of opens)
        await user.click(await within(picker).findByRole('button', {name: `Open folder ${name}`}));
      await user.click(await within(picker).findByRole('button', {name: 'Copy here'}));
      const input = await screen.findByLabelText('Name for the copy');
      await user.clear(input);
      await user.type(input, value);

      const form = screen.getByRole('dialog', {name: 'Copy to folder'});
      expect(input).toHaveAccessibleDescription(refusal ?? '');
      expect(input.hasAttribute('aria-invalid')).toBe(refusal !== null);
      expect(within(form).getByRole('button', {name: 'Copy'})).toHaveProperty('disabled', refusal !== null);
    }
  );
});

describe('a failed enqueue says why (FR-002 AC8)', () => {
  // Driven with a code the enqueue path can ACTUALLY produce. It used to be `NotConfigured`,
  // which the browser can no longer mint at all — the queue URLs are the API's configuration now
  // — so the one flow-level assertion that a failed enqueue reaches a rendered sentence was
  // anchored to a case nothing can reach.
  it('surfaces the mapped message rather than doing nothing', async () => {
    mockSubmit.mockResolvedValue({
      success: false,
      error: {message: 'the queue is unavailable', code: 'ApiUnavailable'}
    });
    const {user} = render();
    await selectAnd(user, 'folder docs', 'Delete selected items');
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    expect(await screen.findByText(toUserMessage({code: 'ApiUnavailable'}).message)).toBeInTheDocument();
  });
});

// ─── FR-003: in-flight state ────────────────────────────────────────────────

describe('in-flight state', () => {
  it('acknowledges ACCEPTANCE, not completion, and shows what is running', async () => {
    const {user} = render();
    await selectAnd(user, 'folder docs', 'Delete selected items');
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    // "Deleted" would be a false statement here — the plane has not started yet.
    expect(await screen.findByText(/Delete requested — you’ll get a notification/)).toBeInTheDocument();
    const region = await screen.findByRole('region', {name: 'File operations in progress'});
    expect(within(region).getByText('Deleting docs')).toBeInTheDocument();
    // No percentage: the browser's own progress loop is gone and the plane reports only at the end.
    expect(within(region).queryByText('%')).toBeNull();
  });

  it('settles the entry when a notification carrying its requestId arrives', async () => {
    const {user, queryClient} = render();
    await selectAnd(user, 'folder docs', 'Delete selected items');
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    await screen.findByRole('region', {name: 'File operations in progress'});
    expect(mockSubmit).toHaveBeenCalledTimes(1);
    const requestId = mockSubmit.mock.calls[0][0].requestId;

    vi.mocked(getNotifications).mockResolvedValue(
      ok([
        {
          id: 'n1',
          message: 'Deleted 3 items.',
          read: false,
          timestamp: '2026-08-23T00:00:00Z',
          payload: {requestId, operation: 'delete'}
        }
      ])
    );
    await pollNotifications(queryClient);
    await waitFor(() => expect(screen.getByText(/Finished — see your notifications/)).toBeInTheDocument());
  });

  it('reads a payload with no operation as REFUSED — the whole-request failure shape', async () => {
    const {user, queryClient} = render();
    await selectAnd(user, 'folder docs', 'Delete selected items');
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    await screen.findByRole('region', {name: 'File operations in progress'});
    expect(mockSubmit).toHaveBeenCalledTimes(1);
    const requestId = mockSubmit.mock.calls[0][0].requestId;

    // `focommon.notify.request_payload` carries the request id and nothing else — the bounded
    // lock give-up arrives this way.
    vi.mocked(getNotifications).mockResolvedValue(
      ok([
        {
          id: 'n1',
          message: 'Your delete could not be started.',
          read: false,
          timestamp: '2026-08-23T00:00:00Z',
          payload: {requestId}
        }
      ])
    );
    await pollNotifications(queryClient);
    await waitFor(() => expect(screen.getByText(/Didn’t finish — see your notifications/)).toBeInTheDocument());
  });

  it('gates a SECOND submit in the same space, and says why on the control', async () => {
    const {user} = render();
    await selectAnd(user, 'folder docs', 'Delete selected items');
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    await screen.findByRole('region', {name: 'File operations in progress'});

    // A second selection that would ENQUEUE — two files.
    await user.click(await screen.findByRole('checkbox', {name: 'Select notes.txt'}));
    await user.click(await screen.findByRole('checkbox', {name: 'Select report.csv'}));
    const move = screen.getByRole('button', {name: 'Move selected items'});
    await waitFor(() => expect(move).toHaveAttribute('aria-disabled', 'true'));
    expect(move.getAttribute('title')).toMatch(/still running here/);
    // Read-only actions from other planes are NOT gated: this lock does not serialize them.
    expect(screen.getByRole('button', {name: 'Send to another user'})).not.toHaveAttribute('aria-disabled');
  });

  it('does NOT gate a selection that would stay in the browser', async () => {
    // The gate exists to keep this session from racing its own plane run. A single file never
    // reaches the plane, so refusing it would take away something the user could do before — which
    // is the one thing this switchover may not do.
    const {user} = render();
    await selectAnd(user, 'folder docs', 'Delete selected items');
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    await screen.findByRole('region', {name: 'File operations in progress'});

    await user.click(await screen.findByRole('checkbox', {name: 'Select notes.txt'}));
    expect(screen.getByRole('button', {name: 'Move selected items'})).not.toHaveAttribute('aria-disabled');
    await user.click(screen.getByRole('button', {name: 'Delete selected items'}));
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    await waitFor(() =>
      expect(mock.deleteObject).toHaveBeenCalledWith(expect.objectContaining({key: 'alice/notes.txt'}))
    );
  });

  it('puts the selection BACK when the enqueue is refused', async () => {
    // The dialogs clear on the way out, before the request resolves — the timing the synchronous
    // paths always had. A refusal would otherwise cost the user every tick they made.
    mockSubmit.mockResolvedValue({
      success: false,
      error: {
        message: 'That selection is too large to move in one go. Select fewer items and try again.',
        code: 'SelectionTooLarge'
      }
    });
    const {user} = render();
    await user.click(await screen.findByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(await screen.findByRole('checkbox', {name: 'Select notes.txt'}));
    await user.click(screen.getByRole('button', {name: 'Move selected items'}));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', {name: 'Open folder docs'}));
    await user.click(within(dialog).getByRole('button', {name: 'Move here'}));
    expect(
      await screen.findByText('That selection is too large to move in one go. Select fewer items and try again.')
    ).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('2 selected')).toBeInTheDocument());
  });

  it('does NOT put the selection back on a page the user has since left', async () => {
    // The refusal lands after the dialog closed, so the user may have turned the page. Restoring
    // then would select rows that are not on screen, and the toolbar acts on the selection.
    const refusal = 'That selection is too large to move in one go. Select fewer items and try again.';
    mock.listFiles.mockImplementation(async (_bucket, prefix, token) => {
      if (prefix !== 'alice/') return ok(page({files: [], folders: []}));
      return token === 'page-2'
        ? ok(page({files: [file('march.csv'), file('april.csv')], folders: []}))
        : ok(page({isTruncated: true, nextContinuationToken: 'page-2'}));
    });
    let refuse = (): void => undefined;
    mockSubmit.mockReturnValue(
      new Promise((resolve) => {
        refuse = () => resolve({success: false, error: {message: refusal, code: 'SelectionTooLarge'}});
      })
    );
    const {user} = render();
    await screen.findByText('report.csv');
    await user.click(screen.getByRole('button', {name: 'Next'}));
    await user.click(await screen.findByRole('checkbox', {name: 'Select march.csv'}));
    await user.click(screen.getByRole('checkbox', {name: 'Select april.csv'}));
    await user.click(screen.getByRole('button', {name: 'Move selected items'}));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', {name: 'Open folder docs'}));
    await user.click(within(dialog).getByRole('button', {name: 'Move here'}));
    await waitFor(() => expect(mockSubmit).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', {name: 'Prev'}));
    await screen.findByRole('checkbox', {name: 'Select report.csv'});

    await act(async () => refuse());

    expect(await screen.findByText(refusal)).toBeInTheDocument();
    await act(async () => undefined);
    expect(screen.queryByText('2 selected')).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', {name: 'Select report.csv'})).not.toBeChecked();
  });

  it('does NOT put the selection back when one of its rows has left the listing meanwhile', async () => {
    // EVERY item must still be on screen. Restoring the rest would select a row the user ticked
    // as part of a pair, beside one that is gone.
    const refusal = 'That selection is too large to move in one go. Select fewer items and try again.';
    let refuse = (): void => undefined;
    mockSubmit.mockReturnValue(
      new Promise((resolve) => {
        refuse = () => resolve({success: false, error: {message: refusal, code: 'SelectionTooLarge'}});
      })
    );
    const {user, queryClient} = render();
    await user.click(await screen.findByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(screen.getByRole('checkbox', {name: 'Select notes.txt'}));
    await user.click(screen.getByRole('button', {name: 'Move selected items'}));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', {name: 'Open folder docs'}));
    await user.click(within(dialog).getByRole('button', {name: 'Move here'}));
    await waitFor(() => expect(mockSubmit).toHaveBeenCalledTimes(1));
    mock.listFiles.mockResolvedValue(ok(page({files: [file('notes.txt')]})));
    await act(async () => {
      await queryClient.invalidateQueries();
    });
    await waitFor(() => expect(screen.queryByRole('checkbox', {name: 'Select report.csv'})).not.toBeInTheDocument());

    await act(async () => refuse());

    expect(await screen.findByText(refusal)).toBeInTheDocument();
    await act(async () => undefined);
    expect(screen.getByRole('checkbox', {name: 'Select notes.txt'})).not.toBeChecked();
  });

  it('keeps the selection when a DELETE enqueue is refused', async () => {
    mockSubmit.mockResolvedValue({
      success: false,
      error: {message: 'That selection is too large to do in one go', code: 'SelectionTooLarge'}
    });
    const {user} = render();
    await user.click(await screen.findByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(await screen.findByRole('checkbox', {name: 'Select notes.txt'}));

    await user.click(screen.getByRole('button', {name: 'Delete selected items'}));
    await user.click(await screen.findByRole('button', {name: 'Delete'}));

    expect(await screen.findByText('That selection is too large to do in one go')).toBeInTheDocument();
    expect(screen.getByText('2 selected')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', {name: 'Select report.csv'})).toBeChecked();
  });

  it('holds ARCHIVE for a single file too, because archive always reaches a plane', async () => {
    // The routing predicate speaks for file operations. Archive enqueues one file exactly as it
    // enqueues a folder, so asking that predicate on its behalf would leave it clickable over the
    // very items an in-flight run is relocating.
    const {user} = render();
    await selectAnd(user, 'folder docs', 'Delete selected items');
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    await screen.findByRole('region', {name: 'File operations in progress'});

    await user.click(await screen.findByRole('checkbox', {name: 'Select notes.txt'}));
    const archive = screen.getByRole('button', {name: 'Archive selected items'});
    await waitFor(() => expect(archive).toHaveAttribute('aria-disabled', 'true'));
    expect(archive.getAttribute('title')).toMatch(/still running here/);
  });

  it('holds a details panel’s Archive the same way as the toolbar’s', async () => {
    const {user} = render();
    await selectAnd(user, 'folder docs', 'Delete selected items');
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    await screen.findByRole('region', {name: 'File operations in progress'});

    await user.click(await screen.findByRole('button', {name: 'Details for notes.txt'}));

    const panel = await screen.findByRole('dialog', {name: 'Details for notes.txt'});
    const archive = within(panel).getByRole('button', {name: 'Archive this item'});
    expect(archive).toHaveAttribute('aria-disabled', 'true');
    expect(archive.getAttribute('title')).toMatch(/still running here/);
  });

  it('passes axe with an operation in flight', async () => {
    const {user} = render();
    await selectAnd(user, 'folder docs', 'Delete selected items');
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    const region = await screen.findByRole('region', {name: 'File operations in progress'});
    // The DRIVEN container, so what axe sees is the state the test put it in.
    await expectContainerHasNoA11yViolations(region, COMPONENT_AXE_OPTIONS);
  });
});

// ─── FR-004: listing catch-up ───────────────────────────────────────────────

describe('listing catch-up', () => {
  it('offers a visible refresh that re-reads the listing', async () => {
    const {user} = render();
    await screen.findByRole('list', {name: 'File list'});
    const before = mock.listFiles.mock.calls.length;
    await user.click(screen.getByRole('button', {name: 'Refresh this folder'}));
    await waitFor(() => expect(mock.listFiles.mock.calls.length).toBeGreaterThan(before));
  });

  it('tells the user a folder is gone, and takes its actions away', async () => {
    // The gap this closes: a folder details panel renders straight from the listing, so a folder
    // the plane removed showed live actions and no error at all.
    mock.folderExists.mockResolvedValue(ok(false));
    const {user} = render();
    await user.click(await screen.findByRole('button', {name: 'Details for docs'}));
    expect(await screen.findByText(/This folder no longer exists/)).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Rename docs'})).toBeNull();
  });

  it('a deleted FILE still surfaces the mapped message from its metadata read', async () => {
    mock.getObjectMetadata.mockResolvedValue({success: false, error: {message: 'gone', code: 'NotFound'}});
    const {user} = render();
    await user.click(await screen.findByRole('button', {name: 'Details for report.csv'}));
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });
});

// ─── FR-005: the conflict round trip ────────────────────────────────────────

describe('the conflict round trip', () => {
  const CONFLICTED = {
    id: 'n9',
    message: 'Moved 1 of 2 items to “out”.',
    read: false,
    timestamp: '2026-08-23T00:00:00Z',
    link: '/files?prefix=alice/out/',
    payload: {
      requestId: 'run-1',
      operation: 'move',
      // A SHARED source, while the browser below is mounted on the personal space — which is what
      // the deep link's `/files` fallback actually produces.
      source: {kind: 'shared', name: 'finance'},
      destination: {kind: 'personal', name: 'alice', prefix: 'alice/out/'},
      conflicts: [
        {itemKey: 'finance/q1.csv', kind: 'file', sample: ['q1.csv'], more: true},
        {itemKey: 'finance/q2.csv', kind: 'file'}
      ]
    }
  };

  beforeEach(() => {
    vi.mocked(getNotifications).mockResolvedValue(ok([CONFLICTED]));
  });

  it('opens from a request id alone, in a tab that never submitted', async () => {
    render({requestId: 'run-1'});
    const dialog = await screen.findByRole('alertdialog', {name: 'Review conflicts'});
    expect(dialog).toHaveTextContent('q1.csv');
    expect(dialog).toHaveTextContent('q2.csv');
    // Two items, spoken of as two, and the rest of the run pointed at rather than vouched for.
    expect(dialog).toHaveTextContent(
      'Something was in the way of these items, so Data Quarry left them alone. Your notification says what happened to the rest of that request.'
    );
    // The sample is bounded at the producer, so a shortened one must never read as complete.
    expect(within(dialog).getByText(/and more/)).toBeInTheDocument();
  });

  it('re-submits ONLY the conflicted items, overwrite, fresh id, spaces from the PAYLOAD', async () => {
    const {user} = render({requestId: 'run-1'});
    const dialog = await screen.findByRole('alertdialog', {name: 'Review conflicts'});
    await user.click(within(dialog).getByRole('button', {name: 'Overwrite…'}));
    const confirm = await screen.findByRole('alertdialog', {name: 'Confirm overwrite'});
    // The wording reaches the user, not merely a reason code.
    expect(within(confirm).getByText(/cannot be recovered/)).toBeInTheDocument();
    // What is protected is what arrives AFTER this click: the re-send carries a fresh timestamp.
    expect(confirm).toHaveTextContent(
      'Anything that arrives at the destination after you press Overwrite is left alone'
    );
    await user.click(within(confirm).getByRole('button', {name: 'Overwrite'}));

    await waitFor(() => expect(mockSubmit).toHaveBeenCalled());
    expect(mockSubmit).toHaveBeenCalledTimes(1);
    const request = mockSubmit.mock.calls[0][0];
    expect(request.requestId).not.toBe('run-1');
    expect(request.source.space).toEqual({kind: 'shared', name: 'finance'});
    expect(request.source.items.map((item) => item.key)).toEqual(['finance/q1.csv', 'finance/q2.csv']);
    expect(request.operation !== 'delete' && request.onConflict).toBe('overwrite');
    expect(
      request.operation !== 'delete' && Date.parse(request.destination ? request.submittedAt : '')
    ).toBeGreaterThan(Date.parse('2026-08-23T00:00:00Z'));
  });

  it('a rename’s "or type a new name" re-submits as a REFUSE', async () => {
    vi.mocked(getNotifications).mockResolvedValue(
      ok([
        {
          ...CONFLICTED,
          payload: {
            ...CONFLICTED.payload,
            // A rename lands in the folder and space its item already sits in.
            destination: {kind: 'shared', name: 'finance', prefix: 'finance/'},
            conflicts: [{itemKey: 'finance/q1.csv', kind: 'file', targetName: 'q1.csv'}]
          }
        }
      ])
    );
    const {user} = render({requestId: 'run-1'});
    const dialog = await screen.findByRole('alertdialog', {name: 'Review conflicts'});
    expect(dialog).toHaveTextContent('Something was in the way of this item, so Data Quarry left it alone.');
    await user.click(within(dialog).getByRole('button', {name: 'Use a different name…'}));
    const form = await screen.findByRole('dialog', {name: 'Rename to avoid the conflict'});
    const input = within(form).getByRole('textbox');
    await user.clear(input);
    await user.type(input, 'q1-v2.csv');
    await user.click(within(form).getByRole('button', {name: 'Request again'}));

    await waitFor(() => expect(mockSubmit).toHaveBeenCalled());
    expect(mockSubmit).toHaveBeenCalledTimes(1);
    const request = mockSubmit.mock.calls[0][0];
    expect(request.operation !== 'delete' && request.onConflict).toBe('refuse');
    expect(request.source.items).toEqual([{kind: 'file', key: 'finance/q1.csv', targetName: 'q1-v2.csv'}]);
    // A rename travels as a `move`, and the in-progress row says what the user pressed, naming the
    // item as the first submit did.
    const region = await screen.findByRole('region', {name: 'File operations in progress'});
    expect(within(region).getByText('Renaming q1.csv')).toBeInTheDocument();
  });

  // A renamed FOLDER lands in the payload's destination, so its new name is checked there first. The
  // source sits below the top of its space, so only the destination can refuse the name. A FILE's
  // new name takes the name rules alone, `system_settings` included, and its refusal names a file.
  it.each([
    {
      conflict: {itemKey: 'finance/reports/q1/', kind: 'folder', targetName: 'q1'},
      prefix: 'alice/',
      value: 'shared_tables',
      refusal: '“shared_tables” is a folder the app manages at the top of a space. Pick another name.'
    },
    {
      conflict: {itemKey: 'finance/reports/q1/', kind: 'folder', targetName: 'q1'},
      prefix: 'alice/projects/',
      value: 'user_settings',
      refusal: '“user_settings” is a name the app keeps for its own folders. Pick another name.'
    },
    {
      conflict: {itemKey: 'finance/reports/q1', kind: 'file', targetName: 'q1'},
      prefix: 'alice/',
      value: 'shared_tables',
      refusal: null
    },
    {
      conflict: {itemKey: 'finance/reports/q1', kind: 'file', targetName: 'q1'},
      prefix: 'alice/',
      value: 'system_settings',
      refusal: '“system_settings” is a folder the app manages. Pick another name.'
    },
    {
      conflict: {itemKey: 'finance/reports/q1', kind: 'file', targetName: 'q1'},
      prefix: 'alice/',
      value: 'a/b',
      refusal: 'File name cannot contain “/”.'
    }
  ])(
    'checks a $conflict.kind’s new name “$value” where the destination $prefix would put it',
    async ({conflict, prefix, value, refusal}) => {
      vi.mocked(getNotifications).mockResolvedValue(
        ok([
          {
            ...CONFLICTED,
            payload: {
              ...CONFLICTED.payload,
              destination: {kind: 'personal', name: 'alice', prefix},
              conflicts: [conflict]
            }
          }
        ])
      );
      const {user} = render({requestId: 'run-1'});
      const dialog = await screen.findByRole('alertdialog', {name: 'Review conflicts'});
      await user.click(within(dialog).getByRole('button', {name: 'Use a different name…'}));
      const form = await screen.findByRole('dialog', {name: 'Rename to avoid the conflict'});
      const input = within(form).getByRole('textbox');
      await user.clear(input);
      await user.type(input, value);

      expect(input).toHaveAccessibleDescription(refusal ?? '');
      expect(input.hasAttribute('aria-invalid')).toBe(refusal !== null);
      expect(within(form).getByRole('button', {name: 'Request again'})).toHaveProperty('disabled', refusal !== null);
    }
  );

  it('passes axe on the rename form, and on the review that offers it inline', async () => {
    vi.mocked(getNotifications).mockResolvedValue(
      ok([
        {
          ...CONFLICTED,
          payload: {
            ...CONFLICTED.payload,
            conflicts: [{itemKey: 'finance/q1.csv', kind: 'file', targetName: 'q1.csv'}]
          }
        }
      ])
    );
    const {user} = render({requestId: 'run-1'});
    const dialog = await screen.findByRole('alertdialog', {name: 'Review conflicts'});
    // This variant DOES carry the inline overwrite control beside the rename affordance.
    expect(within(dialog).getByRole('button', {name: 'overwrite what is there'})).toBeInTheDocument();
    await expectContainerHasNoA11yViolations(dialog, COMPONENT_AXE_OPTIONS);

    await user.click(within(dialog).getByRole('button', {name: 'Use a different name…'}));
    const form = await screen.findByRole('dialog', {name: 'Rename to avoid the conflict'});
    await expectContainerHasNoA11yViolations(form, COMPONENT_AXE_OPTIONS);
  });
});

describe('with the plane switched off, a shape it alone can perform is REFUSED AT THE CONTROL', () => {
  /**
   * The refusal a user meets with the plane off; the services' per-item one is only a backstop.
   *
   * Refusing after the fact would be worse. A folder delete that reached the confirm would ask
   * *"Delete the folder and everything inside it? This can't be undone."* and then delete nothing —
   * the app's most alarming sentence, spent on an action that cannot happen. The repo already had
   * `disabledReason` for exactly this.
   */
  it('disables Delete for a folder, with a reason that does not promise "later"', async () => {
    withFlags({asyncFileOperations: false});
    const {user} = render();

    await user.click(await screen.findByRole('checkbox', {name: 'Select folder docs'}));
    const del = screen.getByRole('button', {name: 'Delete selected items'});

    await waitFor(() => expect(del).toHaveAttribute('aria-disabled', 'true'));
    // Not "try again later": while the service is off, later is the same.
    expect(del).toHaveAccessibleDescription(/not available/i);
    expect(del).not.toHaveAccessibleDescription(/later/i);
  });

  it('disables Copy, Move and Delete for two FILES as well, because the rule is the routing one', async () => {
    // No folder anywhere: the gate refuses every shape the routing rule sends to the plane, and the
    // Files guide tells the user so. A gate narrowed to folders would pass the test above.
    withFlags({asyncFileOperations: false});
    const {user} = render();

    await user.click(await screen.findByRole('checkbox', {name: 'Select report.csv'}));
    await user.click(await screen.findByRole('checkbox', {name: 'Select notes.txt'}));

    for (const name of ['Copy selected items', 'Move selected items', 'Delete selected items']) {
      const control = screen.getByRole('button', {name});
      await waitFor(() => expect(control).toHaveAttribute('aria-disabled', 'true'));
      expect(control).toHaveAccessibleDescription(/not available/i);
    }
  });

  it('leaves a SINGLE FILE alone, which is the whole point of the gate', async () => {
    // A gate that blocked a single-file delete the plane never sees would take away something the
    // user could do before, which is the one thing this switchover may not do.
    withFlags({asyncFileOperations: false});
    const {user} = render();

    await user.click(await screen.findByRole('checkbox', {name: 'Select report.csv'}));
    const del = screen.getByRole('button', {name: 'Delete selected items'});

    expect(del).not.toHaveAttribute('aria-disabled', 'true');
    await user.click(del);
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    await waitFor(() =>
      expect(mock.deleteObject).toHaveBeenCalledWith(expect.objectContaining({key: 'alice/report.csv'}))
    );
  });
});
