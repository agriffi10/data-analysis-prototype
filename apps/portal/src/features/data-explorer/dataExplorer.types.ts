import type {SavedQueryLink} from '../saved-queries/savedQueries.types';

// The exploration model. An exploration is a SOURCE plus a QUERY
// DESCRIPTION plus PRESENTATION STATE, and the split is the feature's central rule: the
// first two determine the SQL, the third never does. They are three separate fields
// rather than one flattened bag precisely so `renderExplorationSql`'s parameter list can
// exclude one of them — a function that cannot reach presentation cannot be made to
// depend on it by a later edit.

/**
 * Where an exploration's rows come from.
 *
 * A discriminated union from the outset, with only the `table` arm reachable until
 * A saved `.sql` file cannot be reverse-engineered into a table plus filters
 * without a SQL parser, so a loaded file is a SOURCE rather than a view state — and
 * filters, ordering and grouping must compose over either arm without knowing which.
 * Retrofitting the union later would have touched every call site in between.
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
  /** Defaults to `'string'`. The filter picks it from the column's Glue/Athena type. */
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
  /** `HAVING COUNT(*) > 1` — the grouped rows that occur more than once. */
  duplicatesOnly: boolean;
  /**
   * Whether the grid shows each grouped row's share of the first aggregate's total.
   *
   * Presentation in every sense except where it lives: it is computed in the browser from
   * rows already fetched and renders NO SQL. It rides here because it is meaningless
   * without the grouping it describes — a percentage of nothing is not a column — and
   * because a grouping restored from a document must restore whole.
   */
  showPercentage: boolean;
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
 * The aggregates the Calc panel offers over a cell selection.
 *
 * Named apart from `AggregateFunction` above, and the difference is the whole point of
 * the spec: that one is a `GROUP BY` clause rendered into SQL and billed, this one runs in
 * the browser over the cells the user has selected — which exist nowhere else.
 */
export type CalcFunction = 'count' | 'countDistinct' | 'countNulls' | 'sum' | 'avg' | 'min' | 'max' | 'median' | 'mode';

export type CalcPanelState = {
  functions: CalcFunction[];
  /** Numeric-only aggregation when false. */
  includeStrings: boolean;
};

export type CalcResult = {
  fn: CalcFunction;
  /** Already formatted for display; `CALC_NO_VALUE` where the function has no answer. */
  value: string;
  /** Cells excluded as non-numeric; surfaced beside the value. */
  skipped: number;
};

/** How the current page's rows are drawn. None of these render SQL. */
export type GridPresentation = 'grid' | 'record' | 'text';

/**
 * A colour a rule may paint text in.
 *
 * A bounded set of design tokens rather than the spec's free-form `string`, and the
 * narrowing is what makes FR-002 AC8 assertable at all: "every pairing meets contrast
 * requirements" is not a claim anyone can make about a colour picker. Every token here
 * clears 4.5:1 against every surface it can land on — `formatting.test.ts` recomputes that
 * from the token values rather than restating it, and `warning` is absent because it does
 * NOT (4.49:1 on `accent-soft`).
 */
export type ColourToken = 'text' | 'text-2' | 'accent-text' | 'success' | 'danger';

/** A colour a rule may paint a cell's background in — the soft tints, for the same reason. */
export type SurfaceToken = 'accent-soft' | 'success-soft' | 'warning-soft' | 'danger-soft';

export type ColourOperator = '=' | '<>' | '>' | '>=' | '<' | '<=' | 'like' | 'ilike' | 'regex';

/**
 * What a matching rule paints.
 *
 * Beyond the spec's Data Model, which carries only `column?` and reads an absent column as
 * "across the row". That conflates two independent choices — what a rule TESTS and what it
 * PAINTS — and leaves the most ordinary rule of all inexpressible: colour the whole row
 * wherever `status` is `failed`. One optional field separates them, on the filter's
 * precedent for `valueKind`.
 */
export type ColourScope = 'cell' | 'row';

export type ColourRule = {
  id: string;
  /** The column the condition is tested against; **undefined tests every cell in the row**. */
  column?: string;
  /** Whether a match paints the matching cell or the whole row. Defaults to `'cell'`. */
  scope?: ColourScope;
  operator: ColourOperator;
  value: string;
  foreground?: ColourToken;
  background?: SurfaceToken;
  /**
   * Numeric gradient across [min, max] instead of a binary match.
   *
   * Present means the operator and value are unused: the cell's own number decides the
   * shade. A non-numeric cell is left UNSTYLED rather than clamped (FR-002 AC4) — clamping
   * would paint a text cell the colour of the minimum, which reads as a measurement.
   */
  gradient?: {min: number; max: number; from: SurfaceToken; to: SurfaceToken};
};

/**
 * A per-column rendering change.
 *
 * **Rendering only.** The raw value continues to drive filtering, colouring, Calc and copy
 * — a transformed value reaching any of those is a silent wrong answer, which is why the
 * transform happens at the cell and nowhere upstream of it.
 */
export type Transformer =
  | {kind: 'numeric'; precision: number; lenient: boolean}
  | {kind: 'binary'; encoding: 'hex' | 'base64'; maxLength: number}
  | {kind: 'url'; template: string};

/** Everything presentation adds, and none of it renders SQL. */
export type FormattingState = {
  /** Evaluated in order; a later match overrides an earlier one **per property**. */
  rules: ColourRule[];
  colourByType: boolean;
  /** Consecutive rows equal in ALL of these form one band. Empty means striping is off. */
  stripeColumns: string[];
  /** Keyed by column name, like the geometry beside it. */
  transformers: Record<string, Transformer>;
};

/** One cell, addressed by its row's index within the CURRENT PAGE and its column's name. */
export type CellRef = {row: number; column: string};

/** An inclusive rectangle of cells; `from` is where the gesture started. */
export type CellRange = {from: CellRef; to: CellRef};

/**
 * The grid's cursor and selection.
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
 * Everything that renders NOTHING.
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
  /** Colours, striping and transformers. Restored whole or not at all. */
  formatting: FormattingState;
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
 * This tab's undo/redo over its own query DESCRIPTIONS.
 *
 * Descriptions, never result sets: a description is a few hundred bytes and re-renders to
 * the same SQL, so stepping back resolves to the execution already cached (
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
   * The `.sql` file this tab was last saved to.
   *
   * What a re-save replaces, and the only reason `isLinkedSavedQuery` can ever be true
   * here — nothing else in this feature mints a link, because loading a `.sql` file as a
   * source is deferred. Optional because a tab that has never been saved has none, and
   * because a document written before these fields existed carries none either.
   *
   * It does NOT rename the tab. A Query workspace tab IS its buffer, so a save renames it;
   * an exploration tab is named for the source it is exploring, which a save does not change.
   */
  savedQuery?: SavedQueryLink;
  /**
   * Bytes scanned per DISTINCT execution this tab has run, keyed by execution id.
   *
   * Keyed rather than summed because that is what makes FR-007's "a cache hit adds
   * nothing" true by construction: a re-rendered identical SQL resolves to the execution
   * id already recorded, so re-adding it changes no total. A running sum would need to
   * detect a cache hit, and a detector can be wrong.
   */
  scannedByExecution: Record<string, number>;
  /** Back/forward over this tab's previous query descriptions. */
  history: QueryHistoryCursor;
};

export type ExplorationTabsState = {
  version: 1;
  /** Display order = creation order. May be empty — this surface has a legal zero-tab state. */
  tabs: ExplorationTab[];
  /** Must reference an existing tab, or `''` when there are none. */
  activeTabId: string;
};

/**
 * A clipboard shape.
 *
 * `tsv` is what Ctrl/Cmd+C uses and what a spreadsheet expects from a paste; the other five
 * exist because a selection's next destination is as often a document, a script or an API
 * fixture as it is a sheet.
 */
export type CopyFormat = 'tsv' | 'csv' | 'json' | 'markdown' | 'sql' | 'xml';

export type CopyOptions = {
  format: CopyFormat;
  includeHeaders: boolean;
  /** Prepends the grid's own absolute row numbers, which are the PAGE's, not the result's. */
  includeRowNumbers: boolean;
  /**
   * Quote every value in the formats that have no other way to say it.
   *
   * Inert in JSON, SQL and XML, whose values are already delimited by the format — the
   * dialog disables the control there rather than offering one that does nothing.
   */
  quoteValues: boolean;
};
