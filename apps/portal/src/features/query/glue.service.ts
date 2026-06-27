import { GetDatabaseCommand, GetTablesCommand } from '@aws-sdk/client-glue';
import { getGlueClient } from '../../lib/glueClient';
import { withCredentialRetry } from '../../lib/credentialRetry';
import type { ServiceResult } from '../../types/service.types';
import type { GlueTableSummary } from './query.types';

function toServiceError(err: unknown, fallback: string) {
  const e = err as { message?: string; name?: string };
  return {
    success: false as const,
    error: { message: e.message ?? fallback, code: e.name },
  };
}

// FR-006: confirm the signed-in user's own database exists (named = username). The
// app only ever asks for the user's own derived database — IAM/LF (SPEC-032) deny
// anything else. A missing database is surfaced as a clean `NotFound` (drives the
// SPEC-035 empty-state / SPEC-033 backfill case), never thrown.
export async function getDatabase(databaseName: string): Promise<ServiceResult<{ name: string }>> {
  return withCredentialRetry(getGlueClient, async (client) => {
    try {
      const response = await client.send(new GetDatabaseCommand({ Name: databaseName }));
      return {
        success: true,
        data: { name: response.Database?.Name ?? databaseName },
      };
    } catch (err) {
      const e = err as { name?: string };
      if (e.name === 'EntityNotFoundException') {
        return {
          success: false,
          error: {
            message: `Database "${databaseName}" does not exist yet.`,
            code: 'NotFound',
          },
        };
      }
      return toServiceError(err, 'Failed to load the database');
    }
  });
}

// FR-006: list the database's tables + columns for the schema browser, paginating
// GetTables past the page cap. A not-yet-created database (the user hasn't run any
// DDL) is an empty schema, not an error. AccessDenied and other failures map to a
// clean ServiceResult error.
export async function listTables(databaseName: string): Promise<ServiceResult<GlueTableSummary[]>> {
  return withCredentialRetry(getGlueClient, async (client) => {
    try {
      const tables: GlueTableSummary[] = [];
      let nextToken: string | undefined;
      do {
        const response = await client.send(
          new GetTablesCommand({
            DatabaseName: databaseName,
            NextToken: nextToken,
          })
        );
        for (const t of response.TableList ?? []) {
          tables.push({
            name: t.Name ?? '',
            columns: (t.StorageDescriptor?.Columns ?? []).map((c) => ({
              name: c.Name ?? '',
              type: c.Type ?? '',
            })),
            tableType: t.TableType,
            location: t.StorageDescriptor?.Location,
          });
        }
        nextToken = response.NextToken;
      } while (nextToken);
      return { success: true, data: tables };
    } catch (err) {
      const e = err as { name?: string };
      // Database exists in the catalog scope but has no tables yet, or hasn't been
      // created — either way the schema browser shows nothing, not an error.
      if (e.name === 'EntityNotFoundException') {
        return { success: true, data: [] };
      }
      return toServiceError(err, 'Failed to list tables');
    }
  });
}
