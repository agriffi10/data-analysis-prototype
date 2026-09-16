import {Menu, type MenuItem} from '../../components/Menu';

export type ExplorationOptionsMenuProps = {
  /** Open the Order-and-filter settings dialog. */
  onOrderAndFilter: () => void;
  /** Clear the whole query. Its label reports what there is to clear. */
  clearAllLabel: string;
  onClearAll: () => void;
  clearAllRefusal?: string;
  /** Filter to the selected cell's value. */
  onFilterByCell: () => void;
  filterByCellRefusal?: string;
  /** Panels and dialogs the menu opens, each already knowing its own open state. */
  onColumns: () => void;
  onColours: () => void;
  onTransformers: () => void;
  onCopy: () => void;
  onExport: () => void;
  /** Toggles, whose current state the label reports rather than a checkmark. */
  valueOpen: boolean;
  onToggleValue: () => void;
  calcOpen: boolean;
  onToggleCalc: () => void;
  groupingOpen: boolean;
  onToggleGrouping: () => void;
  /** Refusals, carried through so a moved control keeps the reason it had on the toolbar. */
  copyRefusal?: string;
  exportRefusal?: string;
  /** `Save as query` follows the `query` flag; REMOVED rather than refused when it is off. */
  savedQueriesEnabled: boolean;
  onSaveQuery: () => void;
  saveRefusal?: string;
  /**
   * `Save as query`'s sibling: one writes a `.sql` file into a space, the other writes a view
   * into the catalog. It sits HERE rather than in the source picker's Create section, because a
   * view is made from a statement and the picker has none — the statement is the thing in front
   * of the user on this screen.
   *
   * Follows the **`query`** flag, like the sibling above and like `Create view` on the Query
   * workspace's own toolbar. Creating a Glue view is a Query capability wherever the button
   * lives, and with the flag off the app deliberately has no way to make one — an exemption
   * here would have handed that back through a different door.
   */
  createViewEnabled: boolean;
  onCreateView: () => void;
  createViewRefusal?: string;
};

/**
 * The Data Explorer's overflow menu: every action the toolbar used to spell out.
 *
 * **THE SPLIT IS NOW "IS IT A DESTINATION OR A GESTURE", NOT "DOES IT CHANGE THE ROWS".**
 * What stays on the bar is undo/redo and the view switch — the two things whose current
 * state has to be readable, and usable repeatedly, without opening anything. Everything
 * that opens a dialog, applies a change and is done goes in here.
 *
 * This REVERSES the earlier rule, deliberately and on user feedback rather than on a fresh
 * opinion. The old split kept the query-changing controls — Order and filter, Clear, Filter
 * by this value — on the bar on the grounds that they are what the screen is for. The
 * complaint was that the bar still reads as a row of buttons; the measurement behind the
 * original trim (thirteen controls wrapping onto three lines at laptop width) argued for a
 * shorter bar, and this shortens it further rather than working against it. The cost is one
 * extra click on three actions that change the rows, which is the thing to weigh if this is
 * ever revisited.
 *
 * Grouping keeps its place here for its original reason: opening it is free, what it applies
 * is a `GROUP BY`, and a user reaches for it far less often than for a filter.
 *
 * **A REFUSAL SURVIVES THE MOVE.** Copy, Export and Save as query were `aria-disabled` with a
 * reason on the toolbar, and an item that merely greyed out inside a menu would be strictly
 * worse than the button it replaced — the reason is now further from the user, not closer.
 * They ride `MenuItem.disabledReason`, added for this.
 *
 * The three toggles say their state in the LABEL (`Hide the value panel`) rather than through
 * `aria-pressed` on a `menuitem`, whose role does not carry a pressed state. A `menuitemcheckbox`
 * would, and is the wrong shape: these open panels rather than setting an option, and two of
 * them are the same gesture as clicking their panel's own close button.
 *
 * @example
 * <ExplorationOptionsMenu onColumns={openColumns} calcOpen={calcOpen} … />
 */
export function ExplorationOptionsMenu({
  onOrderAndFilter,
  clearAllLabel,
  onClearAll,
  clearAllRefusal,
  onFilterByCell,
  filterByCellRefusal,
  onColumns,
  onColours,
  onTransformers,
  onCopy,
  onExport,
  valueOpen,
  onToggleValue,
  calcOpen,
  onToggleCalc,
  groupingOpen,
  onToggleGrouping,
  copyRefusal,
  exportRefusal,
  savedQueriesEnabled,
  onSaveQuery,
  saveRefusal,
  createViewEnabled,
  onCreateView,
  createViewRefusal
}: ExplorationOptionsMenuProps) {
  const items: MenuItem[] = [
    // The query-changing group, first: these are what the screen is for, so they sit above
    // the presentation and export groups rather than being appended to them.
    {kind: 'action', label: 'Order and filter', onSelect: onOrderAndFilter},
    {kind: 'action', label: clearAllLabel, onSelect: onClearAll, disabledReason: clearAllRefusal},
    {kind: 'action', label: 'Filter by this value', onSelect: onFilterByCell, disabledReason: filterByCellRefusal},
    {kind: 'separator'},
    {kind: 'action', label: 'Columns', onSelect: onColumns},
    {kind: 'action', label: 'Colors', onSelect: onColours},
    {kind: 'action', label: 'Transformers', onSelect: onTransformers},
    {kind: 'separator'},
    {kind: 'action', label: valueOpen ? 'Hide the value panel' : 'Value', onSelect: onToggleValue},
    {kind: 'action', label: calcOpen ? 'Hide Calc' : 'Calc', onSelect: onToggleCalc},
    {kind: 'action', label: groupingOpen ? 'Hide Grouping' : 'Grouping', onSelect: onToggleGrouping},
    {kind: 'separator'},
    {kind: 'action', label: 'Copy…', onSelect: onCopy, disabledReason: copyRefusal},
    {kind: 'action', label: 'Save results to my files', onSelect: onExport, disabledReason: exportRefusal},
    // REMOVED rather than refused with the flag off, because a reason cannot explain a state
    // the user has no way to change. Gated by `query`, not `dataExplorer`: the store is the
    // Query workspace's. See `gatedSurfaces.ts`.
    ...(savedQueriesEnabled
      ? ([{kind: 'action', label: 'Save as query', onSelect: onSaveQuery, disabledReason: saveRefusal}] as MenuItem[])
      : []),
    ...(createViewEnabled
      ? ([
          {kind: 'action', label: 'Create view…', onSelect: onCreateView, disabledReason: createViewRefusal}
        ] as MenuItem[])
      : [])
  ];

  return (
    <Menu
      ariaLabel="Exploration options"
      align="left"
      items={items}
      trigger={({open, toggle, ref, menuId}) => (
        <button
          ref={ref}
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={open ? menuId : undefined}
          onClick={toggle}
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-sm font-medium text-text hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          Options
          <span aria-hidden="true">▾</span>
        </button>
      )}
    />
  );
}
