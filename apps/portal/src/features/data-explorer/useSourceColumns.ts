import {useMemo} from 'react';
import {useSchema} from '../catalog/useSchema';
import {normalizeColumnType} from '../catalog/catalog.format';
import type {QueryColumn} from '../catalog/catalog.types';
import type {ExplorationSource} from './dataExplorer.types';

const NO_COLUMNS: QueryColumn[] = [];

/**
 * The columns a source is known to have BEFORE the current execution returns.
 *
 * The two arms of `ExplorationSource` differ exactly here: a `table` has its schema in Glue,
 * so its headers can be drawn while the first statement is still running; a `sql` source has
 * none until an execution reports `ResultSetMetadata`, and then only what its tab remembered
 * from an ungrouped one. That memory is what the Grouping panel lists while a grouping is in
 * force, when the running statement's own columns are the grouping's.
 *
 * The table read is `features/catalog/`'s cached schema, shared with the source picker and the
 * Query rail, so an explored table is normally a cache hit rather than a Glue call.
 *
 * @param source - The active exploration's source, or null to read nothing.
 * @param sqlSourceColumns - The tab's remembered columns, for a `sql` source.
 * @returns The known columns; empty when they are unknowable until an execution lands.
 */
export function useSourceColumns(source: ExplorationSource | null, sqlSourceColumns?: QueryColumn[]): QueryColumn[] {
  const database = source?.kind === 'table' ? source.database : null;
  const schema = useSchema(database);

  return useMemo((): QueryColumn[] => {
    if (source?.kind === 'sql') return sqlSourceColumns ?? NO_COLUMNS;
    if (source?.kind !== 'table') return NO_COLUMNS;
    const table = schema.data?.tables.find((t) => t.name === source.table);
    return (table?.columns ?? []).map((column) => ({name: column.name, type: normalizeColumnType(column.type)}));
  }, [schema.data, source, sqlSourceColumns]);
}
