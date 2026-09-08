import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import userEvent from '@testing-library/user-event';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {resolveExploreParams, spaceDatabase} from './exploreSources';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
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
      expect(screen.getAllByRole('button', {name: /^(My files|teamspace)/}).map((b) => b.textContent)).toEqual([
        'My files',
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

    // No tab is open in this render, so no Cancel row: the list is the column's first child.
    const list = tables.closest('section')!.parentElement!;
    expect(list.parentElement!.firstElementChild).toBe(list);
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
    expect(labels).toEqual(expect.arrayContaining(['My files', 'orders']));
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
    expect(screen.getByRole('button', {name: /^My files/})).toBeInTheDocument();
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
