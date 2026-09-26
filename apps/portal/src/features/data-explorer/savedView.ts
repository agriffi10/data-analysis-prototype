import {exceedsAthenaQueryLimit} from '../../lib/athenaLimit';
import {readStrictPresentation, readStrictQuery} from './explorationTabs';
import {renderExplorationSql} from './renderExplorationSql';
import type {
  AwaitingRun,
  ColourOperator,
  Exploration,
  ExplorationPresentation,
  ExplorationQuery
} from './dataExplorer.types';

/**
 * What a saved `.sql` file's view line records: enough to rebuild the tab it was saved from.
 *
 * The source is a table by database and name, never a space id: `personal` names a different
 * space for every user who opens the file, so the space is found again by database when it opens.
 */
export type SavedView = {
  source: {database: string; table: string};
  query: ExplorationQuery;
  presentation: Omit<ExplorationPresentation, 'valuePanelOpen' | 'recordRowIndex'>;
};

/** Colors operators that compile an author-typed pattern into a backtracking expression. */
const PATTERN_OPERATORS: ReadonlySet<ColourOperator> = new Set(['regex', 'like', 'ilike']);

/**
 * The view a save records, or null for a tab whose source is a statement rather than a table.
 *
 * A statement source is left out on purpose: restoring one would re-run SQL taken from a file.
 *
 * @param exploration - The tab's exploration, as it was when the user chose to save.
 * @returns The view, or null.
 */
export function buildSavedView(exploration: Exploration): SavedView | null {
  const {source, query, presentation} = exploration;
  if (source.kind !== 'table') return null;
  const kept: Partial<ExplorationPresentation> = {...presentation};
  delete kept.valuePanelOpen;
  delete kept.recordRowIndex;
  return {
    source: {database: source.database, table: source.table},
    query,
    presentation: kept as SavedView['presentation']
  };
}

/**
 * Reads a view line's payload, all or nothing.
 *
 * Strict at every step — the shape, the query, the presentation — and then rendered, because a
 * description the validators accept can still be one the renderer refuses, or one too long for
 * Athena. Any failure is null: a view is never partly applied.
 *
 * @param payload - The decoded payload, or undefined when it did not decode.
 * @returns The view, or null.
 */
export function readSavedView(payload: unknown): SavedView | null {
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) return null;
  const stored = payload as Record<string, unknown>;
  const source = stored.source as Record<string, unknown> | null | undefined;
  if (typeof source?.database !== 'string' || typeof source.table !== 'string') return null;
  if (!source.database || !source.table || Object.keys(stored).length !== 3) return null;
  const query = readStrictQuery(stored.query);
  const presentation = readStrictPresentation(stored.presentation);
  if (!query || !presentation) return null;
  try {
    const sql = renderExplorationSql(
      {kind: 'table', spaceId: '', database: source.database, table: source.table},
      query
    );
    if (exceedsAthenaQueryLimit(sql)) return null;
  } catch {
    return null;
  }
  return {source: {database: source.database, table: source.table}, query, presentation};
}

/**
 * Takes out what acts on text a view's author typed, for a view read from a shared space.
 *
 * A link column turns cell values into links to wherever the author's template points, and a
 * pattern rule runs the author's pattern against every cell on the page. Neither is safe to take
 * on trust from a file any member can write. A gradient rule ignores its operator, so it stays.
 *
 * @param presentation - The view's presentation.
 * @returns The presentation without them, and how many of each were taken out.
 */
export function stripForSharedFolder(presentation: SavedView['presentation']): {
  presentation: SavedView['presentation'];
  leftOut: {links: number; patterns: number};
} {
  const {formatting} = presentation;
  const transformers = Object.fromEntries(
    Object.entries(formatting.transformers).filter(([, transformer]) => transformer.kind !== 'url')
  );
  const rules = formatting.rules.filter((rule) => rule.gradient !== undefined || !PATTERN_OPERATORS.has(rule.operator));
  return {
    presentation: {...presentation, formatting: {...formatting, transformers, rules}},
    leftOut: {
      links: Object.keys(formatting.transformers).length - Object.keys(transformers).length,
      patterns: formatting.rules.length - rules.length
    }
  };
}

/** What a held tab says: where its file came from, and that its SQL is there to be checked. */
export function heldText(space: string): string {
  return `This view was saved in ${space || 'a shared space'}, where any member can change it. Check its Generated SQL, then run it.`;
}

/** The note under a held tab naming what was not restored, or null when nothing was left out. */
export function leftOutNote(leftOut: AwaitingRun['leftOut']): string | null {
  const plural = (n: number, noun: string) => `${n} ${noun}${n === 1 ? '' : 's'}`;
  const parts = [
    leftOut.links > 0 ? plural(leftOut.links, 'link column') : null,
    leftOut.patterns > 0 ? plural(leftOut.patterns, 'pattern color rule') : null
  ].filter((part): part is string => part !== null);
  return parts.length > 0 ? `Left out: ${parts.join(', ')}.` : null;
}

/** Why a saved query did not reopen as a view, as the dialog says it. */
export const SAVED_VIEW_REFUSALS = {
  none: (name: string) => `“${name}” has no Data Explorer view saved in it.`,
  edited: (name: string) =>
    `“${name}” has been edited since it was saved from the Data Explorer, so its view no longer describes it.`,
  newer: (name: string) => `“${name}” was saved by a newer version of Data Quarry.`,
  unreadable: (name: string) => `“${name}” carries a view that can’t be read.`,
  tooLarge: (name: string) => `“${name}” is too large to open as a view.`,
  noAccess: (database: string) => `You don’t have access to ${database}, the database this view explores.`
} as const;
