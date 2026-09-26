import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, screen, waitFor, within} from '@testing-library/react';
import {Link} from 'react-router';
import type {QueryClient} from '@tanstack/react-query';
import type {ReactNode} from 'react';
import {createTestQueryClient, renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import userEvent from '@testing-library/user-event';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {resolveExploreParams, spaceDatabase} from './exploreSources';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {newExploration} from './exploration';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryRowCount, getQueryStatus, runQuery} from '../catalog/athena.service';
import {MAX_POLL_DURATION_MS, POLL_INTERVAL_MS} from '../catalog/catalog.constants';
import {catalogKeys} from '../catalog/catalogKeys';
import {withFakeTimers} from '../../test/fakeTimers';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {connectionKeys} from '../connections/connectionKeys';
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
  getQueryResults: vi.fn(),
  getQueryRowCount: vi.fn()
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
  label: 'alice',
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

/** `beside` renders next to the workspace under the same router, standing in for the shell around it. */
function render(route = '/explore', seededClient?: QueryClient, beside?: ReactNode) {
  const user = userEvent.setup(USER_EVENT_OPTIONS);
  const {unmount, queryClient} = renderWithProviders(
    <>
      <DataExplorerWorkspace />
      {beside}
    </>,
    {route, auth: authenticated('alice'), ...(seededClient && {queryClient: seededClient})}
  );
  return {user, unmount, queryClient};
}

const TEAMSPACE = ok({version: 1, connections: [{name: 'teamspace', role: 'member', status: 'active'}]});

/** A client already holding a spaces list — without `teamspace` unless `withTeamspace` — read `ageMs` ago
 *  under the app's 30s staleTime rather than the harness's 0, so whether a read is owed on mount is the
 *  test's choice. */
function clientWithCachedList(ageMs: number, withTeamspace = false) {
  const client = createTestQueryClient();
  client.setQueryDefaults(connectionKeys.list('alice'), {gcTime: Infinity, staleTime: 30_000});
  client.setQueryData(connectionKeys.list('alice'), withTeamspace ? TEAMSPACE.data : {version: 1, connections: []}, {
    updatedAt: Date.now() - ageMs
  });
  return client;
}
const TEAMSPACE_LINK = '/explore?space=teamspace&db=teamspace&table=orders';

/** Seed the session's tabs the way a previous visit would have left them. */
function seedTabs(tabs: {id: string; table: string}[], activeTabId = tabs[0]?.id ?? '') {
  const state: ExplorationTabsState = {
    version: 1,
    tabs: tabs.map(({id, table}): ExplorationTab => ({
      id,
      label: table,
      exploration: newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table}, id),
      scannedByExecution: {},
      history: {past: [], future: []}
    })),
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
  it('offers every space personal-first, under one name each', async () => {
    render();

    // ONE name per row. Printing the label beside the Glue database doubled a shared space's
    // name, and suppressing it only there still left the personal row reading `My filesalice`.
    await waitFor(() =>
      expect(screen.getAllByRole('button', {name: /^(alice|teamspace)/}).map((b) => b.textContent)).toEqual([
        'alice',
        'teamspace'
      ])
    );
  });

  it('groups the chosen space’s objects into Tables and Views', async () => {
    render();

    expect(await screen.findByRole('heading', {name: 'Tables (1)'})).toBeInTheDocument();
    expect(screen.getByRole('heading', {name: 'Views (1)'})).toBeInTheDocument();

    // Each object still opens a tab from its own section — a view is a perfectly good thing
    // to explore, and the renderer does not care which it is reading.
    expect(screen.getByRole('button', {name: 'orders'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: /revenue_view/})).toBeInTheDocument();

    // Tables lead. Asserted because the constant claims "the one order they are ever offered",
    // and two `getByRole` calls prove both headings exist while saying nothing about which
    // comes first.
    const headings = screen.getAllByRole('heading', {name: /^(Tables|Views) \(/}).map((h) => h.textContent);
    expect(headings).toEqual(['Tables (1)', 'Views (1)']);
  });

  // Two assertions, because "nothing above them" has two ways to be false. The heading
  // enumeration catches a title that IS a heading, however it is worded — a `queryByText` for
  // the removed string would pass against a re-worded one. The STRUCTURAL assertion catches a
  // title that is not a heading at all: a reviewer put the old text back as a styled `<p>` one
  // size larger than the group headings, which is exactly the "restates them and outranks
  // them" defect, and the role-based half saw nothing. Comparing the column's first child to
  // the list is markup-agnostic — any element inserted above the list fails it, whatever tag
  // or role it wears.
  it('heads the list with the two groups and nothing above them', async () => {
    render();
    const tables = await screen.findByRole('heading', {name: 'Tables (1)'});

    const region = screen.getByRole('region', {name: 'Choose a table to explore'});
    expect(
      within(region)
        .getAllByRole('heading')
        .map((h) => h.textContent)
    ).toEqual(['Space', 'Tables (1)', 'Views (1)']);

    // No tab is open in this render, so no Cancel: the one row above the list holds only
    // Open saved view, and the list follows it directly.
    const list = tables.closest('section')!.parentElement!;
    const row = list.parentElement!.firstElementChild as HTMLElement;
    expect(within(row).getAllByRole('button').map((b) => b.textContent)).toEqual(['Open saved view']);
    expect(row.nextElementSibling).toBe(list);
  });

  // Pinned to the class because jsdom loads no Tailwind and has no layout, so a prominent
  // heading and a dim caption measure identically here — the same reason the header's wordmark
  // test asserts its class. The two negatives are SEPARATE calls: `toHaveClass(a, b)` asserts
  // both are present, so one `not.toHaveClass('uppercase', 'text-text-3')` passes on a heading
  // that re-adds `uppercase` alone, which is half the regression it claims to hold.
  it('renders those group headings as headings rather than dim captions', async () => {
    render();
    const tables = await screen.findByRole('heading', {name: 'Tables (1)', level: 2});

    expect(tables).toHaveClass('text-base', 'font-semibold', 'text-text');
    expect(tables).not.toHaveClass('uppercase');
    expect(tables).not.toHaveClass('text-text-3');
  });

  // The create-table flow left this screen entirely — it is reached from the Files toolbar,
  // where the folder in view is the answer. Asserted over every button AND link the whole
  // screen renders, not by name and not scoped to the picker's region: the control that was
  // here read "Create table from a folder…", and a query for that exact string would pass
  // against any other create affordance put in its place. A reviewer proved both narrowings —
  // the same wording came back as an `<a>` inside the region, and as a `<button>` just outside
  // it, and the earlier assertion agreed the screen offered no way to create a table. The
  // `arrayContaining` is the positive control: an empty list satisfies a bare filter.
  it('offers no way to create a table', async () => {
    render();
    await screen.findByRole('heading', {name: 'Tables (1)'});

    const labels = [...screen.getAllByRole('button'), ...screen.queryAllByRole('link')].map(
      (el) => el.textContent ?? ''
    );
    expect(labels).toEqual(expect.arrayContaining(['alice', 'orders']));
    expect(labels.filter((label) => /create/i.test(label))).toEqual([]);
  });

  // Cancel is the picker's other state, and it had no test of its own while the create
  // section beside it did — so restructuring that header row could have taken it silently.
  // It also pins the scope of the structural assertion above: with a tab open the Cancel row
  // IS the column's first child, which is why that test says "no tab is open in this render"
  // rather than asserting a rule that only holds in one of the two states.
  it('offers Cancel once there is an exploration to go back to, and returns to it', async () => {
    seedTabs([{id: 't1', table: 'orders'}]);
    const {user} = render();

    await user.click(await screen.findByRole('button', {name: 'New exploration'}));
    const cancel = await screen.findByRole('button', {name: 'Cancel'});

    // Cancel is the one thing the picker still renders over its groups, so it belongs above
    // them. Asserted as DOCUMENT ORDER rather than as a sibling relationship: the latter would
    // also fail on a refactor that merely dropped the wrapper element, which is not the
    // regression this is here to catch.
    const tables = await screen.findByRole('heading', {name: 'Tables (1)'});
    const list = tables.closest('section')!.parentElement!;
    expect(cancel.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    await user.click(cancel);
    expect(screen.queryByRole('heading', {name: 'Tables (1)'})).not.toBeInTheDocument();
  });

  // A space with no views is the ordinary case for a new one, and it is the only shape that
  // enters the empty-section branch — the fixture above has one of each, so nothing reached it.
  // An always-present "Views (0)" is a heading that never says anything.
  it('omits a section with no members rather than showing it empty', async () => {
    vi.mocked(listTables).mockResolvedValue(ok([TABLE]) as never);
    render();

    expect(await screen.findByRole('heading', {name: 'Tables (1)'})).toBeInTheDocument();
    expect(screen.queryByRole('heading', {name: /^Views/})).not.toBeInTheDocument();
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
    expect(screen.getByRole('button', {name: /^alice/})).toBeInTheDocument();
  });
});

// ─── FR-006: deep links ─────────────────────────────────────────────────────

describe('the deep link', () => {
  it.each([
    ['names a space the fresh list has', TEAMSPACE_LINK, 'tab'],
    ['names no table, so opens the picker', '/explore?space=someone_elses&db=someone_elses', 'picker']
  ])('does not read the spaces list for a link that %s', async (_case, route, opens) => {
    // Only a refusal waits. Waiting on anything else would put a spinner and a read in front of every
    // "Explore data" click from the Query rail, whose links name spaces the list already holds.
    render(route, clientWithCachedList(0, true));

    if (opens === 'tab') expect(await screen.findByRole('tab', {name: 'orders'})).toBeInTheDocument();
    else expect(await screen.findByRole('button', {name: 'orders'})).toBeInTheDocument();
    expect(readSharedConnectionsCache).not.toHaveBeenCalled();
  });

  it('opens a tab on the named table when all three parameters resolve', async () => {
    render('/explore?space=personal&db=alice&table=orders');

    expect(await screen.findByRole('tab', {name: 'orders'})).toBeInTheDocument();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    expect(vi.mocked(runQuery).mock.calls[0][0]).toMatchObject({sql: 'SELECT *\nFROM "alice"."orders"'});
  });

  it.each([
    ['nothing is cached', () => undefined],
    ['a fresh cached list lacks it', () => clientWithCachedList(0)]
  ])(
    'renders the denied state for an unreachable space and asks NOTHING of Glue or Athena (%s)',
    async (_c, seeded) => {
      render('/explore?space=someone_elses&db=someone_elses&table=orders', seeded());

      expect(await screen.findByRole('heading', {name: 'You don’t have access to that space'})).toBeInTheDocument();
      // One read of the user's own list, after the link: a cached list may predate a space just joined.
      expect(readSharedConnectionsCache).toHaveBeenCalledOnce();
      // The disclosure this guards: a Glue call would answer whether a database the user
      // cannot see exists, and an Athena call would read it (SPEC-113's rule).
      expect(getDatabase).not.toHaveBeenCalled();
      expect(listTables).not.toHaveBeenCalled();
      expect(runQuery).not.toHaveBeenCalled();
      // …and no picker either, so nothing else can start a request behind the refusal.
      expect(screen.queryByRole('button', {name: 'orders'})).not.toBeInTheDocument();
    }
  );

  it.each([
    ['a fresh cached list predates the space', () => clientWithCachedList(0)],
    ['a stale cached list predates the space', () => clientWithCachedList(60_000)]
  ])('reads the spaces list before refusing a space it lacks (%s)', async (_cached, seeded) => {
    // Trusted, a list read before the user joined refused a space they can read. Fresh, nothing read it
    // again and the refusal stood; stale, it showed until the read owed on mount returned.
    let resolveRead: (result: unknown) => void = () => {};
    vi.mocked(readSharedConnectionsCache).mockReturnValue(new Promise((resolve) => (resolveRead = resolve)) as never);
    render(TEAMSPACE_LINK, seeded());

    await waitFor(() => expect(readSharedConnectionsCache).toHaveBeenCalledOnce());
    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.queryByRole('heading', {name: 'You don’t have access to that space'})).not.toBeInTheDocument();
    expect(getDatabase).not.toHaveBeenCalled();

    resolveRead(TEAMSPACE);
    expect(await screen.findByRole('tab', {name: 'orders'})).toBeInTheDocument();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    expect(vi.mocked(runQuery).mock.calls[0][0]).toMatchObject({sql: 'SELECT *\nFROM "teamspace"."orders"'});
  });

  it('reads the spaces list again when a link followed on the open page names a space it lacks', async () => {
    // The workspace does not remount when a link lands on it, so no read is owed: checked against the
    // list it opened with, a space joined since was refused, and nothing ever read the list again.
    vi.mocked(readSharedConnectionsCache).mockResolvedValueOnce(ok({version: 1, connections: []}) as never);
    const {user, queryClient} = render(
      '/explore',
      clientWithCachedList(60_000),
      <Link to={TEAMSPACE_LINK}>Explore teamspace orders</Link>
    );
    await waitFor(() => expect(readSharedConnectionsCache).toHaveBeenCalledOnce());
    await waitFor(() => expect(queryClient.isFetching({queryKey: connectionKeys.list('alice')})).toBe(0));

    let resolveRead: (result: unknown) => void = () => {};
    vi.mocked(readSharedConnectionsCache).mockReturnValue(new Promise((resolve) => (resolveRead = resolve)) as never);
    await user.click(screen.getByRole('link', {name: 'Explore teamspace orders'}));

    expect(screen.queryByRole('heading', {name: 'You don’t have access to that space'})).not.toBeInTheDocument();
    expect(readSharedConnectionsCache).toHaveBeenCalledTimes(2);

    resolveRead(TEAMSPACE);
    expect(await screen.findByRole('tab', {name: 'orders'})).toBeInTheDocument();
    expect(screen.queryByRole('heading', {name: 'You don’t have access to that space'})).not.toBeInTheDocument();
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

  it('refuses an unreachable NAMED space and shrugs at an absent one', () => {
    expect(resolveExploreParams({space: 'nope', db: 'nope', table: 'orders'}, spaces, 'alice', true)).toEqual({
      status: 'denied'
    });
    expect(resolveExploreParams({space: null, db: 'alice', table: 'orders'}, spaces, 'alice', true)).toMatchObject({
      status: 'ready'
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

  it('looks again when switching to a tab that shares the execution a watch gave up on', async () => {
    await withFakeTimers(async () => {
      // Two tabs on one table and one description render one statement, so the start cache hands
      // both the same execution: only the switch itself can tell the watch to look again.
      seedTabs([
        {id: 't1', table: 'orders'},
        {id: 't2', table: 'orders'}
      ]);
      vi.mocked(getQueryStatus).mockResolvedValue(ok({queryExecutionId: 'exec-1', state: 'RUNNING'}));
      const {user} = render();
      await waitFor(() => expect(getQueryStatus).toHaveBeenCalled());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(MAX_POLL_DURATION_MS);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 10);
      });
      await screen.findByText(/Data Quarry stopped waiting for this query/);

      // The query finishes in Athena after the watch has ended.
      vi.mocked(getQueryStatus).mockResolvedValue(
        ok({queryExecutionId: 'exec-1', state: 'SUCCEEDED', dataScannedBytes: 2048, engineExecutionTimeMillis: 120})
      );
      const readsBefore = vi.mocked(getQueryStatus).mock.calls.length;
      await user.click(screen.getAllByRole('tab', {name: 'orders'})[1]);

      expect(await screen.findByRole('gridcell', {name: '9.99'})).toBeInTheDocument();
      expect(vi.mocked(getQueryStatus).mock.calls.length).toBeGreaterThan(readsBefore);
      expect(screen.queryByText(/Data Quarry stopped waiting for this query/)).not.toBeInTheDocument();
      expect(runQuery).toHaveBeenCalledTimes(1);
    });
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

// ─── FR-009: the results region ─────────────────────────────────────────────

// The grid itself is SPEC-180's (`gridGeometry.test.tsx` and friends); what stays here is
// SPEC-179's own claim — that a succeeded execution renders, a zero-row one is an answer
// rather than a fault, and a failed one is mapped before it reaches a user.
describe('the results region', () => {
  it('renders the columns and rows of a succeeded execution', async () => {
    seedTabs([{id: 't1', table: 'orders'}]);
    render();

    expect(await screen.findByRole('columnheader', {name: 'id'})).toBeInTheDocument();
    expect(screen.getByRole('columnheader', {name: 'total'})).toBeInTheDocument();
    expect(screen.getByRole('gridcell', {name: '9.99'})).toBeInTheDocument();
    expect(screen.getByText(/Rows 1–2/)).toBeInTheDocument();
  });

  // Testers read "Rows 1–100" as all there was. The total is Athena's count, as on the Query tab.
  it.each([
    {count: new Promise(() => {}), pager: 'Rows 1–2 · counting…'},
    {count: Promise.resolve(ok({rowCount: 12_345, pending: false})), pager: 'Rows 1–2 of 12,345'}
  ])('says $pager while more pages remain', async ({count, pager}) => {
    vi.mocked(getQueryResults).mockResolvedValue(
      ok({columns: [{name: 'id', type: 'varchar'}], rows: [['1'], ['2']], nextToken: 't-2'}) as never
    );
    vi.mocked(getQueryRowCount).mockReturnValue(count as never);
    seedTabs([{id: 't1', table: 'orders'}]);

    render();

    expect(await screen.findByText(pager)).toBeInTheDocument();
    expect(getQueryRowCount).toHaveBeenCalledWith('exec-1');
  });

  // The Query workspace's two rules for a count that disagrees with the grid. Each waits for the
  // count to land first: read before it, the pager says the same thing on unfixed code.
  it.each([
    {rule: 'a count below the rows loaded is not a total', nextToken: 't-2', count: 1, pager: 'Rows 1–2'},
    {
      rule: 'the pager’s own count wins once it holds the last page',
      nextToken: undefined,
      count: 5,
      pager: 'Rows 1–2 of 2'
    }
  ])('shows $pager: $rule', async ({nextToken, count, pager}) => {
    vi.mocked(getQueryResults).mockResolvedValue(
      ok({columns: [{name: 'id', type: 'varchar'}], rows: [['1'], ['2']], nextToken}) as never
    );
    vi.mocked(getQueryRowCount).mockResolvedValue(ok({rowCount: count, pending: false}) as never);
    seedTabs([{id: 't1', table: 'orders'}]);

    const {queryClient} = render();

    await waitFor(() => expect(queryClient.getQueryData(catalogKeys.rowCount('exec-1'))).toBe(count));
    expect(await screen.findByText(pager)).toBeInTheDocument();
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

  it('settles a first apply that outlives the ceiling with a warning, and says Running… nowhere', async () => {
    await withFakeTimers(async () => {
      vi.mocked(getQueryStatus).mockResolvedValue(ok({queryExecutionId: 'exec-1', state: 'RUNNING'}));
      seedTabs([{id: 't1', table: 'orders'}]);
      render();
      await waitFor(() => expect(getQueryStatus).toHaveBeenCalled());
      expect(screen.getAllByText('Running…').length).toBeGreaterThan(0);

      // The ceiling's mark in an act of its own, then the one poll whose read decides.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(MAX_POLL_DURATION_MS);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 10);
      });

      const banner = (
        await screen.findByText(
          'Data Quarry stopped waiting for this query after 30 minutes, so its results won’t appear here. When it finishes, they’re saved in your files under system_settings/athenaresults, in a file named after its query ID (exec-1).'
        )
      ).closest('[role="alert"]');
      expect(banner).toHaveTextContent('Still running');
      expect(banner).toHaveClass('bg-warning-soft');
      expect(screen.queryByText('Running…')).not.toBeInTheDocument();
      expect(screen.queryByText('No rows returned.')).not.toBeInTheDocument();
    });
  });

  it('leaves nothing under the banner of a first apply that failed — no Running…, no empty answer', async () => {
    vi.mocked(getQueryStatus).mockResolvedValue(
      ok({queryExecutionId: 'exec-1', state: 'FAILED', stateChangeReason: "line 1:8: mismatched input 'FROM'"})
    );
    seedTabs([{id: 't1', table: 'orders'}]);
    render();

    const banner = (await screen.findByText(/syntax error in your query/i)).closest('[role="alert"]');
    expect(banner).toHaveClass('bg-danger-soft');
    expect(screen.queryByText('Running…')).not.toBeInTheDocument();
    expect(screen.queryByText('No rows returned.')).not.toBeInTheDocument();
  });
});
