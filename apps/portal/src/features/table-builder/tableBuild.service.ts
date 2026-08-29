import {apiRequest} from '../../lib/apiClient';
import {discardPayload} from '../../lib/serviceResult';
import {CATALOG_IDENTIFIER_RE} from '../../lib/catalogIdentifier';
import type {ServiceResult} from '../../types/service.types';
import type {PartitionKey, TableBuildRequest} from './tableBuild.types';
import type {TableRefreshRequest} from './tableRefresh.types';

/**
 * One partition key, as the API declares it.
 *
 * The API's contract cannot express the three-variant union this type models — its vocabulary has
 * no union of object shapes — so the variants are flattened into one shape whose per-kind fields
 * are optional, and the projection bounds travel as strings. Both halves are safe rather than
 * lossy: the control plane accepts bounds that are numbers or strings, and the DDL builder
 * interpolates the pair into one `lo,hi` property without arithmetic, so the table property is
 * byte-identical either way. What is genuinely given up is that the API no longer refuses a date
 * field on an integer key; the plane still validates every combination and refuses by name.
 *
 * @param key - The key as the dialog models it.
 * @returns The key as the wire carries it.
 */
function onTheWire(key: PartitionKey): {
  name: string;
  type: PartitionKey['type'];
  range?: string[];
  format?: string;
  values?: string[];
  digits?: number;
  interval?: number;
  intervalUnit?: string;
} {
  if (key.type === 'string') return {name: key.name, type: key.type, values: key.values};
  const range = [String(key.range[0]), String(key.range[1])];
  if (key.type === 'integer') {
    return {
      name: key.name,
      type: key.type,
      range,
      ...(key.digits === undefined ? {} : {digits: key.digits})
    };
  }
  return {
    name: key.name,
    type: key.type,
    range,
    format: key.format,
    ...(key.interval === undefined ? {} : {interval: key.interval}),
    ...(key.intervalUnit === undefined ? {} : {intervalUnit: key.intervalUnit})
  };
}

/**
 * Enqueue a create-table request onto the table-builder FIFO queue — the browser's
 * only table-builder write. The async control plane creates the table and
 * notifies the actor of the outcome, so success means enqueued, not created.
 *
 * The identity and the FIFO group are the API's; the request id is still minted here.
 */
export async function enqueueTableBuild(req: TableBuildRequest): Promise<ServiceResult<void>> {
  return discardPayload(
    await apiRequest('tableBuild.create', {
      body: {
        requestId: crypto.randomUUID(),
        space: req.space,
        tableName: req.tableName,
        partitionKeys: (req.partitionKeys ?? []).map(onTheWire)
      }
    })
  );
}

/**
 * Enqueue a refresh request onto the same table-builder FIFO queue — the plane's
 * `mode: 'refresh'` half. The pipeline re-inspects the folder the table already
 * points at and replaces the definition in place; the outcome arrives as
 * a notification, so success means enqueued, not refreshed.
 *
 * `partitionKeys` is always `[]`: a refresh reconstructs the table's existing keys
 * from the catalog and the server refuses a request that redeclares them.
 * `allowRemovals` is sent only when the user ticked the opt-in — the diff validates
 * the flag rather than coercing it, so an always-present `false` would be a
 * different request than an absent one.
 */
export async function enqueueTableRefresh(req: TableRefreshRequest): Promise<ServiceResult<void>> {
  return discardPayload(
    await apiRequest('tableBuild.refresh', {
      body: {
        requestId: crypto.randomUUID(),
        space: req.space,
        tableName: req.tableName,
        partitionKeys: [],
        ...(req.allowRemovals === true ? {allowRemovals: true} : {})
      }
    })
  );
}

/**
 * Derive a suggested, catalog-safe table name from a folder name: lowercase,
 * non-conforming chars → `_`, leading letter ensured, trimmed to the max length.
 * UX only — the field stays editable and the name is re-checked client- and
 * server-side, so an edge-case suggestion just leaves Confirm disabled.
 */
export function suggestTableName(folderName: string): string {
  let s = folderName.toLowerCase().replace(/[^a-z0-9_]+/g, '_');
  s = s.replace(/^_+/, ''); // drop leading junk so a real letter can lead
  if (!/^[a-z]/.test(s)) s = `t_${s}`;
  s = s.replace(/_+$/, ''); // cosmetic: no trailing underscore
  if (s.length > 63) s = s.slice(0, 63).replace(/_+$/, '');
  return s;
}

/** The single client-side table-name check (UX only — the server re-validates). */
export function isValidTableName(name: string): boolean {
  return CATALOG_IDENTIFIER_RE.test(name);
}
