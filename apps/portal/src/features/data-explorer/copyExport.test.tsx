import {beforeEach, afterEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders, USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {newExploration} from './exploration';
import {COPY_FAILED, NOTHING_TO_EXPORT, NO_RESULT_COLUMN_TO_SAVE} from './ExplorationResultsRegion';
import {COPY_LOADED_ROWS_NOTE, COPY_QUOTING_INERT, COPY_RECTANGLE_NOTE} from './AdvancedCopyDialog';
import {getDatabase, listTables} from '../catalog/glue.service';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {copyObject, listFiles, objectExists} from '../file-browser/fileBrowser.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {enqueueResultsConversion} from '../catalog/resultsConversion.service';
import type {ExplorationTab, ExplorationTabsState} from './dataExplorer.types';
import {chooseExplorationOption, explorationOption} from './explorationOptions.testkit';

// SPEC-185 FR-001 / FR-002. Integration style (react.md §21): the real workspace, the real
// grid and selection, the real `useSaveResults` and the real `SaveResultsDialog` —
// mocking only the AWS boundary and the clipboard, which jsdom does not implement.
//
// The number this file exists to assert is a ZERO: neither copying nor exporting may start
// an execution, so `runQuery` is counted across both.
vi.mock('../catalog/glue.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/glue.service')>()),
  getDatabase: vi.fn(),
  listTables: vi.fn()
}));
vi.mock('../catalog/athena.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/athena.service')>()),
  runQuery: vi.fn(),
  getQueryStatus: vi.fn(),
  getQueryResults: vi.fn()
}));
vi.mock('../file-browser/fileBrowser.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../file-browser/fileBrowser.service')>()),
  listFiles: vi.fn(),
  copyObject: vi.fn(),
  ensurePrefixMarker: vi.fn().mockResolvedValue({success: true}),
  objectExists: vi.fn().mockResolvedValue({success: true, data: true})
}));
vi.mock('../shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn(),
  enqueueSharedSpaceRequest: vi.fn()
}));
vi.mock('../catalog/resultsConversion.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/resultsConversion.service')>()),
  enqueueResultsConversion: vi.fn()
}));

const ok = <T,>(data: T) => ({success: true as const, data});

const OUTPUT_LOCATION = 's3://user-space/alice/athenaresults/exec-1.csv';
const TABLE = {name: 'orders', tableType: 'EXTERNAL_TABLE', location: 's3://user-space/alice/orders/', columns: []};

/** What the clipboard was last handed, and how many times it was written. */
let clipboardWrites: string[];

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
  const {container} = renderWithProviders(<DataExplorerWorkspace />, {
    route: '/explore',
    auth: authenticated('alice')
  });
  // AFTER `setup()`, deliberately: user-event installs its own `navigator.clipboard` stub,
  // so a spy defined before it is silently replaced and every copy assertion then reads an
  // empty array — a failure that looks like "copy does nothing" rather than like a harness
  // problem.
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: {
      writeText: vi.fn(async (text: string) => {
        clipboardWrites.push(text);
      })
    }
  });
  return {user, container};
}

/** Make the next clipboard write fail, as a denied permission or an insecure context does. */
function refuseClipboard() {
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: {writeText: vi.fn().mockRejectedValue(new Error('NotAllowedError'))}
  });
}

/** The grid, once the seeded tab's first execution has landed. */
async function grid() {
  return screen.findByRole('grid', {name: 'Results'});
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

async function clickCell(user: ReturnType<typeof render>['user'], row: number, column: string) {
  await user.click(cell(row, column));
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  clipboardWrites = [];
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(ok({version: 1, connections: []}) as never);
  vi.mocked(getDatabase).mockResolvedValue(ok({name: 'alice'}) as never);
  vi.mocked(listTables).mockResolvedValue(ok([TABLE]) as never);
  vi.mocked(runQuery).mockResolvedValue(ok({queryExecutionId: 'exec-1'}) as never);
  vi.mocked(getQueryStatus).mockResolvedValue(
    ok({
      queryExecutionId: 'exec-1',
      state: 'SUCCEEDED',
      dataScannedBytes: 2048,
      engineExecutionTimeMillis: 120,
      outputLocation: OUTPUT_LOCATION
    })
  );
  // A NULL beside an empty string, and a value a URL transformer will rewrite on screen.
  vi.mocked(getQueryResults).mockResolvedValue(
    ok({
      columns: [
        {name: 'region', type: 'varchar'},
        {name: 'qty', type: 'bigint'}
      ],
      rows: [
        ['north', '10'],
        ['south', null]
      ]
    }) as never
  );
  vi.mocked(listFiles).mockResolvedValue(ok({files: [], folders: [], nextToken: undefined}) as never);
  vi.mocked(copyObject).mockResolvedValue(ok({destKey: 'alice/out.csv'}) as never);
  vi.mocked(enqueueResultsConversion).mockResolvedValue(ok({requestId: 'r1'}) as never);
  // The conversion path pre-flights the destination; the module mock above answers "taken",
  // which is the overwrite test's premise and nobody else's.
  vi.mocked(objectExists).mockResolvedValue(ok(false) as never);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

// ─── FR-001: copy ───────────────────────────────────────────────────────────

describe('copy (FR-001)', () => {
  it('Ctrl/Cmd+C copies the selection as tab-delimited text, rows in grid order', async () => {
    // AC1.
    seedTab();
    const {user} = render();
    await grid();
    await clickCell(user, 0, 'region');
    await user.keyboard('{Shift>}{ArrowDown}{ArrowRight}{/Shift}');
    await user.keyboard('{Control>}c{/Control}');

    await waitFor(() => expect(clipboardWrites).toHaveLength(1));
    expect(clipboardWrites[0]).toBe('north\t10\nsouth\tNULL');
  });

  it('copies the RAW value, not the transformed rendering', async () => {
    // AC3. A HEX transformer on purpose, on SPEC-182's precedent: a URL transformer keeps
    // the raw value as its link text, so a copy of the rendering and a copy of the value
    // would be the same string and the assertion could not fail. Hex renders something
    // else entirely, so this test can only pass if `renderCopy` reads the row.
    seedTab({
      exploration: {
        ...newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1'),
        presentation: {
          ...newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1')
            .presentation,
          formatting: {
            rules: [],
            colourByType: false,
            stripeColumns: [],
            transformers: {region: {kind: 'binary', encoding: 'hex', maxLength: 64}}
          }
        }
      }
    });
    const {user} = render();
    await grid();
    // On screen the cell is hex…
    await waitFor(() => expect(cell(0, 'region')).toHaveTextContent('6e6f727468'));

    await clickCell(user, 0, 'region');
    await user.keyboard('{Control>}c{/Control}');

    // …and the clipboard carries what the cell actually holds.
    await waitFor(() => expect(clipboardWrites).toHaveLength(1));
    expect(clipboardWrites[0]).toBe('north');
  });

  it('a column header selection copies the whole LOADED column, and the label says so', async () => {
    // AC6. The grid holds one page, so "the whole column" is the page — which the status
    // line and the dialog both say out loud rather than leaving to be discovered.
    seedTab();
    const {user} = render();
    await grid();
    await user.click(screen.getByRole('columnheader', {name: 'region'}));
    expect(await screen.findByRole('status')).toHaveTextContent('2 cells selected on this page');

    await user.keyboard('{Control>}c{/Control}');
    await waitFor(() => expect(clipboardWrites).toHaveLength(1));
    expect(clipboardWrites[0]).toBe('north\nsouth');
  });

  it('the advanced dialog copies in the chosen format and states both surprises', async () => {
    // AC2 and AC5: the format choice and the three toggles, plus the rectangle rule and the
    // loaded-rows rule stated in the UI.
    seedTab();
    const {user} = render();
    await grid();
    await clickCell(user, 0, 'region');
    await user.keyboard('{Shift>}{ArrowDown}{ArrowRight}{/Shift}');
    await chooseExplorationOption(user, 'Copy…');

    const dialog = await screen.findByRole('dialog', {name: 'Copy selection'});
    expect(within(dialog).getByText(COPY_RECTANGLE_NOTE)).toBeInTheDocument();
    expect(within(dialog).getByText(COPY_LOADED_ROWS_NOTE)).toBeInTheDocument();

    await user.selectOptions(within(dialog).getByLabelText('Format'), 'json');
    await user.click(within(dialog).getByRole('button', {name: 'Copy'}));

    await waitFor(() => expect(clipboardWrites).toHaveLength(1));
    // Headers on by default in the dialog, and a NULL is a real null.
    expect(JSON.parse(clipboardWrites[0])).toEqual([
      {region: 'north', qty: '10'},
      {region: 'south', qty: null}
    ]);
  });

  it('a REFUSED clipboard write is reported, never announced as a success', async () => {
    // `useCopyToClipboard` swallows the rejection — safe for a caller that renders its
    // `copied` flag, a lie for this one, which closes the dialog and has to say what
    // happened. Reachable: Safari denies `writeText` outside a gesture it recognises.
    seedTab();
    const {user} = render();
    await grid();
    await clickCell(user, 0, 'region');
    refuseClipboard();
    await chooseExplorationOption(user, 'Copy…');
    const dialog = await screen.findByRole('dialog', {name: 'Copy selection'});
    await user.click(within(dialog).getByRole('button', {name: 'Copy'}));

    expect(await screen.findByText(COPY_FAILED)).toBeInTheDocument();
    expect(screen.queryByText('Copied to the clipboard.')).not.toBeInTheDocument();
  });

  it('the plain Ctrl/Cmd+C reports a refused write too', async () => {
    // Silent on success — the paste is the confirmation — but the grid suppressed the
    // browser's own copy, so a silent failure leaves the PREVIOUS clipboard contents in
    // place under the impression they are the new ones.
    seedTab();
    const {user} = render();
    await grid();
    await clickCell(user, 0, 'region');
    refuseClipboard();
    await user.keyboard('{Control>}c{/Control}');

    expect(await screen.findByText(COPY_FAILED)).toBeInTheDocument();
  });

  it('copies the whole generated statement, exactly as it ran, from beside it', async () => {
    seedTab();
    const {user} = render();
    await grid();
    await user.click(screen.getByText('Generated SQL'));
    const shown = (screen.getByLabelText('Generated SQL') as HTMLTextAreaElement).value;

    await user.click(await screen.findByRole('button', {name: 'Copy SQL'}));

    expect(clipboardWrites).toEqual([shown]);
    expect(shown).toMatch(/FROM\s+"alice"\."orders"/);
  });

  it('issues NO query, however it is used', async () => {
    // AC7. One execution for the exploration itself, and not one more for any amount of
    // selecting, formatting and copying.
    seedTab();
    const {user} = render();
    await grid();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    await clickCell(user, 0, 'region');
    await user.keyboard('{Shift>}{ArrowDown}{/Shift}');
    await user.keyboard('{Control>}c{/Control}');
    await chooseExplorationOption(user, 'Copy…');
    const dialog = await screen.findByRole('dialog', {name: 'Copy selection'});
    await user.selectOptions(within(dialog).getByLabelText('Format'), 'markdown');
    await user.click(within(dialog).getByRole('button', {name: 'Copy'}));

    await waitFor(() => expect(clipboardWrites).toHaveLength(2));
    expect(runQuery).toHaveBeenCalledTimes(1);
  });
});

describe('accessibility', () => {
  it('the copy dialog has no axe violations, with the quoting refusal REACHABLE', async () => {
    seedTab();
    const {user, container} = render();
    await grid();
    await clickCell(user, 0, 'region');
    await chooseExplorationOption(user, 'Copy…');
    const dialog = await screen.findByRole('dialog', {name: 'Copy selection'});

    // SPEC-172's rule: the refusal is `aria-disabled`, so the control stays in the tab order
    // and its reason is announced with it rather than being something a keyboard user tabs
    // straight past.
    await user.selectOptions(within(dialog).getByLabelText('Format'), 'json');
    const quoting = within(dialog).getByLabelText('Quote values');
    expect(quoting).toHaveAttribute('aria-disabled', 'true');
    expect(quoting).toBeEnabled();
    expect(quoting).toHaveAccessibleDescription(COPY_QUOTING_INERT);
    // And it does not toggle, which `aria-disabled` alone would not prevent.
    await user.click(quoting);
    expect(quoting).not.toBeChecked();

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });
});

// ─── FR-002: export ─────────────────────────────────────────────────────────

describe('export (FR-002)', () => {
  /** Open the export dialog on a tab whose first execution has landed. */
  // The control lives in the Options menu, so the wait for the execution is a wait on the MENU
  // ITEM's refusal clearing — same assertion, one layer in. The menu is reopened each pass
  // rather than held open across the wait, because a stale handle would assert against an item
  // detached from the document.
  async function openExport(user: ReturnType<typeof render>['user']) {
    await waitFor(async () =>
      expect(await explorationOption(user, 'Save results…')).not.toHaveAttribute('aria-disabled', 'true')
    );
    await chooseExplorationOption(user, 'Save results…');
    return screen.findByRole('dialog', {name: 'Save results'});
  }

  it('offers Save results beside the pager once a result exists, opening the same dialog', async () => {
    // The Query workspace's own control, by name — a user who found it there finds it here.
    seedTab();
    const {user} = render();
    await grid();

    await user.click(await screen.findByRole('button', {name: 'Save results…'}));
    expect(await screen.findByRole('dialog', {name: 'Save results'})).toBeInTheDocument();
  });

  it('copies the EXECUTION’s own results object, and starts no second query', async () => {
    // AC1. The copy is server-side and takes the object Athena wrote, so a filtered,
    // ordered or grouped exploration exports what is on screen with no second bill.
    seedTab();
    const {user} = render();
    await grid();
    await waitFor(() => expect(runQuery).toHaveBeenCalledTimes(1));

    const dialog = await openExport(user);
    const name = within(dialog).getByLabelText('File name');
    await user.clear(name);
    await user.type(name, 'out');
    await user.click(within(dialog).getByRole('button', {name: 'Save here'}));

    await waitFor(() => expect(copyObject).toHaveBeenCalledTimes(1));
    expect(vi.mocked(copyObject).mock.calls[0][0]).toMatchObject({
      bucket: 'user-space',
      sourceKey: 'alice/athenaresults/exec-1.csv',
      destBucket: 'user-space',
      destKey: 'alice/out.csv',
      overwrite: false
    });
    // THE ZERO.
    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  it('a destination collision prompts before anything is replaced', async () => {
    // AC2: the overwrite prompt is `useSaveResults`' own, unchanged.
    seedTab();
    vi.mocked(copyObject)
      .mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}} as never)
      .mockResolvedValueOnce(ok({destKey: 'alice/out.csv'}) as never);
    const {user} = render();
    await grid();

    const dialog = await openExport(user);
    await user.clear(within(dialog).getByLabelText('File name'));
    await user.type(within(dialog).getByLabelText('File name'), 'out');
    await user.click(within(dialog).getByRole('button', {name: 'Save here'}));

    await user.click(await screen.findByRole('button', {name: 'Overwrite'}));
    await waitFor(() => expect(copyObject).toHaveBeenCalledTimes(2));
    expect(vi.mocked(copyObject).mock.calls[1][0]).toMatchObject({overwrite: true});
  });

  it('is refused until an execution has succeeded, with the reason in the tab order', async () => {
    // AC3. `Button.disabledReason` renders `aria-disabled`, not `disabled`, so the reason is
    // reachable rather than hover-only (SPEC-172).
    seedTab();
    // The execution never reports a results location, which is exactly the state a running
    // or failed one is in.
    vi.mocked(getQueryStatus).mockResolvedValue(
      ok({queryExecutionId: 'exec-1', state: 'SUCCEEDED', dataScannedBytes: 1, engineExecutionTimeMillis: 1})
    );
    const {user} = render();
    await grid();

    // Asserted on the MENU ITEM. `aria-disabled`, not `disabled` — the reason has to be
    // reachable, which is exactly why the item was given `MenuItem.disabledReason` rather
    // than being dropped from the menu when it moved off the toolbar.
    const item = await explorationOption(user, 'Save results…');
    expect(item).toHaveAttribute('aria-disabled', 'true');
    expect(item).not.toHaveAttribute('disabled');
    expect(item).toHaveAttribute('title', NOTHING_TO_EXPORT);
    // The grid is on screen (the menu just opened over it), so this absence is not a race
    // with the load: the button beside the pager is withheld, and the menu item is where
    // the refusal is read.
    expect(screen.queryByRole('button', {name: 'Save results…'})).not.toBeInTheDocument();
  });
});

// ─── SPEC-239: an export leaves out the columns the grid hides ──────────────

describe('exporting what the grid shows (SPEC-239 FR-005)', () => {
  const THREE = {
    columns: [
      {name: 'a', type: 'varchar'},
      {name: 'b', type: 'varchar'},
      {name: 'c', type: 'varchar'}
    ],
    rows: [['1', '2', '3']]
  };

  /** A tab whose presentation already hides or pins, with a three-column result behind it. */
  function seedGrid(presentation: Record<string, unknown> = {}) {
    vi.mocked(getQueryResults).mockResolvedValue(ok(THREE) as never);
    const base = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
    seedTab({exploration: {...base, presentation: {...base.presentation, ...presentation}}});
  }

  async function saveAs(user: ReturnType<typeof render>['user'], name: string) {
    await waitFor(async () =>
      expect(await explorationOption(user, 'Save results…')).not.toHaveAttribute('aria-disabled', 'true')
    );
    await chooseExplorationOption(user, 'Save results…');
    const dialog = await screen.findByRole('dialog', {name: 'Save results'});
    await user.clear(within(dialog).getByLabelText('File name'));
    await user.type(within(dialog).getByLabelText('File name'), name);
    return dialog;
  }

  it('a CSV save of a grid with a hidden column converts instead of copying', async () => {
    // AC2. The whole point of the spec: a copy cannot produce this file, so the one format that
    // used to be an instant copy goes to the plane — and the copy service is not called at all.
    seedGrid({hiddenColumns: ['b']});
    const {user} = render();
    await grid();

    const dialog = await saveAs(user, 'out');
    // AC7 rides here: the dialog is already open and the sentence is what tells the user the
    // file will not hold what the full result does.
    expect(within(dialog).getByText('The file holds 2 result columns, in the order shown.')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', {name: 'Convert and save'}));

    await waitFor(() => expect(enqueueResultsConversion).toHaveBeenCalledTimes(1));
    expect(vi.mocked(enqueueResultsConversion).mock.calls[0][0]).toMatchObject({
      format: 'csv',
      columnIndexes: [0, 2],
      onConflict: 'refuse'
    });
    expect(copyObject).not.toHaveBeenCalled();
    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  it('an overwrite writes the file the question was asked about', async () => {
    // AC3. The prompt carries the columns for the same reason it carries the format: the grid
    // is still behind it, and a re-derived list would write a different file.
    seedGrid({hiddenColumns: ['b']});
    vi.mocked(objectExists).mockResolvedValue(ok(true) as never);
    const {user} = render();
    await grid();

    const dialog = await saveAs(user, 'out');
    await user.click(within(dialog).getByRole('button', {name: 'Convert and save'}));
    await user.click(await screen.findByRole('button', {name: 'Overwrite'}));

    await waitFor(() => expect(enqueueResultsConversion).toHaveBeenCalledTimes(1));
    expect(vi.mocked(enqueueResultsConversion).mock.calls[0][0]).toMatchObject({
      format: 'csv',
      columnIndexes: [0, 2],
      onConflict: 'overwrite'
    });
    expect(copyObject).not.toHaveBeenCalled();
  });

  it('a pinned column reorders the file without anything being hidden', async () => {
    // AC4. "Grid order" is the order the grid draws, pinned block first — so a save can carry a
    // list while every column is still shown.
    seedGrid({pinnedColumns: ['c']});
    const {user} = render();
    await grid();

    const dialog = await saveAs(user, 'out');
    await user.click(within(dialog).getByRole('button', {name: 'Convert and save'}));

    await waitFor(() => expect(enqueueResultsConversion).toHaveBeenCalledTimes(1));
    expect(vi.mocked(enqueueResultsConversion).mock.calls[0][0]).toMatchObject({columnIndexes: [2, 0, 1]});
  });

  it('an untouched grid still saves CSV by copying, and says so on the button', async () => {
    // AC5, and the positive control for every test above: with nothing hidden and nothing moved
    // there is no file a conversion could produce that the object Athena wrote does not have.
    seedGrid();
    const {user} = render();
    await grid();

    const dialog = await saveAs(user, 'out');
    // Matched on the sentence the dialog ACTUALLY renders. This read `/columns shown are saved/`,
    // which the copy had since been reworded away from — a negative query pointed at a string
    // nothing produces passes whatever the dialog shows.
    expect(within(dialog).queryByText(/The file holds \d+ result column/)).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', {name: 'Save here'}));

    await waitFor(() => expect(copyObject).toHaveBeenCalledTimes(1));
    expect(enqueueResultsConversion).not.toHaveBeenCalled();
  });

  it('says "column" when the grid is down to one', async () => {
    // The plural is built, not written, and "Only the 1 columns" is a sentence this dialog can
    // reach: the geometry refuses to hide the LAST visible column, so one of three is ordinary.
    seedGrid({hiddenColumns: ['a', 'b']});
    const {user} = render();
    await grid();

    const dialog = await saveAs(user, 'out');

    expect(within(dialog).getByText('The file holds 1 result column, in the order shown.')).toBeInTheDocument();
  });

  it('carries the columns from the BUTTON beside the pager too, not just the menu item', async () => {
    // Two call sites, one screen apart, and every other test here reaches export through the
    // Options menu — so the pager button, which is the one the guide tells a user to click, had
    // nothing holding it. Measured: passing `null` there instead of the list left all 136 tests
    // green while a CSV save with a hidden column silently wrote the whole result.
    seedGrid({hiddenColumns: ['b']});
    const {user} = render();
    await grid();

    await user.click(await screen.findByRole('button', {name: 'Save results…'}));
    const dialog = await screen.findByRole('dialog', {name: 'Save results'});
    expect(within(dialog).getByText('The file holds 2 result columns, in the order shown.')).toBeInTheDocument();
    await user.clear(within(dialog).getByLabelText('File name'));
    await user.type(within(dialog).getByLabelText('File name'), 'out');
    await user.click(within(dialog).getByRole('button', {name: 'Convert and save'}));

    await waitFor(() => expect(enqueueResultsConversion).toHaveBeenCalledTimes(1));
    expect(vi.mocked(enqueueResultsConversion).mock.calls[0][0]).toMatchObject({columnIndexes: [0, 2]});
  });

  it("resolves against the EXECUTION's columns, never the Glue fallback", async () => {
    // The two agree the moment a result lands, so every other test here is blind to this: the
    // difference only shows in the window where an output location exists and the result's
    // columns do not — a re-execution whose rows have not arrived. Resolving against Glue there
    // would send POSITIONS IN A DIFFERENT LIST, and the plane resolves nothing.
    //
    // Measured: swapping `results.columns` for `executionColumns` passed all 538 tests before
    // this one existed.
    vi.mocked(listTables).mockResolvedValue(
      ok([
        {
          ...TABLE,
          columns: [
            {name: 'g1', type: 'string'},
            {name: 'g2', type: 'string'},
            {name: 'g3', type: 'string'}
          ]
        }
      ]) as never
    );
    vi.mocked(getQueryResults).mockResolvedValue(ok({columns: [], rows: []}) as never);
    const base = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
    seedTab({exploration: {...base, presentation: {...base.presentation, hiddenColumns: ['g2']}}});
    const {user} = render();
    await screen.findByRole('grid', {name: 'Results'});

    const dialog = await saveAs(user, 'out');
    await user.click(within(dialog).getByRole('button', {name: 'Save here'}));

    // A copy, with no list at all: the grid is hiding a GLUE column, and Glue's positions are
    // not the result's to send.
    await waitFor(() => expect(copyObject).toHaveBeenCalledTimes(1));
    expect(enqueueResultsConversion).not.toHaveBeenCalled();
  });

  it("the host's reason wins when both are true, because it is the one a user can act on", async () => {
    // Both refusals hold at once whenever an execution has not produced a results object AND
    // the grid is showing none of its columns — and "nothing has finished running" is the one
    // to say. Flipping the precedence passes every other test in this file.
    vi.mocked(getQueryStatus).mockResolvedValue(
      ok({queryExecutionId: 'exec-1', state: 'SUCCEEDED', dataScannedBytes: 1, engineExecutionTimeMillis: 1})
    );
    vi.mocked(getQueryResults).mockResolvedValue(ok({columns: [{name: 'a', type: 'varchar'}], rows: [['1']]}) as never);
    const base = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
    seedTab({exploration: {...base, presentation: {...base.presentation, hiddenColumns: ['a']}}});
    const {user} = render();
    await grid();

    const item = await explorationOption(user, 'Save results…');

    expect(item).toHaveAttribute('aria-disabled', 'true');
    expect(item).toHaveAttribute('title', NOTHING_TO_EXPORT);
  });

  it('a grouped exploration showing only its percentage column refuses the save', async () => {
    // AC6. The one reachable way to show no result column at all: `useColumnGeometry` refuses to
    // hide the last VISIBLE column, and the percentage column is visible and in no result.
    vi.mocked(getQueryResults).mockResolvedValue(
      ok({
        columns: [
          {name: 'region', type: 'varchar'},
          {name: 'count_all', type: 'bigint'}
        ],
        rows: [['north', '2']]
      }) as never
    );
    const base = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'}, 't1');
    seedTab({
      exploration: {
        ...base,
        query: {
          ...base.query,
          grouping: {
            columns: ['region'],
            aggregates: [{fn: 'COUNT', column: '*'}],
            duplicatesOnly: false,
            showPercentage: true
          }
        },
        presentation: {...base.presentation, hiddenColumns: ['region', 'count_all']}
      }
    });
    const {user} = render();
    await grid();

    const item = await waitFor(async () => {
      const found = await explorationOption(user, 'Save results…');
      expect(found).toHaveAttribute('aria-disabled', 'true');
      return found;
    });

    expect(item).toHaveAccessibleDescription(NO_RESULT_COLUMN_TO_SAVE);
    expect(screen.queryByRole('button', {name: 'Save results…'})).not.toBeInTheDocument();
  });
});
