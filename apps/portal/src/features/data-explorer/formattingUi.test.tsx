import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {STRIPING_OFF_TEXT} from './StripingControl';
import {PATTERN_REFUSAL, STRIPE_BACKGROUND} from './formatting';
import {newExploration} from './exploration';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import type {ExplorationTabsState} from './dataExplorer.types';
import {chooseExplorationOption} from './explorationOptions.testkit';

// SPEC-184 FR-001–FR-004 and FR-007, driven through the real workspace. The claim that
// carries the whole spec is a NEGATIVE one, and it is asserted by COUNT: every gesture in
// this file leaves `runQuery` on the single execution the tab opened with. Presentation is
// the half of an exploration that cannot cost anything, and that is only true because the
// renderer cannot see it.

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

const COLUMNS = [
  {name: 'id', type: 'varchar'},
  {name: 'status', type: 'varchar'},
  {name: 'qty', type: 'bigint'}
];
// Two consecutive rows share an `id`, so a band is a run rather than a grouping.
const ROWS: (string | null)[][] = [
  ['a', 'ok', '10'],
  ['a', 'failed', '20'],
  ['b', 'ok', null]
];

function render() {
  const user = userEvent.setup(USER_EVENT_OPTIONS);
  renderWithProviders(<DataExplorerWorkspace />, {route: '/explore', auth: authenticated('alice')});
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

function storedFormatting() {
  const raw = sessionStorage.getItem(`${EXPLORATION_TABS_STORAGE_PREFIX}alice`) ?? '{}';
  return JSON.parse(raw).tabs?.[0]?.exploration?.presentation?.formatting;
}

/** The cell at (row, column) — rows are the grid's body rows, 0-based. */
function cell(row: number, name: string): HTMLElement {
  const columns = screen
    .getAllByRole('columnheader')
    .map((th) => th.getAttribute('aria-label'))
    .filter((label): label is string => label !== null && label !== '#');
  const bodyRow = screen.getAllByRole('row')[row + 1]; // row 0 is the header
  return within(bodyRow).getAllByRole('gridcell')[columns.indexOf(name)];
}

async function openColours(user: ReturnType<typeof userEvent.setup>) {
  await chooseExplorationOption(user, 'Colors');
  return screen.getByRole('dialog', {name: 'Colors'});
}

/** Adds a rule and fills the fields a simple `equals` rule needs. */
async function addRule(
  user: ReturnType<typeof userEvent.setup>,
  dialog: HTMLElement,
  options: {column?: string; value: string; colour?: string; paints?: string} = {value: ''}
) {
  await user.click(within(dialog).getByRole('button', {name: 'Add rule'}));
  if (options.column) {
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Rule 1 column'}), options.column);
  }
  await user.type(within(dialog).getByRole('textbox', {name: 'Rule 1 value'}), options.value);
  if (options.colour) {
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Rule 1 text color'}), options.colour);
  }
  if (options.paints) {
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Rule 1 paints'}), options.paints);
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(ok({version: 1, connections: []}) as never);
  vi.mocked(getDatabase).mockResolvedValue(ok({name: 'alice'}) as never);
  vi.mocked(listTables).mockResolvedValue(ok([{name: 'orders', tableType: 'EXTERNAL_TABLE', columns: []}]) as never);
  vi.mocked(runQuery).mockResolvedValue(ok({queryExecutionId: 'exec-1'}) as never);
  vi.mocked(getQueryStatus).mockResolvedValue(
    ok({
      queryExecutionId: 'exec-1',
      state: 'SUCCEEDED',
      dataScannedBytes: 2048,
      engineExecutionTimeMillis: 120
    }) as never
  );
  vi.mocked(getQueryResults).mockResolvedValue(ok({columns: COLUMNS, rows: ROWS}) as never);
  seedTab();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('nothing in the formatting surfaces runs a query (FR-001)', () => {
  it('applies a rule, the type tint and striping without a second execution', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'status'});
    // The tab's own opening execution, and the only one this test may ever see.
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));
    const resultReads = vi.mocked(getQueryResults).mock.calls.length;

    const dialog = await openColours(user);
    await addRule(user, dialog, {column: 'status', value: 'ok', colour: 'Red'});
    await user.click(within(dialog).getByRole('checkbox', {name: /data type/i}));
    await user.click(within(dialog).getByRole('checkbox', {name: 'id'}));
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));
    await waitFor(() => expect(cell(0, 'status')).toHaveStyle({color: 'var(--color-danger)'}));

    // A GRADIENT rule, which renders a different set of controls and a different code path.
    const withGradient = await openColours(user);
    await user.click(within(withGradient).getByRole('button', {name: 'Add rule'}));
    await user.selectOptions(within(withGradient).getByRole('combobox', {name: 'Rule 2 column'}), 'qty');
    await user.click(within(withGradient).getByRole('checkbox', {name: 'Rule 2 shades a number range'}));
    await user.click(within(withGradient).getByRole('button', {name: 'Apply'}));
    await waitFor(() => expect(storedFormatting().rules).toHaveLength(2));

    // Every TRANSFORMER kind, all in one Apply.
    await chooseExplorationOption(user, 'Transformers');
    const transformers = screen.getByRole('dialog', {name: 'Transformers'});
    await user.selectOptions(within(transformers).getByRole('combobox', {name: 'Show qty as'}), 'numeric');
    await user.selectOptions(within(transformers).getByRole('combobox', {name: 'Show id as'}), 'binary');
    await user.selectOptions(within(transformers).getByRole('combobox', {name: 'Show status as'}), 'url');
    await user.click(within(transformers).getByRole('button', {name: 'Apply'}));
    await waitFor(() => expect(cell(0, 'qty')).toHaveTextContent('10.00'));

    // And REMOVING a rule, which is the gesture a count test is likeliest to skip.
    const toRemove = await openColours(user);
    await user.click(within(toRemove).getByRole('button', {name: 'Remove rule 1'}));
    await user.click(within(toRemove).getByRole('button', {name: 'Apply'}));
    await waitFor(() => expect(storedFormatting().rules).toHaveLength(1));

    expect(runQuery).toHaveBeenCalledTimes(1);
    // …and the rows on screen are the ones already fetched (AC3): no refetch either.
    expect(vi.mocked(getQueryResults).mock.calls.length).toBe(resultReads);
  });
});

describe('conditional colouring (FR-002)', () => {
  it('paints only the matching cells, and the whole row when asked to', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'status'});

    const dialog = await openColours(user);
    await addRule(user, dialog, {column: 'status', value: 'failed', colour: 'Red'});
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(cell(1, 'status')).toHaveStyle({color: 'var(--color-danger)'}));
    expect(cell(1, 'id')).not.toHaveStyle({color: 'var(--color-danger)'});
    expect(cell(0, 'status')).not.toHaveStyle({color: 'var(--color-danger)'});

    const again = await openColours(user);
    await user.selectOptions(within(again).getByRole('combobox', {name: 'Rule 1 paints'}), 'row');
    await user.click(within(again).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(cell(1, 'id')).toHaveStyle({color: 'var(--color-danger)'}));
    expect(cell(0, 'id')).not.toHaveStyle({color: 'var(--color-danger)'});
  });

  it('refuses an invalid pattern at entry and applies nothing', async () => {
    // A broken pattern that silently matched nothing would look exactly like a rule that
    // is simply not true of this page — which is the failure the requirement names.
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'status'});

    const dialog = await openColours(user);
    // An unclosed group: invalid to the engine, and free of the `[`/`{` that user-event
    // reads as its own keyboard descriptors.
    await addRule(user, dialog, {column: 'status', value: '(', colour: 'Red'});
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Rule 1 test'}), 'regex');
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(PATTERN_REFUSAL);
    // Still open, with the draft intact — the user has somewhere to correct it.
    expect(screen.getByRole('dialog', {name: 'Colors'})).toBeInTheDocument();
    expect(storedFormatting().rules).toEqual([]);
  });

  it('lets a later rule override an earlier one, and lets the order be changed', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'status'});

    const dialog = await openColours(user);
    await addRule(user, dialog, {column: 'status', value: 'ok', colour: 'Red'});
    await user.click(within(dialog).getByRole('button', {name: 'Add rule'}));
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Rule 2 column'}), 'status');
    await user.type(within(dialog).getByRole('textbox', {name: 'Rule 2 value'}), 'ok');
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Rule 2 text color'}), 'Green');
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(cell(0, 'status')).toHaveStyle({color: 'var(--color-success)'}));

    // Reordering is the only way to resolve two rules that disagree, so it is part of the
    // requirement rather than a convenience.
    const again = await openColours(user);
    await user.click(within(again).getByRole('button', {name: 'Move rule 2 earlier'}));
    await user.click(within(again).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(cell(0, 'status')).toHaveStyle({color: 'var(--color-danger)'}));
  });
});

describe('group row striping (FR-004)', () => {
  it('bands consecutive equal rows and says which rows it looked at', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'id'});

    const dialog = await openColours(user);
    expect(within(dialog).getByText(STRIPING_OFF_TEXT)).toBeInTheDocument();
    // Per element, as jsdom has no layout: each row's 24px floor keeps a wrapped checkbox clear of the next.
    const picks = within(within(dialog).getByRole('group', {name: 'Band rows by'})).getAllByRole('checkbox');
    expect(picks).toHaveLength(COLUMNS.length);
    for (const pick of picks) expect(pick.closest('label')).toHaveClass('min-h-[24px]');
    await user.click(within(dialog).getByRole('checkbox', {name: 'id'}));
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    // Rows 0 and 1 share `a` and form the first band; row 2 opens the second and is tinted.
    await waitFor(() => expect(cell(2, 'id')).toHaveStyle({backgroundColor: STRIPE_BACKGROUND}));
    expect(cell(0, 'id')).not.toHaveStyle({backgroundColor: STRIPE_BACKGROUND});
    expect(cell(1, 'id')).not.toHaveStyle({backgroundColor: STRIPE_BACKGROUND});
  });
});

describe('persistence (FR-007)', () => {
  it('keeps the rules with the tab, and keeps an inapplicable one visible', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'status'});

    const dialog = await openColours(user);
    await addRule(user, dialog, {column: 'status', value: 'ok', colour: 'Red'});
    await user.click(within(dialog).getByRole('checkbox', {name: 'id'}));
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    await waitFor(() =>
      expect(storedFormatting()).toMatchObject({
        colourByType: false,
        stripeColumns: ['id'],
        rules: [{column: 'status', operator: '=', value: 'ok', foreground: 'danger'}]
      })
    );
  });
});

describe('transformers (FR-005, FR-006)', () => {
  /** Opens the transformers dialog and points one column at a transformer kind. */
  async function transform(
    user: ReturnType<typeof userEvent.setup>,
    column: string,
    kind: 'numeric' | 'binary' | 'url'
  ) {
    await chooseExplorationOption(user, 'Transformers');
    const dialog = screen.getByRole('dialog', {name: 'Transformers'});
    await user.selectOptions(within(dialog).getByRole('combobox', {name: `Show ${column} as`}), kind);
    return dialog;
  }

  it('renders a number to a precision without changing what a filter sends', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'qty'});

    const dialog = await transform(user, 'qty', 'numeric');
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));
    await waitFor(() => expect(cell(0, 'qty')).toHaveTextContent('10.00'));

    // The filter has to carry the RAW `10`. `"qty" = 10.00` is a different predicate, and
    // against a bigint column Athena would reject it outright.
    await user.click(cell(0, 'qty'));
    await chooseExplorationOption(user, 'Filter by this value');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(2));
    expect(vi.mocked(runQuery).mock.calls[1][0].sql).toContain('"qty" = 10');
    expect(vi.mocked(runQuery).mock.calls[1][0].sql).not.toContain('10.00');
  });

  it('leaves Calc aggregating the raw values, not the rendering', async () => {
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'qty'});

    // Hex is the transformer that makes this observable: `10` renders as `3130`, which is
    // ITSELF a plain number — so a Calc reading the rendering would answer 6360 rather
    // than fail visibly.
    const dialog = await transform(user, 'qty', 'binary');
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));
    await waitFor(() => expect(cell(0, 'qty')).toHaveTextContent('3130'));

    await user.click(cell(0, 'qty'));
    await chooseExplorationOption(user, 'Calc');
    const panel = screen.getByRole('complementary', {name: 'Calc'});
    await user.click(within(panel).getByRole('checkbox', {name: 'Sum'}));
    await user.keyboard('{Shift>}');
    await user.click(cell(1, 'qty'));
    await user.keyboard('{/Shift}');

    const sum = within(panel)
      .getAllByRole('term')
      .find((dt) => dt.textContent === 'Sum')
      ?.parentElement?.querySelector('dd')?.textContent;
    await waitFor(() => expect(sum).toContain('30'));
  });

  it('renders no anchor for any scheme but https', async () => {
    // Each one driven through a real cell value with a bare `${value}` template — the
    // template that hands the whole address to the data, and the only shape in which a
    // cell can choose the scheme at all.
    vi.mocked(getQueryResults).mockResolvedValue(
      ok({
        columns: [{name: 'link', type: 'varchar'}],
        rows: [
          ['javascript:alert(1)'],
          ['data:text/html,<script>alert(1)</script>'],
          ['vbscript:msgbox'],
          ['file:///etc/passwd'],
          ['https://example.com/ok']
        ]
      }) as never
    );
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'link'});

    const dialog = await transform(user, 'link', 'url');
    await user.clear(within(dialog).getByRole('textbox', {name: 'Link for link'}));
    // `{` opens a key descriptor in user-event's keyboard syntax, so the brace is doubled
    // to type one literally — the input ends up holding exactly `${value}`.
    await user.type(within(dialog).getByRole('textbox', {name: 'Link for link'}), '${{value}');
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(screen.getAllByRole('link')).toHaveLength(1));
    const [link] = screen.getAllByRole('link');
    expect(link).toHaveAttribute('href', 'https://example.com/ok');
    // The two attributes that keep an opened tab from reaching back into this one.
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(link).toHaveAttribute('target', '_blank');
    // Every refused scheme is still SHOWN — as text, with its reason available.
    expect(cell(0, 'link')).toHaveTextContent('javascript:alert(1)');
  });
});

describe('the fixes review found', () => {
  it('accepts a negative and a decimal gradient bound', async () => {
    // A number-only round trip cannot be typed into: `Number('-')` is NaN and renders as
    // empty, so the minus is erased, and `1.` renders as `1`, so the point is. Both make a
    // range like `-10..1.5` unreachable, which is most of what a gradient is for.
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'qty'});

    const dialog = await openColours(user);
    await user.click(within(dialog).getByRole('button', {name: 'Add rule'}));
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Rule 1 column'}), 'qty');
    await user.click(within(dialog).getByRole('checkbox', {name: 'Rule 1 shades a number range'}));

    const start = within(dialog).getByRole('textbox', {name: 'Rule 1 range start'});
    const end = within(dialog).getByRole('textbox', {name: 'Rule 1 range end'});
    await user.clear(start);
    await user.type(start, '-10');
    await user.clear(end);
    await user.type(end, '1.5');
    expect(start).toHaveValue('-10');
    expect(end).toHaveValue('1.5');

    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));
    await waitFor(() =>
      expect(storedFormatting().rules[0].gradient).toEqual({
        min: -10,
        max: 1.5,
        from: 'accent-soft',
        to: 'danger-soft'
      })
    );
  });

  it('keeps the grid a single tab stop when a column renders links', async () => {
    // `role="grid"` promises one tab stop with the arrows moving within it. A focusable
    // anchor per row would put a hundred stops inside the grid, and Tab from the cursor
    // would walk the column instead of leaving.
    vi.mocked(getQueryResults).mockResolvedValue(
      ok({
        columns: [{name: 'link', type: 'varchar'}],
        rows: [['https://example.com/a'], ['https://example.com/b']]
      }) as never
    );
    const {user} = render();
    await screen.findByRole('columnheader', {name: 'link'});

    await chooseExplorationOption(user, 'Transformers');
    const dialog = screen.getByRole('dialog', {name: 'Transformers'});
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Show link as'}), 'url');
    await user.clear(within(dialog).getByRole('textbox', {name: 'Link for link'}));
    await user.type(within(dialog).getByRole('textbox', {name: 'Link for link'}), '${{value}');
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(screen.getAllByRole('link')).toHaveLength(2));
    for (const link of screen.getAllByRole('link')) expect(link).toHaveAttribute('tabindex', '-1');

    // …and the keyboard route to the link is the Value panel, which is what makes that
    // decision cost a keyboard user nothing.
    await user.click(cell(0, 'link'));
    await chooseExplorationOption(user, 'Value');
    const panel = await screen.findByRole('complementary', {name: 'Value'});
    const panelLink = within(panel).getByRole('link');
    expect(panelLink).toHaveAttribute('href', 'https://example.com/a');
    expect(panelLink).not.toHaveAttribute('tabindex');
  });
});

describe('a rule that tests for an empty cell (SPEC-238 FR-006)', () => {
  it('takes no value: the field leaves the tree, and Apply succeeds without one', async () => {
    const {user} = render();
    await screen.findAllByRole('gridcell');
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    const dialog = await openColours(user);
    await user.click(within(dialog).getByRole('button', {name: 'Add rule'}));
    // The value field is there for the default operator, so its absence below is a change
    // rather than a query that never matched anything.
    expect(within(dialog).getByRole('textbox', {name: 'Rule 1 value'})).toBeInTheDocument();

    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Rule 1 test'}), 'isEmpty');
    // REMOVED, not disabled: a disabled input beside a rule that ignores it still reads as
    // a control that means something.
    expect(within(dialog).queryByRole('textbox', {name: 'Rule 1 value'})).not.toBeInTheDocument();

    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Rule 1 column'}), 'qty');
    await user.selectOptions(within(dialog).getByRole('combobox', {name: 'Rule 1 background'}), 'Amber tint');
    await user.click(within(dialog).getByRole('button', {name: 'Apply'}));

    await waitFor(() => expect(screen.queryByRole('dialog', {name: 'Colors'})).not.toBeInTheDocument());
    // `qty` is NULL on the third row and a number on the first two — so the rule paints
    // the one cell that holds nothing, and Colors runs no query to do it.
    await waitFor(() => expect(cell(2, 'qty')).toHaveStyle({backgroundColor: 'var(--color-warning-soft)'}));
    expect(cell(0, 'qty')).not.toHaveStyle({backgroundColor: 'var(--color-warning-soft)'});
    expect(runQuery).toHaveBeenCalledTimes(1);
  });
});
