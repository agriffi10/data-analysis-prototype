// The exploration model (SPEC-178 FR-001). An exploration is a SOURCE plus a QUERY
// DESCRIPTION plus PRESENTATION STATE, and the split is the feature's central rule: the
// first two determine the SQL, the third never does. They are three separate fields
// rather than one flattened bag precisely so `renderExplorationSql`'s parameter list can
// exclude one of them — a function that cannot reach presentation cannot be made to
// depend on it by a later edit.

/**
 * Where an exploration's rows come from.
 *
 * A discriminated union from the outset, with only the `table` arm reachable until
 * SPEC-183. A saved `.sql` file cannot be reverse-engineered into a table plus filters
 * without a SQL parser, so a loaded file is a SOURCE rather than a view state — and
 * filters, ordering and grouping must compose over either arm without knowing which.
 * Retrofitting the union at SPEC-183 would have touched every spec in between.
 */
export type ExplorationSource =
  | {
      kind: 'table';
      spaceId: string;
      database: string;
      table: string;
    }
  | {
      kind: 'sql';
      /** The file's SQL, rendered as a subquery. */
      body: string;
      /** What the tab is called — the file's name, not part of the SQL. */
      label: string;
    };

export type FilterOperator = '=' | '<>' | '>' | '>=' | '<' | '<=' | 'isNull' | 'isNotNull';

/**
 * How a filter value is rendered into SQL.
 *
 * Athena is Trino and Trino does not coerce: `WHERE "qty" > '5'` against a `bigint` is a
 * query-time error, not a comparison. So a value the user is filtering a numeric column
 * by must reach the SQL bare, and `'number'` says so. It carries **no injection surface**:
 * the renderer admits it only through a bounded charset AND `Number.isFinite`, so there is
 * nothing left to escape. A value that fails either gate is refused rather than quoted as
 * a fallback, because falling back would reintroduce the type error this exists to prevent.
 *
 * `'string'` is the default and everything else goes through `sqlLiteral`.
 */
export type FilterValueKind = 'string' | 'number';

export type ColumnFilter = {
  column: string;
  operator: FilterOperator;
  /** Absent for `isNull` / `isNotNull`; a raw cell value otherwise, quoted at render time. */
  value?: string;
  /** Defaults to `'string'`. SPEC-181 picks it from the column's Glue/Athena type. */
  valueKind?: FilterValueKind;
};

export type SortEntry = {
  column: string;
  direction: 'asc' | 'desc';
  /** 0-based; lower sorts first. */
  priority: number;
};

export type AggregateFunction = 'COUNT' | 'SUM' | 'AVG' | 'MIN' | 'MAX';

export type GroupingAggregate = {
  fn: AggregateFunction;
  /** `'*'` is legal for COUNT alone. */
  column: string | '*';
};

export type Grouping = {
  columns: string[];
  aggregates: GroupingAggregate[];
};

/** Everything that renders SQL. Nothing else may. */
export type ExplorationQuery = {
  filters: ColumnFilter[];
  /** User-authored WHERE fragment, passed through verbatim (FR-005). */
  expression: string | null;
  ordering: SortEntry[];
  grouping: Grouping | null;
};

/** How the current page's rows are drawn (SPEC-180). None of these render SQL. */
export type GridPresentation = 'grid' | 'record' | 'text';

/** One cell, addressed by its row's index within the CURRENT PAGE and its column's name. */
export type CellRef = {row: number; column: string};

/** An inclusive rectangle of cells; `from` is where the gesture started. */
export type CellRange = {from: CellRef; to: CellRef};

/**
 * The grid's cursor and selection (SPEC-180 FR-002).
 *
 * Named `CellSelection` rather than the spec's `Selection`: that name is a DOM global
 * (`window.getSelection()`), and a same-named export shadows it wherever both are in
 * scope — in a file that also reads the real one to copy text, silently.
 */
export type CellSelection = {
  /** The focused cell; always present when the grid has rows. */
  cursor: CellRef;
  /** Rectangles and discontiguous cells, in selection order. */
  ranges: CellRange[];
};

/**
 * Everything that renders NOTHING. Extended by SPEC-180 and SPEC-184.
 *
 * Changing any field here must never mint an execution: these gestures cost nothing and
 * apply instantly, which is only true because the renderer cannot see this type.
 *
 * Column geometry is keyed by column NAME, not by position: it outlives the execution it
 * was set on (a filter change is a new execution over the same columns), and a width that
 * followed a POSITION would land on whatever column moved into it after a re-order or a
 * grouping change (FR-006 AC3). That is also why it is not `features/catalog/`'s
 * `useColumnWidths`, which is index-keyed, per-execution and in-memory.
 */
export type ExplorationPresentation = {
  hiddenColumns: string[];
  columnOrder: string[];
  pinnedColumns: string[];
  columnWidths: Record<string, number>;
  /**
   * The chosen presentation, or **null for "the user has not chosen"**.
   *
   * Null is what makes FR-007's mobile default expressible: below `tablet` an unchosen
   * tab opens in Record and above it in Grid, while a tab whose user HAS chosen keeps that
   * choice at every width. A non-null default would have to be picked when the tab is
   * created — by `useExplorationTabs`, which has no business reading the viewport.
   */
  presentation: GridPresentation | null;
  valuePanelOpen: boolean;
  /** The Record view's focused row index within the current page. */
  recordRowIndex: number;
};

export type Exploration = {
  id: string;
  source: ExplorationSource;
  query: ExplorationQuery;
  presentation: ExplorationPresentation;
};

/** What one Athena execution actually cost. Reported after the fact — never predicted. */
export type ExecutionCost = {
  bytesScanned: number;
  engineMillis: number;
};

/**
 * This tab's undo/redo over its own query DESCRIPTIONS (SPEC-181 FR-006).
 *
 * Descriptions, never result sets: a description is a few hundred bytes and re-renders to
 * the same SQL, so stepping back resolves to the execution already cached (SPEC-178
 * FR-006) rather than to rows this would otherwise have to hold. It rides in the tab, so
 * it is per tab and lives exactly as long as the session does.
 */
export type QueryHistoryCursor = {
  /** Previous descriptions, oldest first, capped at EXPLORER_FILTER_HISTORY_MAX. */
  past: ExplorationQuery[];
  /** Descriptions stepped back past, for forward navigation. */
  future: ExplorationQuery[];
};

/** One Data Explorer tab: a label and the exploration it owns. */
export type ExplorationTab = {
  /** Stable unique id (crypto.randomUUID()); not the label. */
  id: string;
  label: string;
  exploration: Exploration;
  /**
   * Bytes scanned per DISTINCT execution this tab has run, keyed by execution id.
   *
   * Keyed rather than summed because that is what makes FR-007's "a cache hit adds
   * nothing" true by construction: a re-rendered identical SQL resolves to the execution
   * id already recorded, so re-adding it changes no total. A running sum would need to
   * detect a cache hit, and a detector can be wrong.
   */
  scannedByExecution: Record<string, number>;
  /** Back/forward over this tab's previous query descriptions (SPEC-181 FR-006). */
  history: QueryHistoryCursor;
};

export type ExplorationTabsState = {
  version: 1;
  /** Display order = creation order. May be empty — this surface has a legal zero-tab state. */
  tabs: ExplorationTab[];
  /** Must reference an existing tab, or `''` when there are none. */
  activeTabId: string;
};
