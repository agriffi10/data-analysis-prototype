import type {GlueTableSummary} from './catalog.types';

export type PartitionedSchema = {
  /** Everything that is not a Glue `VIRTUAL_VIEW`. */
  tables: GlueTableSummary[];
  /** Glue objects with `tableType === 'VIRTUAL_VIEW'`. */
  views: GlueTableSummary[];
};

/**
 * Splits a database's Glue objects into tables vs views. Input order is preserved within each
 * group.
 *
 * In `catalog/` because it has two consumers in different features — the Query workspace's
 * schema rail and the Data Explorer's source picker — and a lint rule forbids the second from
 * importing the first, which is where this used to live.
 */
export function partitionSchema(tables: GlueTableSummary[]): PartitionedSchema {
  const result: PartitionedSchema = {tables: [], views: []};
  for (const t of tables) {
    if (t.tableType === 'VIRTUAL_VIEW') result.views.push(t);
    else result.tables.push(t);
  }
  return result;
}
