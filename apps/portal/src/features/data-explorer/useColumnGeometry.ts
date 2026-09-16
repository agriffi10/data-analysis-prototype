import {useCallback, useMemo} from 'react';
import {DEFAULT_COLUMN_WIDTH, MAX_COLUMN_WIDTH, MIN_COLUMN_WIDTH} from '../catalog/catalog.constants';
import type {QueryColumn} from '../catalog/catalog.types';
import type {ExplorationPresentation} from './dataExplorer.types';

/** One column as the grid draws it: its identity, its data position and its geometry. */
export type GridColumn = {
  /** The column's name — the geometry key, and what every action below takes. */
  name: string;
  /** Athena/Glue type, shown under the name. */
  type: string;
  /** Position in the row arrays, i.e. the EXECUTION's column order, not the display order. */
  index: number;
  width: number;
  pinned: boolean;
  hidden: boolean;
};

export type UseColumnGeometryResult = {
  /** Visible columns in display order: the pinned block, then the rest. */
  visible: GridColumn[];
  /** Every column in display order, hidden ones included — the Columns panel's list. */
  all: GridColumn[];
  setWidth: (name: string, px: number) => void;
  resetWidth: (name: string) => void;
  toggleHidden: (name: string) => void;
  togglePinned: (name: string) => void;
  /** Shows every hidden column at once — one way back to the result as it arrived. */
  showAll: () => void;
  /** Unpins every pinned column at once; each returns to its place in the display order. */
  unpinAll: () => void;
  /** Moves a column one place within its own block (pinned columns reorder among pinned). */
  move: (name: string, direction: -1 | 1) => void;
  /** Drag-drop: puts `name` where `target` sits. A cross-block drop is refused, not coerced. */
  moveTo: (name: string, target: string) => void;
  /** Null when hiding is allowed, else the reason — rendered through `Button.disabledReason`. */
  hideRefusal: (name: string) => string | null;
  /** Null when the move is allowed, else the reason. */
  moveRefusal: (name: string, direction: -1 | 1) => string | null;
};

export const LAST_COLUMN_REFUSAL = 'The grid needs at least one visible column.';

function block(column: GridColumn): 'pinned' | 'unpinned' {
  return column.pinned ? 'pinned' : 'unpinned';
}

/**
 * Resolves the exploration's presentation against the columns an execution (or the Glue
 * schema) actually reports, and returns the actions that change it.
 *
 * **None of this renders SQL** (the central rule), so every action here is a state
 * write and never an execution — which is why geometry can be as free as it looks.
 *
 * Geometry is keyed by column NAME rather than position, and that is what makes the discard rule
 * true by construction: a width, a pin or a hide belonging to a column the new result set
 * does not contain simply never resolves — it is not applied to whichever column now
 * occupies that position. Stale entries are left in place rather than pruned, because a
 * re-execution that brings the column back should bring its geometry back with it.
 *
 * Two columns sharing a name share their geometry. `SELECT *` over a Glue table cannot
 * produce that, and the aggregates carry distinct aliases.
 *
 * @param columns - The current column set, in the execution's own order.
 * @param presentation - The tab's presentation state.
 * @param onChange - Applies an update to the tab's presentation.
 * @returns The resolved columns and the actions over them.
 */
export function useColumnGeometry(
  columns: QueryColumn[],
  presentation: ExplorationPresentation,
  onChange: (update: (presentation: ExplorationPresentation) => ExplorationPresentation) => void
): UseColumnGeometryResult {
  const {columnOrder, hiddenColumns, pinnedColumns, columnWidths} = presentation;

  const all = useMemo((): GridColumn[] => {
    const resolved = columns.map((column, index): GridColumn => ({
      name: column.name,
      type: column.type,
      index,
      width: columnWidths[column.name] ?? DEFAULT_COLUMN_WIDTH,
      pinned: pinnedColumns.includes(column.name),
      hidden: hiddenColumns.includes(column.name)
    }));

    // Ordering is "named first, in the order named; everything else after, in the order
    // the execution reported it". A column the stored order has never heard of — a new
    // one after a re-execution, or every column the first time — therefore lands
    // somewhere sensible instead of nowhere.
    const rank = new Map(columnOrder.map((name, i) => [name, i]));
    const ordered = resolved
      .map((column, natural) => ({column, natural}))
      .sort((a, b) => {
        const ra = rank.get(a.column.name);
        const rb = rank.get(b.column.name);
        if (ra !== undefined && rb !== undefined) return ra - rb;
        if (ra !== undefined) return -1;
        if (rb !== undefined) return 1;
        return a.natural - b.natural;
      })
      .map(({column}) => column);

    // The pinned block leads, in pin order — but only for columns the stored order has
    // nothing to say about. An earlier version sorted the block by pin order ALONE, which
    // silently overrode every reorder inside it: the ↑/↓ buttons stayed enabled, the live
    // region announced a new position, and nothing moved (found in review).
    const pinnedRank = new Map(pinnedColumns.map((name, i) => [name, i]));
    const pinned = ordered
      .filter((column) => column.pinned)
      .sort((a, b) => {
        const ra = rank.get(a.name);
        const rb = rank.get(b.name);
        if (ra !== undefined && rb !== undefined) return ra - rb;
        if (ra !== undefined) return -1;
        if (rb !== undefined) return 1;
        return (pinnedRank.get(a.name) ?? 0) - (pinnedRank.get(b.name) ?? 0);
      });
    return [...pinned, ...ordered.filter((column) => !column.pinned)];
  }, [columns, columnOrder, hiddenColumns, pinnedColumns, columnWidths]);

  const visible = useMemo(() => all.filter((column) => !column.hidden), [all]);

  const setWidth = useCallback(
    (name: string, px: number) => {
      const clamped = Math.min(MAX_COLUMN_WIDTH, Math.max(MIN_COLUMN_WIDTH, Math.round(px)));
      onChange((p) => ({...p, columnWidths: {...p.columnWidths, [name]: clamped}}));
    },
    [onChange]
  );

  const resetWidth = useCallback(
    (name: string) => {
      onChange((p) => ({
        ...p,
        // Dropped rather than set to the default: an absent entry IS the default, so a
        // reset leaves nothing behind to be restored onto a later column of that name.
        columnWidths: Object.fromEntries(Object.entries(p.columnWidths).filter(([column]) => column !== name))
      }));
    },
    [onChange]
  );

  const hideRefusal = useCallback(
    (name: string): string | null => {
      const column = all.find((c) => c.name === name);
      if (!column || column.hidden) return null;
      return visible.length > 1 ? null : LAST_COLUMN_REFUSAL;
    },
    [all, visible.length]
  );

  const toggleHidden = useCallback(
    (name: string) => {
      if (hideRefusal(name) !== null) return;
      onChange((p) => ({
        ...p,
        hiddenColumns: p.hiddenColumns.includes(name)
          ? p.hiddenColumns.filter((c) => c !== name)
          : [...p.hiddenColumns, name]
      }));
    },
    [hideRefusal, onChange]
  );

  const togglePinned = useCallback(
    (name: string) => {
      onChange((p) => ({
        ...p,
        pinnedColumns: p.pinnedColumns.includes(name)
          ? p.pinnedColumns.filter((c) => c !== name)
          : [...p.pinnedColumns, name]
      }));
    },
    [onChange]
  );

  const showAll = useCallback(() => onChange((p) => ({...p, hiddenColumns: []})), [onChange]);
  const unpinAll = useCallback(() => onChange((p) => ({...p, pinnedColumns: []})), [onChange]);

  // Writes the resolved display order back whole. The stored order is then explicit for
  // every column present, which is what keeps a second move predictable.
  const writeOrder = useCallback((names: string[]) => onChange((p) => ({...p, columnOrder: names})), [onChange]);

  const moveRefusal = useCallback(
    (name: string, direction: -1 | 1): string | null => {
      const column = all.find((c) => c.name === name);
      if (!column) return null;
      const siblings = all.filter((c) => block(c) === block(column));
      const at = siblings.findIndex((c) => c.name === name);
      const to = at + direction;
      if (to >= 0 && to < siblings.length) return null;
      const where = column.pinned ? ' of the pinned columns' : '';
      return direction === -1 ? `“${name}” is already first${where}.` : `“${name}” is already last${where}.`;
    },
    [all]
  );

  const move = useCallback(
    (name: string, direction: -1 | 1) => {
      if (moveRefusal(name, direction) !== null) return;
      const column = all.find((c) => c.name === name);
      if (!column) return;
      const siblings = all.filter((c) => block(c) === block(column));
      const at = siblings.findIndex((c) => c.name === name);
      const swapped = [...siblings];
      [swapped[at], swapped[at + direction]] = [swapped[at + direction], swapped[at]];
      const others = all.filter((c) => block(c) !== block(column));
      writeOrder(
        column.pinned ? [...swapped, ...others].map((c) => c.name) : [...others, ...swapped].map((c) => c.name)
      );
    },
    [all, moveRefusal, writeOrder]
  );

  const moveTo = useCallback(
    (name: string, target: string) => {
      const column = all.find((c) => c.name === name);
      const onto = all.find((c) => c.name === target);
      // A cross-block drop is REFUSED rather than read as "pin this too": pinning is a
      // deliberate act with its own control, and inferring it from where a drag ended is
      // a mutation the user did not ask for.
      if (!column || !onto || column.name === onto.name || block(column) !== block(onto)) return;
      const siblings = all.filter((c) => block(c) === block(column)).map((c) => c.name);
      // Dropped to the RIGHT, the column lands after the target; to the left, before it.
      // Splicing at the target's post-removal index does the left case only — a one-place
      // rightward drag was a no-op, which is half of drag-reorder (found in review).
      const rightward = siblings.indexOf(name) < siblings.indexOf(target);
      const without = siblings.filter((n) => n !== name);
      const at = without.indexOf(target) + (rightward ? 1 : 0);
      const reordered = [...without.slice(0, at), name, ...without.slice(at)];
      const others = all.filter((c) => block(c) !== block(column)).map((c) => c.name);
      writeOrder(column.pinned ? [...reordered, ...others] : [...others, ...reordered]);
    },
    [all, writeOrder]
  );

  return {
    visible,
    all,
    setWidth,
    resetWidth,
    toggleHidden,
    togglePinned,
    showAll,
    unpinAll,
    move,
    moveTo,
    hideRefusal,
    moveRefusal
  };
}
