// SPEC-063 Data Model: the single source of truth for splitting a database's Glue
// objects into Tables vs Views for the schema rail's two collapsible groups. A view
// is a Glue `VIRTUAL_VIEW` (SPEC-048); everything else is a table. Order is preserved.

import type {GlueTableSummary} from './query.types';

export type PartitionedSchema = {
  tables: GlueTableSummary[]; // tableType !== 'VIRTUAL_VIEW'
  views: GlueTableSummary[]; // tableType === 'VIRTUAL_VIEW'
};

export function partitionSchema(tables: GlueTableSummary[]): PartitionedSchema {
  const result: PartitionedSchema = {tables: [], views: []};
  for (const t of tables) {
    if (t.tableType === 'VIRTUAL_VIEW') result.views.push(t);
    else result.tables.push(t);
  }
  return result;
}
