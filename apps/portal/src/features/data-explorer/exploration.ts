import type {
  Exploration,
  ExplorationPresentation,
  ExplorationQuery,
  ExplorationSource,
  FilterGroup,
  FilterItem,
  FormattingState,
  Grouping,
  QueryHistoryCursor
} from './dataExplorer.types';

// Constructors for the model. Separate from the types so there is one definition of what
// "empty" means — a description built field-by-field at a call site is how two surfaces
// come to disagree about whether `expression` starts as `null` or `''`.

let fallbackSeq = 0;

/**
 * A fresh exploration id. `crypto.randomUUID` exists in the browser and in the Node test
 * runtime; the catch keeps one missing-crypto environment from throwing.
 *
 * @returns A unique id for an exploration or a tab.
 */
export function newExplorationId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    fallbackSeq += 1;
    return `exploration-${fallbackSeq}`;
  }
}

/**
 * Whether a filter item is a group rather than a condition.
 *
 * `Object.hasOwn`, never `in`: a stored document is the one untrusted input this model has, and
 * `in` would also answer for an `items` inherited through the prototype chain.
 *
 * @param item - A top-level item, or one inside a group.
 * @returns True for a group.
 */
export function isFilterGroup(item: FilterItem): item is FilterGroup {
  return Object.hasOwn(item, 'items');
}

/**
 * The empty query description: no filters, no expression, no ordering, no grouping.
 *
 * @returns A description that renders `SELECT * FROM <source>` and nothing more.
 */
export function emptyExplorationQuery(): ExplorationQuery {
  return {filters: [], expression: null, ordering: [], grouping: null};
}

/**
 * The grouping a panel starts from: no columns yet, and `COUNT(*)`.
 *
 * `COUNT(*)` is present by default because a grouping with no aggregate answers nothing —
 * it is a distinct list — and "how many in each" is the question grouping is nearly always
 * asked for. It is removable like any other aggregate.
 *
 * @returns A draft grouping, not yet in grouping mode (it has no columns).
 */
export function emptyGrouping(): Grouping {
  return {columns: [], aggregates: [{fn: 'COUNT', column: '*'}], duplicatesOnly: false, showPercentage: false};
}

/**
 * A tab's empty history: nothing to go back to and nothing to go forward to.
 *
 * @returns A cursor a fresh tab starts with.
 */
export function emptyQueryHistory(): QueryHistoryCursor {
  return {past: [], future: []};
}

/**
 * Formatting as a tab starts: no rules, no type tint, no striping, no transformers.
 *
 * Every default is "off" rather than a sensible-looking preset, because each one changes
 * how a value READS — a number rendered to two decimals is a different number to anyone
 * reading it, and nobody asked for it.
 *
 * @returns Formatting state that changes nothing on screen.
 */
export function emptyFormattingState(): FormattingState {
  return {rules: [], colourByType: false, stripeColumns: [], transformers: {}};
}

/**
 * The empty presentation state. Nothing here reaches the renderer.
 *
 * @returns Presentation state that changes no SQL.
 */
export function emptyExplorationPresentation(): ExplorationPresentation {
  return {
    hiddenColumns: [],
    columnOrder: [],
    pinnedColumns: [],
    columnWidths: {},
    valuePanelOpen: false,
    formatting: emptyFormattingState()
  };
}

/**
 * A new exploration over a source, with an empty query description.
 *
 * @param source - Where the rows come from.
 * @param id - An explicit id; omit for a fresh one.
 * @returns The exploration, ready to render.
 */
export function newExploration(source: ExplorationSource, id: string = newExplorationId()): Exploration {
  return {
    id,
    source,
    query: emptyExplorationQuery(),
    presentation: emptyExplorationPresentation()
  };
}

/**
 * What a tab is called before a user renames it: the table's name, or the `.sql` file's.
 *
 * @param source - The source to label.
 * @returns A display label, never qualified — the rail already says which database.
 */
export function explorationSourceLabel(source: ExplorationSource): string {
  return source.kind === 'table' ? source.table : source.label;
}
