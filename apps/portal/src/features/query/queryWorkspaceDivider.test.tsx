import {NavRailProvider} from '../../components/NavRailProvider';
import {QueryWorkspace} from './QueryWorkspace';
import {authenticated} from '../../test/authFixtures';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {fireEvent, screen} from '@testing-library/react';
import {
  EDITOR_SPLIT_DIVIDER_HEIGHT,
  MIN_EDITOR_HEIGHT,
  MIN_RESULTS_HEIGHT,
  QUERY_EDITOR_SPLIT_STORAGE_PREFIX
} from './query.constants';
import {
  installWorkspaceMocks,
  mockListSaved,
  renderWorkspace,
  resetViewport,
  savedListing,
  seedSingle
} from '../../test/queryWorkspaceSupport';
import {monacoLayout} from '../../test/sqlEditorStub';
import {renderWithProviders} from '../../test/renderWithProviders';

// The editor/results divider, driven through the workspace that owns the measured column and
// the split — the same seam as every other workspace journey.
vi.mock('./SqlEditor', () => import('../../test/sqlEditorStub'));

// ── AWS service boundary (the only real seam) ────────────────────────────────
vi.mock('../catalog/athena.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/athena.service')>()),
  runQuery: vi.fn(),
  stopQuery: vi.fn(),
  getTableDdl: vi.fn(),
  runStatementToCompletion: vi.fn(),
  getQueryStatus: vi.fn(),
  getQueryResults: vi.fn(),
  getQueryRowCount: vi.fn()
}));

vi.mock('../catalog/glue.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/glue.service')>()),
  getDatabase: vi.fn(),
  listTables: vi.fn()
}));

vi.mock('./queryHistory.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./queryHistory.service')>()),
  getQueryHistory: vi.fn(),
  appendQueryHistory: vi.fn(),
  updateQueryHistoryEntry: vi.fn()
}));

vi.mock('../saved-queries/savedQueries.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../saved-queries/savedQueries.service')>()),
  // The name/key helpers stay REAL — a tab label and a list row must not be able to
  // disagree about what a file is called, and a mocked `savedQueryName` would hide it.
  ensureSavedQueriesFolder: vi.fn(),
  listSavedQueries: vi.fn(),
  readSavedQuery: vi.fn(),
  writeSavedQuery: vi.fn(),
  deleteSavedQuery: vi.fn()
}));

vi.mock('../shared-spaces/sharedSpaces.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../shared-spaces/sharedSpaces.service')>()),
  readSharedConnectionsCache: vi.fn()
}));

vi.mock('../file-browser/fileBrowser.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../file-browser/fileBrowser.service')>()),
  copyObject: vi.fn(),
  listFiles: vi.fn()
}));

vi.mock('../table-share/tableShare.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../table-share/tableShare.service')>()),
  enqueueTableShare: vi.fn()
}));

vi.mock('../table-builder/tableBuild.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../table-builder/tableBuild.service')>()),
  enqueueTableRefresh: vi.fn()
}));

describe('QueryWorkspace — the editor/results divider', () => {
  beforeEach(installWorkspaceMocks);
  afterEach(resetViewport);

  // jsdom lays nothing out, so the measured column would be 0 and every drag a
  // divide by zero. `clientHeight` is read by one source file — the workspace's
  // own column measurement — so spying the getter gives that one measurement a
  // real value and leaves everything else alone. The editor pane's height is an
  // INLINE style, not layout, so it stays observable.
  const COLUMN = 1000;
  let heights: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    heights = vi.spyOn(Element.prototype, 'clientHeight', 'get').mockReturnValue(COLUMN);
  });
  afterEach(() => heights.mockRestore());

  // `fireEvent` rather than `userEvent` for the pointer sequences, against §21's
  // default: the drag's listeners live on the window, and the released-off-element
  // case has to dispatch on the document, neither of which userEvent's pointer API
  // can target. Every other interaction here is userEvent. The three drag tests
  // already in this repo do the same.
  const divider = () => screen.getByRole('separator', {name: 'Resize the editor and results'});
  // The separator sits inside a 24px band with the two step buttons, because a
  // focusable widget may not contain focusable descendants. The BAND is the
  // column's flex child, so the panes are its siblings, not the separator's.
  const band = () => divider().parentElement as HTMLElement;
  const editorPane = () => band().previousElementSibling as HTMLElement;

  async function renderReady() {
    seedSingle('SELECT 1');
    const rendered = renderWorkspace();
    await screen.findByRole('button', {name: 'sales_2026'});
    return rendered;
  }

  it('drags the split by the pointer DELTA from the gesture origin, and re-lays-out Monaco', async () => {
    await renderReady();
    expect(editorPane().style.height).toBe('500px');
    expect(divider()).toHaveAttribute('aria-valuenow', '50');
    // No text selection while dragging: the handler cancels the gesture's default.
    expect(divider()).toHaveClass('select-none');
    monacoLayout.mockClear();

    // The grab point is deliberately NOT the pane height. They coincide only if
    // the divider sits at the top of the viewport, which it never does — the
    // header, tab strip and toolbar are above it — and a handler that read the
    // pointer as an absolute position would agree with a delta handler at every
    // grab point where they are equal.
    // Grab the GRIP, not the band: the visible pill is what a user aims at, and
    // it is a child of the separator, so the gesture arrives with a target that
    // is not the element carrying the handler.
    const grip = divider().firstElementChild as HTMLElement;
    expect(fireEvent.pointerDown(grip, {clientY: 800})).toBe(false); // preventDefault'd
    fireEvent.pointerMove(window, {clientY: 1000}); // +200 from the origin

    expect(editorPane().style.height).toBe('700px');
    expect(divider()).toHaveAttribute('aria-valuenow', '70');
    expect(divider()).toHaveAttribute('aria-valuetext', 'Editor 70% of the column');
    expect(monacoLayout).toHaveBeenCalledTimes(1);
    fireEvent.pointerUp(window);
  });

  it('ends the drag on a release dispatched off the element, and persists what it ended on', async () => {
    const {unmount} = await renderReady();

    fireEvent.pointerDown(divider(), {clientY: 800});
    fireEvent.pointerMove(window, {clientY: 1000});
    // The listeners live on the window, so a release dispatched on the document
    // still ends the gesture — the case a pointer released off-screen produces.
    fireEvent.pointerUp(document);
    fireEvent.pointerMove(window, {clientY: 1200});

    expect(editorPane().style.height).toBe('700px');
    // The failure a hook test cannot see is the workspace not reading it back.
    unmount();
    await renderReady();
    expect(editorPane().style.height).toBe('700px');
  });

  it('persists a value the next mount will accept, even when the drag ran past a floor', async () => {
    // The move handler clamps, and nothing rendered depends on it — `fraction`
    // and `editorHeight` both re-clamp downstream. What depends on it is the
    // value that reaches storage: an unclamped over-drag persists a negative
    // number, `isFraction` rejects it on the next mount, and the user's split
    // silently reverts to even.
    const {unmount} = await renderReady();
    fireEvent.pointerDown(divider(), {clientY: 800});
    fireEvent.pointerMove(window, {clientY: -5000});
    fireEvent.pointerUp(window);
    expect(editorPane().style.height).toBe(`${MIN_EDITOR_HEIGHT}px`);

    unmount();
    await renderReady();
    expect(editorPane().style.height).toBe(`${MIN_EDITOR_HEIGHT}px`);
  });

  it('stops at the editor floor and at the results floor', async () => {
    await renderReady();

    fireEvent.pointerDown(divider(), {clientY: 500});
    fireEvent.pointerMove(window, {clientY: -5000});
    expect(editorPane().style.height).toBe(`${MIN_EDITOR_HEIGHT}px`);

    fireEvent.pointerMove(window, {clientY: 5000});
    expect(editorPane().style.height).toBe(`${COLUMN - MIN_RESULTS_HEIGHT - EDITOR_SPLIT_DIVIDER_HEIGHT}px`);
    fireEvent.pointerUp(window);
  });

  it('is an accessible separator, and the column is its three flex children', async () => {
    await renderReady();

    expect(divider()).toHaveAttribute('aria-orientation', 'horizontal');
    expect(divider()).toHaveAttribute('tabindex', '0');
    expect(divider()).toHaveAttribute('aria-valuemin', String(Math.round((MIN_EDITOR_HEIGHT / COLUMN) * 100)));
    expect(divider()).toHaveAttribute(
      'aria-valuemax',
      String(Math.round(((COLUMN - MIN_RESULTS_HEIGHT - EDITOR_SPLIT_DIVIDER_HEIGHT) / COLUMN) * 100))
    );
    // jsdom computes no styles, so a visible ring is only assertable as the class.
    expect(divider()).toHaveClass('focus-visible:ring-2');
    expect(band().style.height).toBe(`${EDITOR_SPLIT_DIVIDER_HEIGHT}px`);

    // The panes and the divider exactly fill the column because they are its
    // only children and the results side takes the flex remainder. jsdom lays
    // nothing out, so this is the structural half; the arithmetic half is the
    // containment sweep over `clampEditorHeight`.
    const column = band().parentElement as HTMLElement;
    expect(column.children).toHaveLength(3);
    expect(editorPane()).toHaveClass('flex-none');
    expect(band()).toHaveClass('flex-none');
    expect(band().nextElementSibling).toHaveClass('flex-1', 'min-h-0');
  });

  it('moves the split with the arrow keys, Home and End', async () => {
    const {user} = await renderReady();
    divider().focus();
    expect(divider()).toHaveFocus();

    await user.keyboard('{ArrowUp}');
    expect(divider()).toHaveAttribute('aria-valuenow', '45');
    await user.keyboard('{ArrowDown}{ArrowDown}');
    expect(divider()).toHaveAttribute('aria-valuenow', '55');
    await user.keyboard('{Home}');
    expect(editorPane().style.height).toBe(`${MIN_EDITOR_HEIGHT}px`);
    await user.keyboard('{End}');
    expect(editorPane().style.height).toBe(`${COLUMN - MIN_RESULTS_HEIGHT - EDITOR_SPLIT_DIVIDER_HEIGHT}px`);
  });

  it('steps the split from a click, without dragging and without resetting', async () => {
    // The pointer path that is not a drag. Without it the only way to choose a
    // split with a pointer is to hold and move one, which is the thing some
    // people cannot do — and the double-click reaches exactly one position.
    const {user} = await renderReady();
    const smaller = screen.getByRole('button', {name: 'Give the results more room'});
    const larger = screen.getByRole('button', {name: 'Give the editor more room'});

    await user.click(smaller);
    expect(divider()).toHaveAttribute('aria-valuenow', '45');
    await user.click(larger);
    await user.click(larger);
    expect(divider()).toHaveAttribute('aria-valuenow', '55');
    expect(sessionStorage.getItem(`${QUERY_EDITOR_SPLIT_STORAGE_PREFIX}alice`)).toBe('0.55');

    // Pressing a button must not start a drag. Held, not clicked: a click ends
    // with a pointerup, which unbinds any drag the pointerdown began, so the
    // move below could never see one and the assertion would pass regardless.
    fireEvent.pointerDown(smaller, {clientY: 800});
    fireEvent.pointerMove(window, {clientY: 2000});
    expect(divider()).toHaveAttribute('aria-valuenow', '55');
    fireEvent.pointerUp(window);
    // …and two quick steps are two steps, not the band's reset-to-even.
    await user.dblClick(larger);
    expect(divider()).toHaveAttribute('aria-valuenow', '65');
  });

  it('grabbing the divider focuses it, so the keys are reachable from a pointer', async () => {
    // The drag cancels the pointer-down default, which in a browser also
    // cancels the focus a mousedown would have given — leaving the whole
    // keyboard path unreachable for anyone who found the divider by dragging.
    await renderReady();
    expect(divider()).not.toHaveFocus();

    fireEvent.pointerDown(divider(), {clientY: 800});
    expect(divider()).toHaveFocus();
    fireEvent.pointerUp(window);
  });

  it('drops the gesture when it is cancelled, and when the workspace unmounts', async () => {
    const {unmount} = await renderReady();

    // pointercancel fires INSTEAD of pointerup when the browser or OS takes the
    // gesture over; an unbound move handler then resizes on every pointer move.
    fireEvent.pointerDown(divider(), {clientY: 800});
    fireEvent.pointerMove(window, {clientY: 900});
    expect(editorPane().style.height).toBe('600px');
    fireEvent.pointerCancel(window);
    fireEvent.pointerMove(window, {clientY: 1200});
    expect(editorPane().style.height).toBe('600px');

    // And a release arriving after the tree is gone must not persist a split
    // the user was still choosing.
    fireEvent.pointerDown(divider(), {clientY: 800});
    fireEvent.pointerMove(window, {clientY: 700});
    unmount();
    fireEvent.pointerUp(window);
    expect(sessionStorage.getItem(`${QUERY_EDITOR_SPLIT_STORAGE_PREFIX}alice`)).toBe('0.6');
  });

  it('double-click resets to an even split, persists it, and leaves no drag running', async () => {
    const {user} = await renderReady();
    fireEvent.pointerDown(divider(), {clientY: 500});
    fireEvent.pointerMove(window, {clientY: 700});
    fireEvent.pointerUp(window);
    expect(editorPane().style.height).toBe('700px');

    await user.dblClick(divider());

    expect(editorPane().style.height).toBe('500px');
    expect(sessionStorage.getItem(`${QUERY_EDITOR_SPLIT_STORAGE_PREFIX}alice`)).toBe('0.5');
    fireEvent.pointerMove(window, {clientY: 900});
    expect(editorPane().style.height).toBe('500px');
  });

  it('replaces the layout presets rather than sitting beside them', async () => {
    await renderReady();
    // The toolbar really rendered — otherwise every absence below holds because
    // there is no toolbar, not because the control was removed from one.
    expect(screen.getByRole('button', {name: 'Clear query'})).toBeInTheDocument();
    expect(screen.queryByRole('group', {name: 'Editor and results layout'})).not.toBeInTheDocument();
    for (const name of [/split editor and results evenly/i, /grow the editor/i, /grow the results/i]) {
      expect(screen.queryByRole('button', {name})).not.toBeInTheDocument();
    }
  });

  it('measures the column when a narrow session widens past tablet', async () => {
    // The column only exists above `tablet`, so a mount-only measurement finds
    // no element and never runs again: the divider renders, announces a value,
    // and moves nothing — the editor stuck at its floor with no way out.
    mockListSaved.mockResolvedValue(savedListing('Revenue'));
    window.innerWidth = 390;
    const {rerender} = renderWithProviders(
      <NavRailProvider>
        <QueryWorkspace />
      </NavRailProvider>,
      {auth: authenticated('alice')}
    );
    await screen.findByRole('button', {name: 'Run saved query Revenue'});

    window.innerWidth = 1400;
    rerender(
      <NavRailProvider>
        <QueryWorkspace />
      </NavRailProvider>
    );

    await screen.findByRole('separator', {name: 'Resize the editor and results'});
    expect(editorPane().style.height).toBe('500px'); // measured, not the floor
    fireEvent.pointerDown(divider(), {clientY: 800});
    fireEvent.pointerMove(window, {clientY: 900});
    fireEvent.pointerUp(window);
    expect(editorPane().style.height).toBe('600px');
    window.innerWidth = 1024;
  });

  it('renders no divider below tablet', async () => {
    heights.mockRestore();
    mockListSaved.mockResolvedValue(savedListing('Revenue'));
    window.innerWidth = 390;
    renderWithProviders(
      <NavRailProvider>
        <QueryWorkspace />
      </NavRailProvider>,
      {auth: authenticated('alice')}
    );

    await screen.findByRole('button', {name: 'Run saved query Revenue'});
    expect(screen.queryByRole('separator', {name: 'Resize the editor and results'})).not.toBeInTheDocument();
    window.innerWidth = 1024;
  });
});
