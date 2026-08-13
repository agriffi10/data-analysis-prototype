import type {Exploration, ExplorationPresentation, ExplorationQuery, ExplorationSource} from './dataExplorer.types';

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
 * The empty query description: no filters, no expression, no ordering, no grouping.
 *
 * @returns A description that renders `SELECT * FROM <source>` and nothing more.
 */
export function emptyExplorationQuery(): ExplorationQuery {
  return {filters: [], expression: null, ordering: [], grouping: null};
}

/**
 * The empty presentation state. Extended by SPEC-184; nothing here reaches the renderer.
 *
 * `presentation: null` means "unchosen", which is not the same as `'grid'` — it is what
 * lets the viewport decide the opening view (FR-007) without a tab being born knowing how
 * wide the window is.
 *
 * @returns Presentation state that changes no SQL.
 */
export function emptyExplorationPresentation(): ExplorationPresentation {
  return {
    hiddenColumns: [],
    columnOrder: [],
    pinnedColumns: [],
    columnWidths: {},
    presentation: null,
    valuePanelOpen: false,
    recordRowIndex: 0
  };
}

/**
 * A new exploration over a source, with an empty query description (FR-001 AC4).
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
