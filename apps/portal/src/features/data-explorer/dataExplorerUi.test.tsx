import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import userEvent from '@testing-library/user-event';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {resolveExploreParams, spaceDatabase} from './exploreSources';
import {EXPLORATION_TABS_MAX, EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {newExploration} from './exploration';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationTab, ExplorationTabsState} from './dataExplorer.types';
import type {QuerySpace} from '../catalog/catalog.types';

// Only the AWS boundary is mocked (react.md §21): the real workspace, the real picker, the
// real tab state and SPEC-178's real engine all run. `isTerminalState` stays real — it
// decides when polling stops, which is the pending/settled boundary these tests assert.
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
const VIEW = {name: 'revenue_view', tableType: 'VIRTUAL_VIEW', columns: []};

const PERSONAL_SPACE: QuerySpace = {
  id: 'personal',
  label: 'My files',
  bucket: 'user-space',
  rootPrefix: 'alice/',
  rootLabel: 'My Files'
};
const SHARED_SPACE: QuerySpace = {
  id: 'teamspace',
  label: 'teamspace',
  bucket: 'shared-space',
  rootPrefix: 'teamspace/',
  rootLabel: 'teamspace'
};

function render(route = '/explore') {
  const user = userEvent.setup(USER_EVENT_OPTIONS);
  const {unmount} = renderWithProviders(<DataExplorerWorkspace />, {route, auth: authenticated('alice')});
  return {user, unmount};
}

/** Seed the session's tabs the way a previous visit would have left them. */
function seedTabs(tabs: {id: string; table: string}[], activeTabId = tabs[0]?.id ?? '') {
  const state: ExplorationTabsState = {
    version: 1,
    tabs: tabs.map(
      ({id, table}): ExplorationTab => ({
        id,
        label: table,
        exploration: newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table}, id),
        scannedByExecution: {}
      })
    ),
    activeTabId
  };
  sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(
    ok({version: 1, connections: [{name: 'teamspace', role: 'member', status: 'active'}]}) as never
  );
  vi.mocked(getDatabase).mockResolvedValue(ok({name: 'alice'}) as never);
  vi.mocked(listTables).mockResolvedValue(ok([TABLE, VIEW]) as never);
  let started = 0;
  vi.mocked(runQuery).mockImplementation(async () => {
    started += 1;
    return ok({queryExecutionId: `exec-${started}`});
  });
  vi.mocked(getQueryStatus).mockResolvedValue(
    ok({queryExecutionId: 'exec-1', state: 'SUCCEEDED', dataScannedBytes: 2048, engineExecutionTimeMillis: 120})
  );
  vi.mocked(getQueryResults).mockResolvedValue(
    ok({
      columns: [
        {name: 'id', type: 'varchar'},
        {name: 'total', type: 'double'}
      ],
      rows: [
        ['1', '9.99'],
        ['2', '12.50']
      ]
    }) as never
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

// ─── FR-005: the source picker ──────────────────────────────────────────────

describe('the source picker', () => {
  it('offers every space personal-first, and the chosen space’s tables AND views', async () => {
    render();

    await waitFor(() =>
      expect(screen.getAllByRole('button', {name: /^(My files|teamspace)/}).map((b) => b.textContent)).toEqual([
        'My filesalice',
        'teamspaceteamspace'
      ])
    );

    expect(await screen.findByRole('button', {name: 'orders'})).toBeInTheDocument();
    // A view is a perfectly good thing to explore — the renderer does not care which it is.
    expect(screen.getByRole('button', {name: /revenue_view/})).toBeInTheDocument();
  });

  it('reads the SELECTED space’s database, not the first one', async () => {
    const {user} = render();
    await user.click(await screen.findByRole('button', {name: /^teamspace/}));

    await waitFor(() => expect(getDatabase).toHaveBeenCalledWith('teamspace'));
  });

  it('opens a tab bound to the chosen table and runs its first execution', async () => {
    const {user} = render();
    await user.click(await screen.findByRole('button', {name: 'orders'}));

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    expect(vi.mocked(runQuery).mock.calls[0][0]).toMatchObject({
      sql: 'SELECT *\nFROM "alice"."orders"',
      username: 'alice'
    });
    expect(await screen.findByRole('tab', {name: 'orders'})).toBeInTheDocument();
  });

  it('explains an unreadable database rather than listing tables that fail', async () => {
    // FR-005 AC3, as this build honours it: the space list comes from MEMBERSHIPS, so a
    // database that cannot be read is explained where its tables would have been. Nothing
    // offers a table that cannot be opened.
    vi.mocked(getDatabase).mockResolvedValue({success: false, error: {message: 'EntityNotFoundException'}} as never);
    render();

    expect(await screen.findByText(/tables aren’t available right now/)).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'orders'})).not.toBeInTheDocument();
    // …and the space itself is still selectable, so another one is one click away.
    expect(screen.getByRole('button', {name: /^My files/})).toBeInTheDocument();
  });

  it('explains itself rather than rendering empty when there is no usable space', async () => {
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', '');
    render();

    expect(await screen.findByRole('heading', {name: 'Nothing to explore yet'})).toBeInTheDocument();
    expect(getDatabase).not.toHaveBeenCalled();
  });
});

// ─── FR-006: deep links ─────────────────────────────────────────────────────

describe('the deep link', () => {
  it('opens a tab on the named table when all three parameters resolve', async () => {
    render('/explore?space=personal&db=alice&table=orders');

    expect(await screen.findByRole('tab', {name: 'orders'})).toBeInTheDocument();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    expect(vi.mocked(runQuery).mock.calls[0][0]).toMatchObject({sql: 'SELECT *\nFROM "alice"."orders"'});
  });

  it('opens a tab in a SHARED space the user is an active member of', async () => {
    render('/explore?space=teamspace&db=teamspace&table=orders');

    expect(await screen.findByRole('tab', {name: 'orders'})).toBeInTheDocument();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    expect(vi.mocked(runQuery).mock.calls[0][0]).toMatchObject({sql: 'SELECT *\nFROM "teamspace"."orders"'});
  });

  it('renders the denied state for an unreachable space and asks NOTHING of Glue or Athena', async () => {
    render('/explore?space=someone_elses&db=someone_elses&table=orders');

    expect(await screen.findByRole('heading', {name: 'You don’t have access to that space'})).toBeInTheDocument();
    // The disclosure this guards: a Glue call would answer whether a database the user
    // cannot see exists, and an Athena call would read it (SPEC-113's rule).
    expect(getDatabase).not.toHaveBeenCalled();
    expect(listTables).not.toHaveBeenCalled();
    expect(runQuery).not.toHaveBeenCalled();
    // …and no picker either, so nothing else can start a request behind the refusal.
    expect(screen.queryByRole('button', {name: 'orders'})).not.toBeInTheDocument();
  });

  it('starts NO execution for a denied link, even with a tab restored from the session', async () => {
    // The bug this pins: `denied` is false during the resolution window, so a guard written
    // as `denied ? null : …` let the restored tab mint a real StartQueryExecution for a page
    // that then rendered nothing but the refusal. FR-006 AC2's letter survived that — the
    // execution is against the user's OWN table — but cost is this feature's through-line,
    // and a billed query behind a refusal is the wrong kind of correct.
    seedTabs([{id: 't1', table: 'orders'}]);
    render('/explore?space=someone_elses&db=someone_elses&table=orders');

    expect(await screen.findByRole('heading', {name: 'You don’t have access to that space'})).toBeInTheDocument();
    expect(runQuery).not.toHaveBeenCalled();
    expect(getDatabase).not.toHaveBeenCalled();
  });

  it('falls through to the picker on a malformed link, never an error', async () => {
    render('/explore?table=orders');

    expect(await screen.findByRole('button', {name: 'orders'})).toBeInTheDocument();
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
    expect(runQuery).not.toHaveBeenCalled();
  });

  it('drops the parameters once acted on, so a re-render does not stack duplicates', async () => {
    render('/explore?space=personal&db=alice&table=orders');

    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getAllByRole('tab')).toHaveLength(1));
  });
});

describe('resolveExploreParams — the precedence rules, asserted directly', () => {
  const spaces = [PERSONAL_SPACE, {...SHARED_SPACE, id: 'alice', label: 'alice'}];

  it('resolves the actor’s own username as PERSONAL even when a shared space shares the name', () => {
    // Mirrors SPEC-113: the other reading sends a user to the shared bucket's catalog under
    // their own name — a stranger's database, or a 403 on what is theirs.
    const result = resolveExploreParams({space: 'alice', db: 'alice', table: 'orders'}, spaces, 'alice', true);

    expect(result).toEqual({status: 'ready', target: {spaceId: 'personal', database: 'alice', table: 'orders'}});
  });

  it('does not read ?space= at all when sharedWorkspaces is off', () => {
    // Never resolved-then-fallen-back: a "we sent you somewhere else" banner over a
    // parameter that was never consulted would be a lie. The personal space's database is
    // `alice`, so a link to `teamspace` simply names nothing and the picker opens.
    const withShared = [PERSONAL_SPACE, SHARED_SPACE];
    expect(
      resolveExploreParams({space: 'teamspace', db: 'teamspace', table: 'orders'}, withShared, 'alice', false)
    ).toEqual({status: 'none'});
  });

  it('refuses an unreachable NAMED space and shrugs at an absent one', () => {
    expect(resolveExploreParams({space: 'nope', db: 'nope', table: 'orders'}, spaces, 'alice', true)).toEqual({
      status: 'denied'
    });
    expect(resolveExploreParams({space: null, db: 'alice', table: 'orders'}, spaces, 'alice', true)).toMatchObject({
      status: 'ready'
    });
  });

  it('treats a database that is not the space’s own as a malformed link', () => {
    expect(resolveExploreParams({space: 'personal', db: 'teamspace', table: 'orders'}, spaces, 'alice', true)).toEqual({
      status: 'none'
    });
  });

  it('maps a space to exactly one database', () => {
    expect(spaceDatabase(PERSONAL_SPACE, 'alice')).toBe('alice');
    expect(spaceDatabase(SHARED_SPACE, 'alice')).toBe('teamspace');
  });
});

// ─── FR-008: the tab strip ──────────────────────────────────────────────────

describe('the exploration tabs', () => {
  it('renders tabs in creation order, and switching restores that tab’s exploration', async () => {
    seedTabs([
      {id: 't1', table: 'orders'},
      {id: 't2', table: 'refunds'}
    ]);
    const {user} = render();

    expect((await screen.findAllByRole('tab')).map((t) => t.textContent)).toEqual(['orders', 'refunds']);
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    expect(vi.mocked(runQuery).mock.calls[0][0]).toMatchObject({sql: 'SELECT *\nFROM "alice"."orders"'});

    await user.click(screen.getByRole('tab', {name: 'refunds'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(vi.mocked(runQuery).mock.calls[1][0]).toMatchObject({sql: 'SELECT *\nFROM "alice"."refunds"'});
  });

  it('raises the cap dialog at the limit, leaving the + enabled', async () => {
    seedTabs(Array.from({length: EXPLORATION_TABS_MAX}, (_, i) => ({id: `t${i}`, table: `table_${i}`})));
    const {user} = render();

    const plus = await screen.findByRole('button', {name: 'New exploration'});
    expect(plus).toBeEnabled();
    await user.click(plus);

    const dialog = await screen.findByRole('alertdialog', {name: 'Exploration limit reached'});
    expect(within(dialog).getByText(/Close one before opening another/)).toBeInTheDocument();
    // Nothing was opened, and no picker took the place of the results.
    expect(screen.getAllByRole('tab')).toHaveLength(EXPLORATION_TABS_MAX);
  });

  it('runs no query when a tab is closed', async () => {
    seedTabs([
      {id: 't1', table: 'orders'},
      {id: 't2', table: 'refunds'}
    ]);
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    // The ACTIVE tab, which is the case that can actually run something: closing it
    // promotes a neighbour into view. Both have run here (the switch below), so the
    // promoted one resolves to its cached execution and closing costs nothing.
    await user.click(screen.getByRole('tab', {name: 'refunds'}));
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    await user.click(screen.getByTitle('Close refunds'));

    expect(screen.getAllByRole('tab')).toHaveLength(1);
    expect(screen.getByRole('tab', {name: 'orders'})).toHaveAttribute('aria-selected', 'true');
    expect(runQuery).toHaveBeenCalledTimes(2);
  });

  it('closing the last tab leaves the picker, and still runs nothing', async () => {
    // Zero tabs is a legal state here, unlike the Query workspace's — so the last tab keeps
    // its close control and what replaces it is the picker, not an empty frame.
    seedTabs([{id: 't1', table: 'orders'}]);
    const {user} = render();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    await user.click(screen.getByTitle('Close orders'));

    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
    expect(await screen.findByRole('region', {name: 'Choose a table to explore'})).toBeInTheDocument();
    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  it('closes the focused tab with Delete, so the ✕ never has to be reachable', async () => {
    // The ✕ is a non-focusable span (it sits INSIDE `role="tab"`, where a nested button
    // trips axe), so this key is what keeps the action operable — WCAG 2.1.1, and the
    // Query strip's own arrangement.
    seedTabs([
      {id: 't1', table: 'orders'},
      {id: 't2', table: 'refunds'}
    ]);
    const {user} = render();
    const tab = await screen.findByRole('tab', {name: 'orders'});

    tab.focus();
    await user.keyboard('{Delete}');

    expect(screen.queryByRole('tab', {name: 'orders'})).not.toBeInTheDocument();
  });

  it('survives a reload through sessionStorage', async () => {
    const {user, unmount} = render();
    await user.click(await screen.findByRole('button', {name: 'orders'}));
    await screen.findByRole('tab', {name: 'orders'});

    // A reload is a fresh mount over the same session storage — the tab has to come back
    // from there, so the previous tree is torn down first rather than left standing beside
    // it (which would let the assertion below pass on the ORIGINAL tab).
    unmount();
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();

    render();
    expect(await screen.findByRole('tab', {name: 'orders'})).toBeInTheDocument();
  });
});

// ─── Accessibility ──────────────────────────────────────────────────────────

describe('accessibility', () => {
  it('leaves the picker axe-clean', async () => {
    render();
    await screen.findByRole('button', {name: 'orders'});

    await expectContainerHasNoA11yViolations(document.body, COMPONENT_AXE_OPTIONS);
  });

  it('leaves the tab strip and results axe-clean', async () => {
    // The check that caught a real violation: a `<button>` close control inside
    // `role="tab"` trips `aria-required-children`, which is exactly why the Query strip
    // uses a non-focusable span. Driven into the state that has tabs, then asserted on the
    // rendered container — axe snapshots the tree when it starts, so a state the caller has
    // to wait for must be waited for first.
    seedTabs([
      {id: 't1', table: 'orders'},
      {id: 't2', table: 'refunds'}
    ]);
    render();
    await screen.findByRole('columnheader', {name: 'id'});

    await expectContainerHasNoA11yViolations(document.body, COMPONENT_AXE_OPTIONS);
  });
});

// ─── FR-009: the placeholder results table ──────────────────────────────────

describe('the results table (a placeholder SPEC-180 replaces)', () => {
  it('renders the columns and rows of a succeeded execution', async () => {
    seedTabs([{id: 't1', table: 'orders'}]);
    render();

    expect(await screen.findByRole('columnheader', {name: 'id'})).toBeInTheDocument();
    expect(screen.getByRole('columnheader', {name: 'total'})).toBeInTheDocument();
    expect(screen.getByRole('cell', {name: '9.99'})).toBeInTheDocument();
    expect(screen.getByText(/Rows 1–2/)).toBeInTheDocument();
  });

  it('renders the friendly empty state for a zero-row result, not an error', async () => {
    vi.mocked(getQueryResults).mockResolvedValue(ok({columns: [{name: 'id', type: 'varchar'}], rows: []}) as never);
    seedTabs([{id: 't1', table: 'orders'}]);
    render();

    expect(await screen.findByText('No rows returned.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('maps a failed execution through toUserMessage — no Athena text reaches the user', async () => {
    vi.mocked(runQuery).mockResolvedValue({
      success: false,
      error: {message: 'SYNTAX_ERROR: line 1:8: Column "nope" cannot be resolved'}
    } as never);
    seedTabs([{id: 't1', table: 'orders'}]);
    render();

    const alert = await screen.findByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).not.toMatch(/SYNTAX_ERROR/);
    expect(screen.queryByText(/cannot be resolved/)).not.toBeInTheDocument();
  });
});
