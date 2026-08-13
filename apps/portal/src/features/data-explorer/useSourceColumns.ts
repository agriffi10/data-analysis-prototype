import {useMemo} from 'react';
import {useSchema} from '../catalog/useSchema';
import {normalizeColumnType} from '../catalog/catalog.format';
import type {QueryColumn} from '../catalog/catalog.types';
import type {ExplorationSource} from './dataExplorer.types';

/**
 * The columns a source is known to have BEFORE any execution returns (SPEC-180 FR-006).
 *
 * The two arms of `ExplorationSource` differ exactly here: a `table` has its schema in
 * Glue, so its headers can be drawn while the first statement is still running; a `sql`
 * source has none until the execution reports `ResultSetMetadata`, and returns nothing.
 * The grid handles both from the start, even though the `sql` arm has no UI until
 * SPEC-183 — a header path retrofitted later would be a change to every surface built on
 * it in between.
 *
 * The read is `features/catalog/`'s cached schema, shared with the source picker and the
 * Query rail, so an explored table is normally a cache hit rather than a Glue call.
 *
 * @param source - The active exploration's source, or null to read nothing.
 * @returns The known columns; empty when they are unknowable until the execution lands.
 */
export function useSourceColumns(source: ExplorationSource | null): QueryColumn[] {
  const database = source?.kind === 'table' ? source.database : null;
  const schema = useSchema(database);

  return useMemo((): QueryColumn[] => {
    if (source?.kind !== 'table') return [];
    const table = schema.data?.tables.find((t) => t.name === source.table);
    return (table?.columns ?? []).map((column) => ({name: column.name, type: normalizeColumnType(column.type)}));
  }, [schema.data, source]);
}
