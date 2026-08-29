import {apiRequest} from '../../lib/apiClient';
import type {ServiceResult} from '../../types/service.types';
import type {GlueTableSummary} from './catalog.types';

/**
 * Confirms a database the user can access exists. A missing database is
 * surfaced as a clean `NotFound` error (drives the empty-state), never thrown.
 *
 * The mapping from Glue's `EntityNotFoundException` moved to the API, which answers 404; the
 * code a caller sees is unchanged.
 *
 * @param databaseName - The database to look up.
 * @returns Its name, or the machine code a surface maps to wording.
 */
export async function getDatabase(databaseName: string): Promise<ServiceResult<{name: string}>> {
  return apiRequest('catalog.database.get', {params: {database: databaseName}});
}

/**
 * Lists a database's tables + columns for the schema browser, paginating past the page cap. A
 * not-yet-created database is an empty schema, not an error.
 *
 * **The continuation walk stays in the browser.** The API answers one page per request, by
 * design: a server-side walk over a collection whose size the user controls would put an
 * unbounded loop under a 30-second gateway ceiling. This is the same loop it always was, over
 * API calls instead of SDK calls, and `useSchema` cannot tell the difference.
 *
 * @param databaseName - The database whose tables to list.
 * @returns Every table, or the machine code a surface maps to wording.
 */
export async function listTables(databaseName: string): Promise<ServiceResult<GlueTableSummary[]>> {
  const tables: GlueTableSummary[] = [];
  let nextToken: string | undefined;

  do {
    const query: {nextToken?: string} = {};
    if (nextToken !== undefined) query.nextToken = nextToken;

    const result = await apiRequest('catalog.tables.list', {
      params: {database: databaseName},
      query
    });
    if (!result.success) return result;

    for (const table of result.data.items) {
      tables.push({
        name: table.name,
        columns: table.columns,
        tableType: table.tableType ?? undefined,
        location: table.location ?? undefined
      });
    }
    nextToken = result.data.nextToken ?? undefined;
  } while (nextToken);

  return {success: true, data: tables};
}
