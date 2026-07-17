import {GetDatabaseCommand, GetTablesCommand} from '@aws-sdk/client-glue';
import {getGlueClient} from '../../lib/glueClient';
import {withCredentialRetry} from '../../lib/credentialRetry';
import {toServiceError} from '../../lib/serviceResult';
import type {ServiceResult} from '../../types/service.types';
import type {GlueTableSummary} from './query.types';

/**
 * Confirms a database the user can access exists. A missing database is
 * surfaced as a clean `NotFound` error (drives the empty-state), never thrown.
 */
export async function getDatabase(databaseName: string): Promise<ServiceResult<{name: string}>> {
  return withCredentialRetry(getGlueClient, async (client) => {
    try {
      const response = await client.send(new GetDatabaseCommand({Name: databaseName}));
      return {
        success: true,
        data: {name: response.Database?.Name ?? databaseName}
      };
    } catch (err) {
      const e = err as {name?: string};
      if (e.name === 'EntityNotFoundException') {
        return {
          success: false,
          error: {
            message: `Database "${databaseName}" does not exist yet.`,
            code: 'NotFound'
          }
        };
      }
      return toServiceError(err, 'Failed to load the database');
    }
  });
}

/**
 * Lists a database's tables + columns for the schema browser, paginating
 * GetTables past the page cap. A not-yet-created database is an empty schema,
 * not an error.
 */
export async function listTables(databaseName: string): Promise<ServiceResult<GlueTableSummary[]>> {
  return withCredentialRetry(getGlueClient, async (client) => {
    try {
      const tables: GlueTableSummary[] = [];
      let nextToken: string | undefined;
      do {
        const response = await client.send(
          new GetTablesCommand({
            DatabaseName: databaseName,
            NextToken: nextToken
          })
        );
        for (const t of response.TableList ?? []) {
          tables.push({
            name: t.Name ?? '',
            columns: (t.StorageDescriptor?.Columns ?? []).map((c) => ({
              name: c.Name ?? '',
              type: c.Type ?? ''
            })),
            tableType: t.TableType,
            location: t.StorageDescriptor?.Location
          });
        }
        nextToken = response.NextToken;
      } while (nextToken);
      return {success: true, data: tables};
    } catch (err) {
      const e = err as {name?: string};
      // Database exists in the catalog scope but has no tables yet, or hasn't been
      // created — either way the schema browser shows nothing, not an error.
      if (e.name === 'EntityNotFoundException') {
        return {success: true, data: []};
      }
      return toServiceError(err, 'Failed to list tables');
    }
  });
}
