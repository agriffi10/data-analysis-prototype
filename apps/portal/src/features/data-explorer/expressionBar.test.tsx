import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {newExploration} from './exploration';
import {getFeatureFlags} from '../feature-flags/featureFlags.service';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {MAX_POLL_DURATION_MS, POLL_INTERVAL_MS} from '../catalog/catalog.constants';
import {withFakeTimers} from '../../test/fakeTimers';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationTabsState} from './dataExplorer.types';
import type {FeatureFlags} from '../feature-flags/featureFlags.types';

// SPEC-181 FR-003: the raw expression bar. Its three rules are that it applies on an
// explicit gesture and never on a keystroke, that its text survives a failure so it can be
// corrected, and that it is NOT gated on the `query` flag.

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
vi.mock('../feature-flags/featureFlags.service', async (importActual) => ({
  ...(await importActual<typeof import('../feature-flags/featureFlags.service')>()),
  getFeatureFlags: vi.fn()
}));

const ok = <T,>(data: T) => ({success: true as const, data});

const COLUMNS = [
  {name: 'id', type: 'varchar'},
  {name: 'status', type: 'varchar'}
];
const ROWS = [
  ['1', 'open'],
  ['2', 'closed']
];

const ALL_ON: FeatureFlags = {
  files: true,
  query: true,
  sharedWorkspaces: true,
  dataQuality: true,
  dataExplorer: true,
  asyncFileOperations: true,
  resultsConversion: true,
  archive: true
};

function lastSql(): string {
  const calls = vi.mocked(runQuery).mock.calls;
  return (calls[calls.length - 1][0] as {sql: string}).sql;
}

function render(options: {seedFeatureFlags?: boolean} = {}) {
  const user = userEvent.setup(USER_EVENT_OPTIONS);
  renderWithProviders(<DataExplorerWorkspace />, {
    route: '/explore',
    auth: authenticated('alice'),
    ...options
  });
  return {user};
}

function seedTab() {
  const exploration = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
  const state: ExplorationTabsState = {
    version: 1,
    tabs: [{id: 't1', label: 'orders', exploration, scannedByExecution: {}, history: {past: [], future: []}}],
    activeTabId: 't1'
  };
  sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(getFeatureFlags).mockResolvedValue(ok(ALL_ON) as never);
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(ok({version: 1, connections: []}) as never);
  vi.mocked(getDatabase).mockResolvedValue(ok({name: 'alice'}) as never);
  vi.mocked(listTables).mockResolvedValue(ok([{name: 'orders', tableType: 'EXTERNAL_TABLE', columns: []}]) as never);

  let seq = 0;
  vi.mocked(runQuery).mockImplementation((async () => {
    seq += 1;
    return ok({queryExecutionId: `exec-${seq}`});
  }) as never);
  vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
    ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048, engineExecutionTimeMillis: 120})) as never);
  vi.mocked(getQueryResults).mockResolvedValue(ok({columns: COLUMNS, rows: ROWS}) as never);
  seedTab();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('the expression bar', () => {
  it('applies on Enter and on Apply, and NEVER on a keystroke', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    const bar = screen.getByLabelText('Filter expression');
    await user.type(bar, "status = 'open' AND id <> '2'");
    // A whole expression typed, and not one execution: every apply is a bill, so a
    // keystroke cannot be one.
    expect(runQuery).toHaveBeenCalledTimes(1);

    await user.keyboard('{Enter}');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    // Composed VERBATIM — the user's own SQL, exactly as Monaco's buffer is. Passing it
    // through `sqlLiteral` would quote the whole fragment and match nothing.
    expect(lastSql()).toContain(`WHERE (status = 'open' AND id <> '2')`);

    await user.clear(bar);
    await user.type(bar, "id = '2'");
    expect(runQuery).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole('button', {name: 'Apply expression'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(3));
    expect(lastSql()).toContain(`WHERE (id = '2')`);
  });

  it('parenthesizes both sides, so an OR in the expression cannot capture a filter', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await user.click(await screen.findByRole('button', {name: /^Column options: status/}));
    await user.click(await screen.findByRole('menuitem', {name: 'Filter: is not null'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));

    await user.type(screen.getByLabelText('Filter expression'), "id = '1' OR id = '2'{Enter}");
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(3));
    // `a IS NOT NULL AND b OR c` is not `a IS NOT NULL AND (b OR c)`, and the difference is
    // rows the user did not ask for.
    expect(lastSql()).toContain(`WHERE "status" IS NOT NULL AND (id = '1' OR id = '2')`);
  });

  // A typed WHERE reached Athena as `WHERE (WHERE …)` and failed; testers did not know the bar
  // supplies its own. The column `where_flag` is the case a looser pattern would eat.
  it.each([
    {typed: "WHERE status = 'open'", sent: `WHERE (status = 'open')`},
    {typed: 'where_flag = 1', sent: 'WHERE (where_flag = 1)'},
    // Only a LEADING where comes off: one inside a value is the user's data.
    {typed: "note LIKE '%where%'", sent: "WHERE (note LIKE '%where%')"}
  ])('sends "$typed" with the one WHERE the renderer supplies, and leaves the text as typed', async ({typed, sent}) => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    await user.type(screen.getByLabelText('Filter expression'), `${typed}{Enter}`);

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toContain(sent);
    expect(lastSql().match(/\bWHERE\b/g)).toHaveLength(1);
    expect(screen.getByLabelText('Filter expression')).toHaveValue(typed);
    expect(screen.getByLabelText('Filter expression')).toHaveAccessibleDescription(/without where/);
  });

  it('renders an Athena syntax error through toUserMessage, keeps the text, and keeps the rows', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');

    vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
      queryExecutionId === 'exec-1'
        ? ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048})
        : ok({
            queryExecutionId,
            state: 'FAILED',
            stateChangeReason: "line 1:23: mismatched input 'FROM'. Expecting: <expression>"
          })) as never);
    // A failed execution has no results to read, which is what makes the fallback the ONLY
    // way rows can still be on screen — without it this assertion would pass over the
    // failed execution's own (mocked) rows.
    vi.mocked(getQueryResults).mockImplementation((async ({queryExecutionId}: {queryExecutionId: string}) =>
      queryExecutionId === 'exec-1'
        ? ok({columns: COLUMNS, rows: ROWS})
        : {success: false as const, error: {message: 'Query did not finish successfully'}}) as never);

    await user.type(screen.getByLabelText('Filter expression'), 'status ==== ?{Enter}');

    // The sentence stays friendly; the engine's own words exist only inside the closed Details.
    expect(await screen.findByText(/syntax error in your query/i)).toBeInTheDocument();
    const engineText = screen.getAllByText(/mismatched input/);
    expect(engineText).toHaveLength(1);
    expect(engineText[0].closest('details')).not.toHaveAttribute('open');
    // The offending text stays, so it can be corrected (AC4)…
    expect(screen.getByLabelText('Filter expression')).toHaveValue('status ==== ?');
    // …and the previous execution's rows stay on screen rather than the grid emptying (AC5).
    expect(screen.getByRole('grid')).toBeInTheDocument();
    expect(screen.getByText('open')).toBeInTheDocument();
  });

  it('keeps the previous rows under the banner when an apply outlives the ceiling', async () => {
    await withFakeTimers(async () => {
      const {user} = render();
      await screen.findAllByRole('gridcell');
      vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) =>
        queryExecutionId === 'exec-1'
          ? ok({queryExecutionId, state: 'SUCCEEDED', dataScannedBytes: 2048})
          : ok({queryExecutionId, state: 'RUNNING'})) as never);

      await user.type(screen.getByLabelText('Filter expression'), "status = 'open'{Enter}");
      await waitFor(() => expect(getQueryStatus).toHaveBeenCalledWith('exec-2'));
      // The ceiling's mark in an act of its own, then the one poll whose read decides.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(MAX_POLL_DURATION_MS);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 10);
      });

      expect(await screen.findByText(/Data Quarry stopped waiting for this query/)).toBeInTheDocument();
      expect(screen.getByRole('grid')).toBeInTheDocument();
      expect(screen.getByText('open')).toBeInTheDocument();
    });
  });

  it('is present with the query flag OFF', async () => {
    // A flag is presentation, never authorization (SPEC-162): gating this input would
    // revoke no grant and would leave the feature unable to express what people filter on.
    vi.mocked(getFeatureFlags).mockResolvedValue(ok({...ALL_ON, query: false}) as never);
    const {user} = render({seedFeatureFlags: false});
    await screen.findAllByRole('gridcell');

    const bar = await screen.findByLabelText('Filter expression');
    await user.type(bar, "status = 'open'{Enter}");
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(lastSql()).toContain(`WHERE (status = 'open')`);
  });
});
