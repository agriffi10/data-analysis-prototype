import {beforeEach, afterEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {HeadObjectCommand, ListObjectsV2Command, PutObjectCommand} from '@aws-sdk/client-s3';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {readExplorationTabsState} from './explorationTabs';
import {newExploration} from './exploration';
import {NOTHING_TO_SAVE} from './ExplorationResultsRegion';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {listSavedQueries, readSavedQuery} from '../saved-queries/savedQueries.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationTab, ExplorationTabsState} from './dataExplorer.types';
import type {QuerySpace} from '../catalog/catalog.types';

// SPEC-183. Only the AWS boundary is mocked (react.md §21): the real workspace, the real
// engine, the real `useSaveQuery`, the real `writeSavedQuery` and the real dialog all run —
// which is the point, because this spec's whole claim is that the Data Explorer reuses
// SPEC-175's save path rather than reimplementing it.
//
// `lib/s3Client` is the seam the STORE lands on, so the assertions below can count the
// commands the save actually issues.
const {mockSend, mockGetS3Client} = vi.hoisted(() => ({mockSend: vi.fn(), mockGetS3Client: vi.fn()}));
vi.mock('../../lib/s3Client', () => ({
  s3Client: {send: vi.fn()},
  getS3Client: mockGetS3Client
}));
vi.mock('../catalog/glue.service', () => ({
  getDatabase: vi.fn(),
  listTables: vi.fn()
}));
vi.mock('../catalog/athena.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/athena.service')>()),
  runQuery: vi.fn(),
  getQueryStatus: vi.fn(),
  getQueryResults: vi.fn()
}));
vi.mock('../shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn(),
  enqueueSharedSpaceRequest: vi.fn()
}));

const ok = <T,>(data: T) => ({success: true as const, data});

const PERSONAL: QuerySpace = {
  id: 'personal',
  label: 'My files',
  bucket: 'user-space',
  rootPrefix: 'alice/',
  rootLabel: 'My Files'
};

const TABLE = {name: 'orders', tableType: 'EXTERNAL_TABLE', location: 's3://user-space/alice/orders/', columns: []};

/** Seed the session's tabs the way a previous visit would have left them. */
function seedTab(over: Partial<ExplorationTab> = {}) {
  const exploration = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
  const state: ExplorationTabsState = {
    version: 1,
    tabs: [{id: 't1', label: 'orders', exploration, scannedByExecution: {}, history: {past: [], future: []}, ...over}],
    activeTabId: 't1'
  };
  sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
}

function render() {
  const user = userEvent.setup(USER_EVENT_OPTIONS);
  renderWithProviders(<DataExplorerWorkspace />, {route: '/explore', auth: authenticated('alice')});
  return {user};
}

const commandsOfType = (type: unknown) => mockSend.mock.calls.filter((c) => c[0] instanceof (type as never));
const putBodies = () => commandsOfType(PutObjectCommand).map((c) => (c[0] as PutObjectCommand).input);

function notFoundError() {
  return Object.assign(new Error('Not Found'), {name: 'NotFound', $metadata: {httpStatusCode: 404}});
}

/**
 * The store's answers for a space whose `saved_queries/` folder ALREADY EXISTS and holds
 * nothing under the name being saved.
 *
 * The existing marker is what makes FR-004's "exactly one PutObject" a statement about
 * sidecars rather than about folder creation: `ensureSavedQueriesFolder` writes a marker
 * when there is none, and a fixture without one would make the count two for a reason that
 * has nothing to do with what this spec forbids.
 */
function storeReady({occupied = false}: {occupied?: boolean} = {}) {
  mockSend.mockImplementation(async (command: unknown) => {
    if (command instanceof HeadObjectCommand) {
      const key = command.input.Key ?? '';
      if (key.endsWith('DO_NOT_DELETE.txt')) return {}; // the folder marker is already there
      if (occupied) return {};
      throw notFoundError();
    }
    return {};
  });
}

/** Open the save dialog on a tab whose first execution has landed. */
async function openSaveDialog(user: ReturnType<typeof render>['user']) {
  const button = await screen.findByRole('button', {name: 'Save as query'});
  await waitFor(() => expect(button).not.toHaveAttribute('aria-disabled', 'true'));
  await user.click(button);
  return screen.findByRole('dialog', {name: 'Save query'});
}

async function saveAs(user: ReturnType<typeof render>['user'], name: string) {
  const dialog = await openSaveDialog(user);
  await user.clear(within(dialog).getByLabelText('Name'));
  await user.type(within(dialog).getByLabelText('Name'), name);
  await user.click(within(dialog).getByRole('button', {name: 'Save'}));
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  mockGetS3Client.mockResolvedValue(ok({send: mockSend}));
  storeReady();
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(
    ok({version: 1, connections: [{name: 'teamspace', role: 'member', status: 'active'}]}) as never
  );
  vi.mocked(getDatabase).mockResolvedValue(ok({name: 'alice'}) as never);
  vi.mocked(listTables).mockResolvedValue(ok([TABLE]) as never);
  vi.mocked(runQuery).mockResolvedValue(ok({queryExecutionId: 'exec-1'}) as never);
  vi.mocked(getQueryStatus).mockResolvedValue(
    ok({queryExecutionId: 'exec-1', state: 'SUCCEEDED', dataScannedBytes: 2048, engineExecutionTimeMillis: 120})
  );
  vi.mocked(getQueryResults).mockResolvedValue(ok({columns: [{name: 'id', type: 'varchar'}], rows: [['1']]}) as never);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

// ─── FR-001: what gets written ──────────────────────────────────────────────

describe('what a save writes (FR-001)', () => {
  it('writes the RENDERED SQL — the exact string the execution was given', async () => {
    // AC1. The filter is applied through the real toolbar, so the body under test is the
    // one the description actually rendered to rather than one this test composed.
    seedTab({
      exploration: {
        ...newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1'),
        query: {
          filters: [{column: 'status', operator: '=', value: 'open'}],
          expression: null,
          ordering: [{column: 'id', direction: 'desc', priority: 0}],
          grouping: null
        }
      }
    });
    const {user} = render();

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    const executed = vi.mocked(runQuery).mock.calls[0][0].sql;

    await saveAs(user, 'Open orders');

    await waitFor(() => expect(putBodies()).toHaveLength(1));
    const put = putBodies()[0];
    expect(put.Body).toBe(executed);
    // Not merely equal to the execution's string — it carries the description, which is what
    // makes "saving the bare source would save something the user did not see" a real risk.
    expect(put.Body).toContain('WHERE "status" = \'open\'');
    expect(put.Body).toContain('ORDER BY "id" DESC');
  });

  it('writes exactly one object, at the store’s own key, and starts no execution (FR-004)', async () => {
    seedTab();
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    await saveAs(user, 'Monthly revenue');

    await waitFor(() => expect(putBodies()).toHaveLength(1));
    expect(putBodies()[0]).toMatchObject({
      Bucket: 'user-space',
      Key: 'alice/saved_queries/Monthly revenue.sql',
      ContentType: 'text/plain; charset=utf-8'
    });
    // AC3: no sidecar, no manifest, no metadata object — the count IS the assertion, and it
    // is taken over a space whose folder marker already exists.
    expect(commandsOfType(PutObjectCommand)).toHaveLength(1);
    // FR-001 AC6: saving is not a query. The one call is the tab's own first execution.
    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  it('lowercases a typed extension while leaving the stem alone (SPEC-175’s correction)', async () => {
    // AC4, asserted at this SECOND caller: `report.SQL` and `report.sql` rendering as one
    // name while being two objects is the bug that correction exists for.
    seedTab();
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    await saveAs(user, 'Report.SQL');

    await waitFor(() => expect(putBodies()).toHaveLength(1));
    expect(putBodies()[0].Key).toBe('alice/saved_queries/Report.sql');
  });

  it('offers the spaces the workspace is showing, and writes into the chosen one', async () => {
    seedTab();
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    const dialog = await openSaveDialog(user);
    const select = within(dialog).getByLabelText('Space');
    await waitFor(() =>
      expect(
        within(select)
          .getAllByRole('option')
          .map((o) => o.textContent)
      ).toEqual(['My files', 'teamspace'])
    );

    await user.selectOptions(select, 'teamspace');
    await user.type(within(dialog).getByLabelText('Name'), 'Shared report');
    await user.click(within(dialog).getByRole('button', {name: 'Save'}));

    await waitFor(() => expect(putBodies()).toHaveLength(1));
    expect(putBodies()[0]).toMatchObject({
      Bucket: 'shared-space',
      Key: 'teamspace/saved_queries/Shared report.sql'
    });
  });
});

// ─── FR-001 AC3: SPEC-175's rules, at a second caller ───────────────────────

describe('SPEC-175’s rules hold here too (FR-001 AC3)', () => {
  it('raises the Replace confirm for a name that already exists, and replaces on confirm', async () => {
    storeReady({occupied: true});
    seedTab();
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    await saveAs(user, 'Monthly revenue');

    const confirm = await screen.findByRole('alertdialog', {name: 'Confirm replace saved query'});
    expect(within(confirm).getByText(/already exists in My files/)).toBeInTheDocument();
    // Nothing has been written while the question is open.
    expect(commandsOfType(PutObjectCommand)).toHaveLength(0);

    await user.click(within(confirm).getByRole('button', {name: 'Replace'}));
    await waitFor(() => expect(putBodies()).toHaveLength(1));
  });

  it('keeps the dialog open with the mapped message inline when the write fails', async () => {
    seedTab();
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    mockSend.mockImplementation(async (command: unknown) => {
      if (command instanceof HeadObjectCommand) throw notFoundError();
      throw Object.assign(new Error('User is not authorized'), {name: 'AccessDenied'});
    });
    await saveAs(user, 'Monthly revenue');

    const dialog = await screen.findByRole('dialog', {name: 'Save query'});
    // SPEC-106: mapped, never the raw AWS sentence.
    expect(await within(dialog).findByText(/don't have permission/i)).toBeInTheDocument();
    expect(within(dialog).queryByText(/User is not authorized/)).not.toBeInTheDocument();
    // FR-006: the name the user chose is still there, so another destination is one control
    // away rather than a retype.
    expect(within(dialog).getByLabelText('Name')).toHaveValue('Monthly revenue');
  });

  it('refuses an invalid name on submit, with no request at all', async () => {
    seedTab();
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    const dialog = await openSaveDialog(user);
    await user.type(within(dialog).getByLabelText('Name'), 'a/b');
    await user.click(within(dialog).getByRole('button', {name: 'Save'}));

    expect(await within(dialog).findByText(/cannot contain/i)).toBeInTheDocument();
    expect(commandsOfType(PutObjectCommand)).toHaveLength(0);
  });
});

// ─── FR-003: the link the save leaves behind ────────────────────────────────

describe('the tab remembers what it was saved as (FR-003)', () => {
  it('links the tab to the file, and re-saving the same name replaces it with no second confirm', async () => {
    seedTab();
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    await saveAs(user, 'Monthly revenue');
    await waitFor(() => expect(putBodies()).toHaveLength(1));

    await waitFor(() =>
      expect(readExplorationTabsState('alice')?.tabs[0].savedQuery).toEqual({
        spaceId: 'personal',
        bucket: 'user-space',
        key: 'alice/saved_queries/Monthly revenue.sql',
        name: 'Monthly revenue'
      })
    );
    // AC4: the tab is still named for what it explores. A save does not rename it — that is
    // a behaviour of a tab whose whole identity is its buffer.
    expect(screen.getByRole('tab', {name: 'orders'})).toBeInTheDocument();

    // The second save. The name comes back pre-filled from the link, the key already exists,
    // and it writes THROUGH — the file being replaced is the one the user is looking at the
    // name of (SPEC-175 FR-004).
    storeReady({occupied: true});
    const dialog = await openSaveDialog(user);
    expect(within(dialog).getByLabelText('Name')).toHaveValue('Monthly revenue');
    expect(within(dialog).getByText(/replacing the file this tab was opened from/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', {name: 'Save'}));

    await waitFor(() => expect(putBodies()).toHaveLength(2));
    expect(screen.queryByRole('alertdialog', {name: 'Confirm replace saved query'})).not.toBeInTheDocument();
  });

  it('takes the HEAD-and-confirm path for any OTHER key, linked or not', async () => {
    storeReady({occupied: true});
    seedTab({
      savedQuery: {
        spaceId: 'personal',
        bucket: 'user-space',
        key: 'alice/saved_queries/Monthly revenue.sql',
        name: 'Monthly revenue'
      }
    });
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    await saveAs(user, 'Something else');

    expect(await screen.findByRole('alertdialog', {name: 'Confirm replace saved query'})).toBeInTheDocument();
    expect(commandsOfType(PutObjectCommand)).toHaveLength(0);
  });

  it('restores a stored link, and restores the tab WITHOUT one when it is malformed', async () => {
    // AC3. A document written before this spec carries none at all, which is the ordinary
    // case for the first session after a deploy — the tab must survive either way.
    const exploration = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
    const withLink = (savedQuery: unknown) =>
      JSON.stringify({
        version: 1,
        tabs: [
          {id: 't1', label: 'orders', exploration, scannedByExecution: {}, history: {past: [], future: []}, savedQuery}
        ],
        activeTabId: 't1'
      });

    sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`, withLink({bucket: 'user-space', key: 'k'}));
    expect(readExplorationTabsState('alice')?.tabs).toHaveLength(1);
    expect(readExplorationTabsState('alice')?.tabs[0].savedQuery).toBeUndefined();

    sessionStorage.setItem(
      `${EXPLORATION_TABS_STORAGE_PREFIX}alice`,
      withLink({spaceId: 'personal', bucket: 'user-space', key: 'alice/saved_queries/r.sql', name: 'r'})
    );
    expect(readExplorationTabsState('alice')?.tabs[0].savedQuery?.name).toBe('r');
  });
});

// ─── FR-005: one store, both surfaces ───────────────────────────────────────

describe('a file saved here is an ordinary saved query (FR-005)', () => {
  it('comes back through the Query workspace’s OWN reader, row and body', async () => {
    // Asserted at the STORE rather than by mounting the Query workspace, and that is a
    // constraint rather than a shortcut: SPEC-176's layering rule forbids one sibling
    // feature's test from importing the other, tests included. So the assertion uses the
    // functions the workspace's panel is built on — `listSavedQueries` for the row it
    // renders, `readSavedQuery` for what Open puts in the editor — over the object this
    // save actually wrote. What the panel then does with a `SavedQuery` is SPEC-174's.
    seedTab();
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    await saveAs(user, 'Monthly revenue');
    await waitFor(() => expect(putBodies()).toHaveLength(1));
    const written = putBodies()[0];

    mockSend.mockImplementation(async (command: unknown) => {
      if (command instanceof ListObjectsV2Command) {
        return {Contents: [{Key: written.Key, Size: 42, LastModified: new Date('2026-08-13')}], IsTruncated: false};
      }
      return {Body: {transformToString: async () => written.Body}};
    });

    const page = await listSavedQueries({space: PERSONAL});
    expect(page.success && page.data.queries).toEqual([
      {
        spaceId: 'personal',
        bucket: 'user-space',
        key: 'alice/saved_queries/Monthly revenue.sql',
        name: 'Monthly revenue',
        updatedAt: '2026-08-13T00:00:00.000Z',
        size: 42
      }
    ]);

    const body = await readSavedQuery({bucket: 'user-space', key: written.Key as string});
    expect(body.success && body.data).toBe(written.Body);
  });
});

// ─── FR-002: there is nothing to save until something has run ───────────────

describe('nothing to save (FR-002)', () => {
  it('refuses in the tab order, with user text, when the description cannot render', async () => {
    // A grouping that orders by a column it neither groups nor aggregates: the renderer
    // REFUSES it, so there is no statement to save. Its own message names a column for an
    // operator, which SPEC-106 forbids showing anyone — so the control says something else.
    seedTab({
      exploration: {
        ...newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1'),
        query: {
          filters: [],
          expression: null,
          ordering: [{column: 'total', direction: 'asc', priority: 0}],
          grouping: {columns: ['status'], aggregates: [], duplicatesOnly: false, showPercentage: false}
        }
      }
    });
    render();

    const button = await screen.findByRole('button', {name: 'Save as query'});
    // `aria-disabled`, not `disabled` (SPEC-172) — the reason has to be reachable.
    await waitFor(() => expect(button).toHaveAttribute('aria-disabled', 'true'));
    expect(button).not.toHaveAttribute('disabled');
    expect(button).toHaveAttribute('title', NOTHING_TO_SAVE);
    expect(runQuery).not.toHaveBeenCalled();
    expect(screen.queryByText(/neither grouped nor aggregated/)).not.toBeInTheDocument();
  });

  it('is unavailable while a description is suspended, because nothing has run', async () => {
    // AC2. SPEC-181 holds a history step onto a known-failed statement back rather than
    // re-running it — so the description on screen has produced no statement, and there is
    // nothing to write.
    let started = 0;
    vi.mocked(runQuery).mockImplementation(async () => {
      started += 1;
      return ok({queryExecutionId: `exec-${started}`}) as never;
    });
    // `getQueryStatus` takes the id as a BARE STRING, not an object — the second execution
    // is the expression's, and it is the one that fails.
    vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
      queryExecutionId === 'exec-2'
        ? ok({queryExecutionId, state: 'FAILED', stateChangeReason: 'mismatched input'})
        : ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048})) as never);

    seedTab();
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    await user.type(screen.getByLabelText('Filter expression'), 'not sql at all{Enter}');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    await screen.findByText(/syntax error in your query/i);
    await user.click(screen.getByRole('button', {name: 'Back to previous filters'}));
    await waitFor(() => expect(screen.getByLabelText('Filter expression')).toHaveValue(''));
    await user.click(screen.getByRole('button', {name: 'Forward to next filters'}));
    await screen.findByRole('button', {name: 'Run it anyway'});

    const button = screen.getByRole('button', {name: 'Save as query'});
    expect(button).toHaveAttribute('aria-disabled', 'true');
    expect(button).toHaveAttribute('title', NOTHING_TO_SAVE);
  });
});
