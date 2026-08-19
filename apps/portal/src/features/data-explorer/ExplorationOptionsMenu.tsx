import {Menu, type MenuItem} from '../../components/Menu';

export type ExplorationOptionsMenuProps = {
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
 * The Data Explorer's overflow menu: everything the toolbar used to spell out that does not
 * change **which rows** are on screen.
 *
 * **THE SPLIT IS "DOES THIS CHANGE THE ROWS", NOT "IS THIS IMPORTANT".** What stays on the bar
 * is the query itself — undo/redo, Order and filter, Clear, Filter by this value — plus the
 * view switch, because that is the one control whose current setting has to be readable
 * without opening anything. What moves in either changes how the rows LOOK (Columns, Colours,
 * Transformers), inspects what is already there without issuing anything (Value, Calc), or
 * leaves the page with it (Copy…, Export, Save as query). Grouping is the awkward one: opening
 * it is free but what it applies is a `GROUP BY`, and it sits here because a user reaches for
 * it far less often than for a filter.
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
    {kind: 'action', label: 'Columns', onSelect: onColumns},
    {kind: 'action', label: 'Colours', onSelect: onColours},
    {kind: 'action', label: 'Transformers', onSelect: onTransformers},
    {kind: 'separator'},
    {kind: 'action', label: valueOpen ? 'Hide the value panel' : 'Value', onSelect: onToggleValue},
    {kind: 'action', label: calcOpen ? 'Hide Calc' : 'Calc', onSelect: onToggleCalc},
    {kind: 'action', label: groupingOpen ? 'Hide Grouping' : 'Grouping', onSelect: onToggleGrouping},
    {kind: 'separator'},
    {kind: 'action', label: 'Copy…', onSelect: onCopy, disabledReason: copyRefusal},
    {kind: 'action', label: 'Export', onSelect: onExport, disabledReason: exportRefusal},
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
