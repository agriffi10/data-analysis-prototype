// The refresh half of the table-builder request contract (SPEC-143/144), from the
// browser's side. As with a create, the browser only SENDS this: eligibility, the
// schema diff and the in-place rebuild are all server-side.

import type {TableBuildSpace} from './tableBuild.types';
import type {GlueTableSummary} from '../catalog/catalog.types';

export type TableRefreshRequest = {
  space: TableBuildSpace;
  tableName: string;
  /** Omitted unless the user ticked the opt-in (SPEC-144: never coerced, never persisted). */
  allowRemovals?: boolean;
};

/**
 * Parsed from SPEC-144's `columns_removed` notification link. Never stored — the
 * opt-in it gates is re-taken on every open.
 */
export type PendingRemoval = {
  database: string;
  tableName: string;
  columns: string[];
};

export type TableRefreshTarget = {
  database: string;
  table: GlueTableSummary;
  /** Present ⇒ opened from a columns_removed link; render the names, gate confirm. */
  pending: PendingRemoval | null;
};
