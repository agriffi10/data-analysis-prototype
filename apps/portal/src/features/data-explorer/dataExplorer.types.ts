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
 * by must reach the SQL bare, and `'number'` says so. It carries **no injection surface**
 * — the renderer admits only `[-+]?digits[.digits][e±digits]`, so there is nothing left
 * to escape; a value that fails that check is refused rather than quoted as a fallback,
 * because falling back would reintroduce the type error this exists to prevent.
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

/**
 * Everything that renders NOTHING. Extended by SPEC-180 and SPEC-184.
 *
 * Changing any field here must never mint an execution: these gestures cost nothing and
 * apply instantly, which is only true because the renderer cannot see this type.
 */
export type ExplorationPresentation = {
  hiddenColumns: string[];
  columnOrder: string[];
  pinnedColumns: string[];
  columnWidths: Record<string, number>;
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
};

export type ExplorationTabsState = {
  version: 1;
  /** Display order = creation order; always length >= 1. */
  tabs: ExplorationTab[];
  /** Must reference an existing tab. */
  activeTabId: string;
  /** Monotonic per-session counter for blank "Exploration N" tabs only. */
  nextExplorationNumber: number;
};
