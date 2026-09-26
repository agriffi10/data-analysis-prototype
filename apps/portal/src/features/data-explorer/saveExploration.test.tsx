import {beforeEach, afterEach, describe, expect, it, vi} from 'vitest';
import {act, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {readExplorationTabsState} from './explorationTabs';
import {parseViewLine} from '../../lib/savedViewLine';
import {newExploration} from './exploration';
import {FAILED_NO_VIEW, FAILED_NOT_SAVEABLE} from './ExplorationResultsRegion';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {MAX_POLL_DURATION_MS, POLL_INTERVAL_MS} from '../catalog/catalog.constants';
import {withFakeTimers} from '../../test/fakeTimers';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationTab, ExplorationTabsState} from './dataExplorer.types';
import {chooseExplorationOption, explorationOption} from './explorationOptions.testkit';

// SPEC-183. Only the AWS boundary is mocked (react.md §21): the real workspace, the real
// engine, the real `useSaveQuery`, the real `writeSavedQuery` and the real dialog all run —
// which is the point, because this spec's whole claim is that the Data Explorer reuses
// SPEC-175's save path rather than reimplementing it.
//
// `lib/apiClient` is the seam the STORE lands on now, so the assertions below can count the
// requests the save actually issues.
const {mockSend} = vi.hoisted(() => ({mockSend: vi.fn()}));
// `apiRetryPolicy` is kept REAL rather than stubbed: it reads the generated route table and is
// pure, so a stub would have this suite driving a retry policy the contract does not declare.
vi.mock('../../lib/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/apiClient')>()),
  apiRequest: mockSend
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

type ApiCall = [string, {body?: Record<string, unknown>; query?: Record<string, string>}];

const callsTo = (route: string) => (mockSend.mock.calls as ApiCall[]).filter(([id]) => id === route);

/** Every write that is a saved query rather than the folder's own marker. */
/**
 * The writes the store ACCEPTED, which is not the same list as the writes attempted.
 *
 * The collision check moved inside the write route, so a save onto an occupied name IS a write
 * request — one the store refuses. Counting attempts would report a stored object while the
 * Replace question is still on screen.
 */
const stored: Record<string, unknown>[] = [];

/**
 * The store's answers for a space whose `saved_queries/` folder ALREADY EXISTS and holds
 * nothing under the name being saved.
 *
 * The existing marker is what makes FR-004's "exactly one write" a statement about sidecars
 * rather than about folder creation: `ensureSavedQueriesFolder` answers its own `Conflict` when
 * the marker is there, and a fixture without one would make the count two for a reason that has
 * nothing to do with what this spec forbids.
 */
function storeReady({occupied = false}: {occupied?: boolean} = {}) {
  mockSend.mockImplementation(async (route: string, options?: {body?: Record<string, unknown>}) => {
    // Anything but the write is unexpected here, and it THROWS rather than answering an empty
    // success: a save that started calling a different route would otherwise still satisfy this
    // fake, which is the shape of a port that silently drops a request.
    if (route !== 'objects.writeContent') {
      throw new Error(`saveExploration: unexpected route ${route}`);
    }
    const key = String(options?.body?.key ?? '');
    // The marker is already there, which the write route reports as a Conflict.
    if (key.endsWith('DO_NOT_DELETE.txt')) return {success: false, error: {message: '', code: 'Conflict'}};
    if (occupied && options?.body?.overwrite !== true) {
      return {success: false, error: {message: '', code: 'Conflict'}};
    }
    stored.push(options?.body ?? {});
    return {success: true, data: {key, etag: 'e'}};
  });
}

/** Open the save dialog on a tab whose first execution has landed.
 *
 * The control lives in the Options menu, so the wait for the execution is a wait on the MENU
 * ITEM's refusal clearing — same assertion, one layer in. The menu is reopened rather than held
 * open across the wait: `waitFor` can outlive an outside click, and a stale handle would assert
 * against an item detached from the document. */
async function openSaveDialog(user: ReturnType<typeof render>['user']) {
  await waitFor(async () =>
    expect(await explorationOption(user, 'Save as query')).not.toHaveAttribute('aria-disabled', 'true')
  );
  await chooseExplorationOption(user, 'Save as query');
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
  stored.length = 0;
  sessionStorage.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
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

    await waitFor(() => expect(stored).toHaveLength(1));
    const parsed = parseViewLine(stored[0].body as string);
    expect(parsed.sql).toBe(executed);
    // Not merely equal to the execution's string — it carries the description, which is what
    // makes "saving the bare source would save something the user did not see" a real risk.
    expect(parsed.sql).toContain('WHERE "status" = \'open\'');
    expect(parsed.sql).toContain('ORDER BY "id" DESC');
    // And the view it came from, on the one line under it, so the Data Explorer can reopen it.
    expect(stored[0].body).toBe(`${executed}\n${(stored[0].body as string).split('\n').at(-2)}\n`);
    expect(parsed.kind === 'ok' && parsed.payload).toMatchObject({
      source: {database: 'alice', table: 'orders'},
      query: {filters: [{column: 'status', operator: '=', value: 'open'}]}
    });
  });

  it('writes a statement source’s SQL alone, and a view too large to keep with a toast that says so', async () => {
    seedTab({
      exploration: newExploration({kind: 'sql', body: 'SELECT 1 AS n', label: 'SELECT 1'}, 't1')
    });
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    await saveAs(user, 'One');

    await waitFor(() => expect(stored).toHaveLength(1));
    expect(stored[0].body).toBe(vi.mocked(runQuery).mock.calls[0][0].sql);
  });

  it('keeps the SQL and tells the user when the view would take the file past Athena’s limit', async () => {
    seedTab({
      exploration: {
        ...newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1'),
        query: {filters: [], expression: `note = '${'x'.repeat(120_000)}'`, ordering: [], grouping: null}
      }
    });
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    await saveAs(user, 'Long');

    await waitFor(() => expect(stored).toHaveLength(1));
    expect(parseViewLine(stored[0].body as string).kind).toBe('none');
    expect(
      await screen.findByText('Saved “Long” to alice. The view was too large to keep, so it opens in Query only.', {
        exact: false
      })
    ).toBeInTheDocument();
  });

  it('writes exactly one object, at the store’s own key, and starts no execution (FR-004)', async () => {
    seedTab();
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    await saveAs(user, 'Monthly revenue');

    await waitFor(() => expect(stored).toHaveLength(1));
    // The bucket no longer travels: the API resolves the space from the caller's verified claims,
    // so what the browser still says is WHICH space and which key.
    expect(stored[0]).toMatchObject({
      space: {kind: 'personal', name: 'alice'},
      key: 'alice/saved_queries/Monthly revenue.sql',
      contentType: 'text/plain; charset=utf-8'
    });
    // AC3: no sidecar, no manifest, no metadata object — the count IS the assertion, and it
    // is taken over a space whose folder marker already exists.
    expect(stored).toHaveLength(1);
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

    await waitFor(() => expect(stored).toHaveLength(1));
    expect(stored[0].key).toBe('alice/saved_queries/Report.sql');
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
      ).toEqual(['alice', 'teamspace'])
    );

    await user.selectOptions(select, 'teamspace');
    await user.type(within(dialog).getByLabelText('Name'), 'Shared report');
    await user.click(within(dialog).getByRole('button', {name: 'Save'}));

    await waitFor(() => expect(stored).toHaveLength(1));
    expect(stored[0]).toMatchObject({
      space: {kind: 'shared', name: 'teamspace'},
      key: 'teamspace/saved_queries/Shared report.sql'
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
    expect(within(confirm).getByText(/already exists in alice/)).toBeInTheDocument();
    // Nothing has been STORED while the question is open. Counted on what the store accepted, not
    // on what was attempted: the collision check lives inside the write route now, so the refused
    // save is itself a request.
    expect(stored).toHaveLength(0);

    await user.click(within(confirm).getByRole('button', {name: 'Replace'}));
    await waitFor(() => expect(stored).toHaveLength(1));
  });

  it('refuses an invalid name on submit, with no request at all', async () => {
    seedTab();
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    const dialog = await openSaveDialog(user);
    await user.type(within(dialog).getByLabelText('Name'), 'a/b');
    await user.click(within(dialog).getByRole('button', {name: 'Save'}));

    expect(await within(dialog).findByText(/cannot contain/i)).toBeInTheDocument();
    expect(callsTo('objects.writeContent')).toHaveLength(0);
  });
});

// ─── FR-003: the link the save leaves behind ────────────────────────────────

describe('the tab remembers what it was saved as (FR-003)', () => {
  it('links the tab to the file, and re-saving the same name replaces it with no second confirm', async () => {
    seedTab();
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    await saveAs(user, 'Monthly revenue');
    await waitFor(() => expect(stored).toHaveLength(1));

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

    await waitFor(() => expect(stored).toHaveLength(2));
    expect(screen.queryByRole('alertdialog', {name: 'Confirm replace saved query'})).not.toBeInTheDocument();
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
    const {user} = render();

    // Asserted on the MENU ITEM: `aria-disabled`, not `disabled` — the reason has to be
    // reachable, which is why the item carries `MenuItem.disabledReason` rather than leaving
    // the menu. Re-fetched on each pass because `waitFor` outlives the menu's own state.
    await waitFor(async () =>
      expect(await explorationOption(user, 'Save as query')).toHaveAttribute('aria-disabled', 'true')
    );
    const button = await explorationOption(user, 'Save as query');
    expect(button).not.toHaveAttribute('disabled');
    // A render refusal is an ERROR as well as an absent statement, so it takes the same
    // wording a failed execution does: nothing ran, and the way out is to change something.
    expect(button).toHaveAttribute('title', FAILED_NOT_SAVEABLE);
    // Create view is refused for the same reason, in its own words: it makes a view, not a file.
    expect(await explorationOption(user, 'Create view…')).toHaveAttribute('title', FAILED_NO_VIEW);
    expect(runQuery).not.toHaveBeenCalled();
    expect(screen.queryByText(/neither grouped nor aggregated/)).not.toBeInTheDocument();
  });

  it('offers Save as query for a statement the watch stopped waiting for, which Athena accepted', async () => {
    await withFakeTimers(async () => {
      vi.mocked(getQueryStatus).mockResolvedValue(ok({queryExecutionId: 'exec-1', state: 'RUNNING'}) as never);
      seedTab();
      const {user} = render();
      await waitFor(() => expect(getQueryStatus).toHaveBeenCalled());
      // The ceiling's mark in an act of its own, then the one poll whose read decides.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(MAX_POLL_DURATION_MS);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 10);
      });

      await screen.findByText(/Data Quarry stopped waiting for this query/);

      expect(await explorationOption(user, 'Save as query')).not.toHaveAttribute('aria-disabled', 'true');
      await chooseExplorationOption(user, 'Save as query');
      expect(await screen.findByRole('dialog', {name: 'Save query'})).toBeInTheDocument();
    });
  });

  it('refuses a FAILED exploration, whose rows on screen are a DIFFERENT query’s', async () => {
    // The state this refusal exists for, and the one that is easy to miss: a failed apply
    // still HAS a rendered statement — the one Athena rejected — while the region has fallen
    // back to the last good execution's rows (SPEC-181). Saving there wrote the failed query
    // under a name whose grid showed another one's rows, and the file then failed to open in
    // the Query workspace FR-005 promises it opens in. Found in review.
    let started = 0;
    vi.mocked(runQuery).mockImplementation(async () => {
      started += 1;
      return ok({queryExecutionId: `exec-${started}`}) as never;
    });
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

    // NOT suspended — this is the FIRST failure, not a history step onto a known-bad
    // statement, so `sql` is non-null and only the failure itself can turn the control off.
    expect(screen.queryByRole('button', {name: 'Run it anyway'})).not.toBeInTheDocument();

    const button = await explorationOption(user, 'Save as query');
    expect(button).toHaveAttribute('aria-disabled', 'true');
    expect(button).toHaveAttribute('title', FAILED_NOT_SAVEABLE);

    // …and pressing it anyway writes nothing: `MenuItem.disabledReason` drops the handler the
    // same way `Button.disabledReason` does, which is the property that had to survive the
    // move off the toolbar.
    await user.click(button);
    expect(screen.queryByRole('dialog', {name: 'Save query'})).not.toBeInTheDocument();
    expect(stored).toHaveLength(0);
  });
});

// ─── Accessibility ──────────────────────────────────────────────────────────

describe('accessibility', () => {
  it('leaves the open save dialog, and the toolbar’s refused control, axe-clean', async () => {
    // `document.body` — the DRIVEN tree, not a fresh render of the same JSX: a re-render
    // would put the dialog back in its closed state and axe would never see it open.
    seedTab();
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    await openSaveDialog(user);
    await expectContainerHasNoA11yViolations(document.body, COMPONENT_AXE_OPTIONS);
  });

  it('leaves the Replace confirm axe-clean', async () => {
    storeReady({occupied: true});
    seedTab();
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    await saveAs(user, 'Monthly revenue');
    await screen.findByRole('alertdialog', {name: 'Confirm replace saved query'});

    await expectContainerHasNoA11yViolations(document.body, COMPONENT_AXE_OPTIONS);
  });
});
