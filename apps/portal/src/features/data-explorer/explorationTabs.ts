import {
  BINARY_TRANSFORMER_MAX_LENGTH,
  EXPLORATION_TABS_STORAGE_PREFIX,
  EXPLORER_FILTER_HISTORY_MAX,
  FORMATTING_BACKGROUNDS,
  FORMATTING_FOREGROUNDS,
  NUMERIC_TRANSFORMER_MAX_PRECISION
} from './dataExplorer.constants';
import {emptyExplorationPresentation, emptyFormattingState} from './exploration';
import type {
  ExplorationPresentation,
  ExplorationQuery,
  ExplorationTab,
  ExplorationTabsState,
  FormattingState,
  QueryHistoryCursor
} from './dataExplorer.types';
import type {SavedQueryLink} from '../saved-queries/savedQueries.types';

// Per-user, current-session persistence of the Data Explorer's tabs. All access goes
// through this wrapper so a disabled or quota-exceeded sessionStorage degrades to "not
// persisted" rather than crashing the page, and an empty username (the dev-unauth path)
// is a no-op. The split mirrors `features/query/queryTabs.ts`, which is the precedent
// this whole model follows.

function tabsKey(username: string): string | null {
  if (!username) return null;
  return `${EXPLORATION_TABS_STORAGE_PREFIX}${username}`;
}

/**
 * A brand-new session: no tabs at all.
 *
 * Deliberately unlike `initialTabsState()` in the Query workspace, which seeds "Query 1"
 * with boilerplate SQL. An exploration cannot exist without a source, and there is no
 * table to guess — SPEC-179's empty state asks the user to pick one.
 *
 * @returns An empty, valid tabs state.
 */
export function initialExplorationTabsState(): ExplorationTabsState {
  return {version: 1, tabs: [], activeTabId: ''};
}

function isValidSource(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  const source = value as Record<string, unknown>;
  if (source.kind === 'table') {
    return (
      typeof source.spaceId === 'string' && typeof source.database === 'string' && typeof source.table === 'string'
    );
  }
  if (source.kind === 'sql') {
    return typeof source.body === 'string' && typeof source.label === 'string';
  }
  return false;
}

// A stored document is the ONE untrusted input this model has, and "well-formed enough to
// restore" is not the same as "renderable". These check the fields the renderer branches
// on, because a filter with an unrecognised operator renders `"a" undefined 'x'` — invalid
// SQL, sent to StartQueryExecution rather than refused — and a `grouping` of `{}` throws a
// raw TypeError out of the renderer instead of an ExplorationRenderError.
const FILTER_OPERATORS = new Set(['=', '<>', '>', '>=', '<', '<=', 'isNull', 'isNotNull']);
const AGGREGATE_FUNCTIONS = new Set(['COUNT', 'SUM', 'AVG', 'MIN', 'MAX']);

function isValidFilter(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  const filter = value as Record<string, unknown>;
  if (typeof filter.column !== 'string') return false;
  if (typeof filter.operator !== 'string' || !FILTER_OPERATORS.has(filter.operator)) return false;
  if (filter.value !== undefined && typeof filter.value !== 'string') return false;
  return filter.valueKind === undefined || filter.valueKind === 'string' || filter.valueKind === 'number';
}

function isValidSortEntry(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  const entry = value as Record<string, unknown>;
  return (
    typeof entry.column === 'string' &&
    (entry.direction === 'asc' || entry.direction === 'desc') &&
    typeof entry.priority === 'number' &&
    Number.isFinite(entry.priority)
  );
}

function isValidGrouping(value: unknown): boolean {
  if (value === null) return true;
  if (typeof value !== 'object') return false;
  const grouping = value as Record<string, unknown>;
  if (!Array.isArray(grouping.columns) || !grouping.columns.every((c) => typeof c === 'string')) return false;
  // SPEC-182's two flags are accepted ABSENT as well as boolean, and normalised to false on
  // the way out. Requiring them would discard the whole document — every tab, not just the
  // grouping — over a field that did not exist when it was written.
  if (grouping.duplicatesOnly !== undefined && typeof grouping.duplicatesOnly !== 'boolean') return false;
  if (grouping.showPercentage !== undefined && typeof grouping.showPercentage !== 'boolean') return false;
  if (!Array.isArray(grouping.aggregates)) return false;
  return grouping.aggregates.every((a) => {
    if (typeof a !== 'object' || a === null) return false;
    const aggregate = a as Record<string, unknown>;
    return (
      typeof aggregate.fn === 'string' && AGGREGATE_FUNCTIONS.has(aggregate.fn) && typeof aggregate.column === 'string'
    );
  });
}

/**
 * Reads a stored saved-query link, dropping anything it cannot trust (SPEC-183 FR-003).
 *
 * Absent is the ordinary case — every document written before SPEC-183, and every tab that
 * has never been saved — so a missing or malformed link restores the tab WITHOUT one rather
 * than discarding the session, on SPEC-182's precedent for an added field. All four fields
 * are required together: a half link would name a bucket with no key, and the write path
 * would resolve `overwrite` from it.
 *
 * @param value - The stored `savedQuery` object, or anything at all.
 * @returns The link, or undefined wherever the document was silent or wrong.
 */
function normalizeSavedQueryLink(value: unknown): SavedQueryLink | undefined {
  if (typeof value !== 'object' || value === null) return undefined;
  const link = value as Record<string, unknown>;
  const fields = [link.spaceId, link.bucket, link.key, link.name];
  if (!fields.every((field) => typeof field === 'string' && field.length > 0)) return undefined;
  return {
    spaceId: link.spaceId as string,
    bucket: link.bucket as string,
    key: link.key as string,
    name: link.name as string
  };
}

function isValidLedger(value: unknown): boolean {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  // The VALUES matter as much as the shape: `tabBytesScanned` sums them, so one string
  // turns a total into `"0x"` and one NaN turns it into NaN — breaking the never-NaN
  // invariant FR-007 AC4 exists to hold, from the only untrusted input this model has.
  return Object.values(value).every((bytes) => typeof bytes === 'number' && Number.isFinite(bytes));
}

function isValidQuery(value: unknown): boolean {
  const query = value as Record<string, unknown> | undefined;
  if (typeof query !== 'object' || query === null) return false;
  if (!Array.isArray(query.filters) || !query.filters.every(isValidFilter)) return false;
  if (!Array.isArray(query.ordering) || !query.ordering.every(isValidSortEntry)) return false;
  if (query.expression !== null && typeof query.expression !== 'string') return false;
  return isValidGrouping(query.grouping);
}

/**
 * Fills in a grouping's SPEC-182 flags, which a document written before it does not carry.
 *
 * Absent has to become `false` rather than staying undefined: `sameQuery` compares
 * descriptions on a canonical form, and a restored description whose flag is missing would
 * compare unequal to the identical one the panel builds — so the first apply after a
 * reload would push a history entry for a change nobody made.
 *
 * @param query - A description that has already passed validation.
 * @returns The same description, with a complete grouping or none.
 */
function normalizeQuery(query: ExplorationQuery): ExplorationQuery {
  if (!query.grouping) return query;
  return {
    ...query,
    grouping: {
      ...query.grouping,
      duplicatesOnly: query.grouping.duplicatesOnly === true,
      showPercentage: query.grouping.showPercentage === true
    }
  };
}

/**
 * Reads a stored history cursor, defaulting anything it cannot trust to no history.
 *
 * Unlike the presentation beside it, every entry here is a description that RENDERS SQL,
 * so a malformed one cannot be normalised field by field — it is dropped whole. Dropping
 * costs the user their Back button for this tab and nothing else, where restoring a
 * half-valid description would put a query they never built one click away.
 *
 * @param value - The stored `history` object, or anything at all.
 * @returns A usable cursor; empty wherever the document was silent or wrong.
 */
function normalizeHistory(value: unknown): QueryHistoryCursor {
  const stored = (value ?? {}) as Record<string, unknown>;
  const side = (entries: unknown): ExplorationQuery[] =>
    Array.isArray(entries) && entries.every(isValidQuery)
      ? (entries as ExplorationQuery[]).slice(-EXPLORER_FILTER_HISTORY_MAX).map(normalizeQuery)
      : [];
  return {past: side(stored.past), future: side(stored.future)};
}

function isValidExploration(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  const exploration = value as Record<string, unknown>;
  if (typeof exploration.id !== 'string') return false;
  if (!isValidSource(exploration.source)) return false;
  if (!isValidQuery(exploration.query)) return false;

  // Presentation is only required to BE an object here; every field is normalised on the
  // way out rather than gating the restore. It renders no SQL, so a bad value cannot
  // produce a query the user never built — and discarding a whole session's explorations
  // over a stale `valuePanelOpen` would cost far more than defaulting it.
  return typeof exploration.presentation === 'object' && exploration.presentation !== null;
}

function stringArray(value: unknown): string[] | null {
  return Array.isArray(value) && value.every((v) => typeof v === 'string') ? (value as string[]) : null;
}

function finiteWidths(value: unknown): Record<string, number> | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const entries = Object.entries(value);
  if (!entries.every(([, px]) => typeof px === 'number' && Number.isFinite(px))) return null;
  return Object.fromEntries(entries) as Record<string, number>;
}

const COLOUR_OPERATORS = new Set(['=', '<>', '>', '>=', '<', '<=', 'like', 'ilike', 'regex']);

function isValidColourRule(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  const rule = value as Record<string, unknown>;
  if (typeof rule.id !== 'string' || rule.id === '') return false;
  if (rule.column !== undefined && typeof rule.column !== 'string') return false;
  if (rule.scope !== undefined && rule.scope !== 'cell' && rule.scope !== 'row') return false;
  if (typeof rule.operator !== 'string' || !COLOUR_OPERATORS.has(rule.operator)) return false;
  if (typeof rule.value !== 'string') return false;
  // The colours are checked against the PALETTE, not merely against `string`: a stored
  // `#ff0000` would be rendered verbatim as an inline style, and the contrast the palette
  // is measured for would no longer hold for it (FR-002 AC8).
  if (rule.foreground !== undefined && !FORMATTING_FOREGROUNDS.includes(rule.foreground as never)) return false;
  if (rule.background !== undefined && !FORMATTING_BACKGROUNDS.includes(rule.background as never)) return false;
  if (rule.gradient === undefined) return true;
  if (typeof rule.gradient !== 'object' || rule.gradient === null) return false;
  const gradient = rule.gradient as Record<string, unknown>;
  return (
    typeof gradient.min === 'number' &&
    Number.isFinite(gradient.min) &&
    typeof gradient.max === 'number' &&
    Number.isFinite(gradient.max) &&
    FORMATTING_BACKGROUNDS.includes(gradient.from as never) &&
    FORMATTING_BACKGROUNDS.includes(gradient.to as never)
  );
}

function isValidTransformer(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  const transformer = value as Record<string, unknown>;
  if (transformer.kind === 'numeric') {
    return (
      typeof transformer.precision === 'number' &&
      Number.isInteger(transformer.precision) &&
      transformer.precision >= 0 &&
      transformer.precision <= NUMERIC_TRANSFORMER_MAX_PRECISION &&
      typeof transformer.lenient === 'boolean'
    );
  }
  if (transformer.kind === 'binary') {
    return (
      (transformer.encoding === 'hex' || transformer.encoding === 'base64') &&
      typeof transformer.maxLength === 'number' &&
      Number.isInteger(transformer.maxLength) &&
      transformer.maxLength > 0 &&
      transformer.maxLength <= BINARY_TRANSFORMER_MAX_LENGTH
    );
  }
  if (transformer.kind === 'url') return typeof transformer.template === 'string';
  return false;
}

/**
 * Reads a stored formatting block, discarding it WHOLE if any part of it is wrong
 * (FR-007 AC2).
 *
 * Deliberately unlike the field-by-field normalisation around it, and the difference is
 * what the requirement asks for: a partially-applied colour set is a rule list the user
 * never built, and a rule that survived while the one meant to override it was dropped
 * paints the opposite of what was intended. Losing the block costs a tab its colours;
 * keeping half of it costs the user their trust in what they are looking at.
 *
 * A document written before SPEC-184 carries no block at all, which is the ordinary case
 * for the first session after a deploy and reaches the same default.
 *
 * @param value - The stored `formatting` object, or anything at all.
 * @returns The block, or the empty state.
 */
function normalizeFormatting(value: unknown): FormattingState {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return emptyFormattingState();
  const stored = value as Record<string, unknown>;
  if (!Array.isArray(stored.rules) || !stored.rules.every(isValidColourRule)) return emptyFormattingState();
  if (typeof stored.colourByType !== 'boolean') return emptyFormattingState();
  if (!Array.isArray(stored.stripeColumns) || !stored.stripeColumns.every((c) => typeof c === 'string')) {
    return emptyFormattingState();
  }
  const transformers = stored.transformers;
  if (typeof transformers !== 'object' || transformers === null || Array.isArray(transformers)) {
    return emptyFormattingState();
  }
  if (!Object.values(transformers).every(isValidTransformer)) return emptyFormattingState();
  return {
    rules: stored.rules as FormattingState['rules'],
    colourByType: stored.colourByType,
    stripeColumns: stored.stripeColumns as string[],
    transformers: transformers as FormattingState['transformers']
  };
}

/**
 * Reads a stored presentation, defaulting every field it cannot trust.
 *
 * A document written before SPEC-180 carries only the four geometry fields, and one
 * written by a future version may carry fields this build has never heard of — both must
 * restore rather than discard the tab, because presentation is cosmetic and the
 * exploration beside it is not.
 *
 * @param value - The stored `presentation` object (already known to BE an object).
 * @returns A complete presentation, with defaults wherever the document was silent or wrong.
 */
function normalizePresentation(value: unknown): ExplorationPresentation {
  const stored = (value ?? {}) as Record<string, unknown>;
  const empty = emptyExplorationPresentation();
  const presentation = stored.presentation;
  return {
    hiddenColumns: stringArray(stored.hiddenColumns) ?? empty.hiddenColumns,
    columnOrder: stringArray(stored.columnOrder) ?? empty.columnOrder,
    pinnedColumns: stringArray(stored.pinnedColumns) ?? empty.pinnedColumns,
    columnWidths: finiteWidths(stored.columnWidths) ?? empty.columnWidths,
    presentation: presentation === 'grid' || presentation === 'record' || presentation === 'text' ? presentation : null,
    valuePanelOpen: stored.valuePanelOpen === true,
    // A non-integer or negative index would address a row that cannot exist; the views
    // clamp to the loaded page anyway, so page one, row one is the honest default.
    recordRowIndex:
      typeof stored.recordRowIndex === 'number' && Number.isInteger(stored.recordRowIndex) && stored.recordRowIndex >= 0
        ? stored.recordRowIndex
        : empty.recordRowIndex,
    formatting: normalizeFormatting(stored.formatting)
  };
}

// Structural validation — a corrupt, old or foreign blob must never crash the page, and
// must never be PARTIALLY applied. A half-restored exploration is worse than none: it
// renders SQL from a description the user never built.
function isValidTabsState(value: unknown): value is ExplorationTabsState {
  if (typeof value !== 'object' || value === null) return false;
  const state = value as Record<string, unknown>;
  if (state.version !== 1) return false;
  if (!Array.isArray(state.tabs)) return false;
  if (typeof state.activeTabId !== 'string') return false;

  const tabsOk = state.tabs.every((t) => {
    if (typeof t !== 'object' || t === null) return false;
    const tab = t as Record<string, unknown>;
    return (
      typeof tab.id === 'string' &&
      typeof tab.label === 'string' &&
      isValidExploration(tab.exploration) &&
      isValidLedger(tab.scannedByExecution)
    );
  });
  if (!tabsOk) return false;

  // The invariant `activeTabId` always references an existing tab — with the empty state
  // as the one legal exception, since there is nothing for it to reference.
  const tabs = state.tabs as ExplorationTab[];
  if (tabs.length === 0) return state.activeTabId === '';
  return tabs.some((t) => t.id === state.activeTabId);
}

/** Returns the persisted tabs state, or null if none exists / it is invalid / storage is unavailable. */
export function readExplorationTabsState(username: string): ExplorationTabsState | null {
  const key = tabsKey(username);
  if (!key) return null;
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!isValidTabsState(parsed)) return null;
    return {
      ...parsed,
      tabs: parsed.tabs.map((tab) => ({
        ...tab,
        // A document written before SPEC-181 carries no history at all, which is the
        // ordinary case for the first session after a deploy — not a fault.
        history: normalizeHistory(tab.history),
        savedQuery: normalizeSavedQueryLink(tab.savedQuery),
        exploration: {
          ...tab.exploration,
          query: normalizeQuery(tab.exploration.query),
          presentation: normalizePresentation(tab.exploration.presentation)
        }
      }))
    };
  } catch {
    return null;
  }
}

/** Persists the tabs state under the per-user key. No-op on failure / empty user. */
export function writeExplorationTabsState(username: string, state: ExplorationTabsState): void {
  const key = tabsKey(username);
  if (!key) return;
  try {
    sessionStorage.setItem(key, JSON.stringify(state));
  } catch {
    // Degrade to not-persisted; never surface a storage error to the page.
  }
}

/**
 * Total bytes this tab has scanned, across every DISTINCT execution it has run.
 *
 * Summed from a map keyed by execution id rather than accumulated as a running total,
 * which is what makes FR-007's "a cache hit adds nothing" true by construction: a
 * re-rendered identical statement resolves to an id already in the map, so recording it
 * again changes no total. A running sum would have to DETECT a cache hit, and a detector
 * can be wrong in the direction that overcharges.
 *
 * @param tab - The tab to total.
 * @returns Bytes scanned; 0 for a tab that has run nothing.
 */
export function tabBytesScanned(tab: ExplorationTab): number {
  return Object.values(tab.scannedByExecution).reduce((total, bytes) => total + bytes, 0);
}
