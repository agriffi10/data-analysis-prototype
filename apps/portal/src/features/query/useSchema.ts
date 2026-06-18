import { useQuery, type QueryClient } from '@tanstack/react-query';
import { getDatabase, listTables } from './glue.service';
import { queryKeys } from './queryKeys';
import type { GlueTableSummary } from './query.types';

export type SchemaData = {
  database: { name: string };
  tables: GlueTableSummary[];
};

// SPEC-034 FR-006: expose the signed-in user's database + its tables for the
// schema browser (SPEC-035). Disabled while the database name is null. Keyed by
// database so a DDL `CREATE TABLE`/`DROP TABLE` run through runQuery can refresh
// it via invalidateSchema.
export function useSchema(databaseName: string | null) {
  return useQuery({
    queryKey: queryKeys.schema(databaseName ?? '__none__'),
    enabled: databaseName !== null,
    queryFn: async (): Promise<SchemaData> => {
      const db = databaseName as string;
      const dbResult = await getDatabase(db);
      if (!dbResult.success) throw new Error(dbResult.error.message);
      const tablesResult = await listTables(db);
      if (!tablesResult.success) throw new Error(tablesResult.error.message);
      return { database: dbResult.data, tables: tablesResult.data };
    },
  });
}

// FR-006: refresh a database's schema after table DDL runs through runQuery.
// Exported (not a method) so it can be called with any QueryClient and unit-tested.
export async function invalidateSchema(
  client: QueryClient,
  databaseName: string,
): Promise<void> {
  await client.invalidateQueries({ queryKey: queryKeys.schema(databaseName) });
}
