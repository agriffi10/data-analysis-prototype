import type {GlueTableSummary} from './catalog.types';

export type PartitionedSchema = {
  /** Everything that is not a Glue `VIRTUAL_VIEW`. */
  tables: GlueTableSummary[];
  /** Glue objects with `tableType === 'VIRTUAL_VIEW'`. */
  views: GlueTableSummary[];
};

/**
 * Splits a database's Glue objects into tables vs views for the schema rail's
 * two collapsible groups. Input order is preserved within each group.
 */
export function partitionSchema(tables: GlueTableSummary[]): PartitionedSchema {
  const result: PartitionedSchema = {tables: [], views: []};
  for (const t of tables) {
    if (t.tableType === 'VIRTUAL_VIEW') result.views.push(t);
    else result.tables.push(t);
  }
  return result;
}
