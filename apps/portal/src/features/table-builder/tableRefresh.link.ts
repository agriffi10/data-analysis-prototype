import {CATALOG_IDENTIFIER_RE} from '../query/query.constants';
import type {PendingRemoval} from './tableRefresh.types';

/** Mirrors `tbcommon.messages.MAX_NAMED_COLUMNS` — the link never carries more. */
export const MAX_LINKED_COLUMNS = 20;

/**
 * The raw (still percent-encoded) value of one query parameter.
 *
 * `URLSearchParams.get` is deliberately NOT used for this: it decodes, and SPEC-144
 * encodes each column name individually before joining them with a comma — so a
 * name containing `%2C` would come back as a bare comma and split into two columns.
 * The separator has to be read before anything is decoded.
 */
function rawParam(search: string, name: string): string | null {
  const query = search.startsWith('?') ? search.slice(1) : search;
  for (const part of query.split('&')) {
    const eq = part.indexOf('=');
    if ((eq === -1 ? part : part.slice(0, eq)) !== name) continue;
    return eq === -1 ? '' : part.slice(eq + 1);
  }
  return null;
}

function decode(value: string): string | null {
  try {
    return decodeURIComponent(value);
  } catch {
    return null; // a malformed escape — drop this name, keep the rest
  }
}

/**
 * Parse SPEC-144's `columns_removed` notification link
 * (`/query?refreshTable={database}.{table}&removed={names}`) off the Query route's
 * query string. Returns `null` — meaning "ignore these parameters entirely" — for
 * anything that isn't a pair of catalog-safe identifiers, because the link is
 * user-controllable text in a URL.
 *
 * **The column names are NOT validated against `CATALOG_IDENTIFIER_RE`, and must not
 * be.** Column names are not catalog-safe anywhere in this plane — `infer-schema`
 * takes them verbatim from a CSV header — so `id`, `Amount` and `first name` are all
 * ordinary and all fail that pattern. Applying it would discard the whole link for
 * most real tables. They are decoded, capped, and rendered as text.
 */
export function parseRefreshLink(search: string): PendingRemoval | null {
  const raw = rawParam(search, 'refreshTable');
  if (!raw) return null;
  const qualified = decode(raw);
  if (!qualified) return null;

  const dot = qualified.indexOf('.');
  if (dot === -1) return null;
  const database = qualified.slice(0, dot);
  const tableName = qualified.slice(dot + 1);
  if (!CATALOG_IDENTIFIER_RE.test(database) || !CATALOG_IDENTIFIER_RE.test(tableName)) return null;

  const removed = rawParam(search, 'removed') ?? '';
  const columns = removed
    .split(',')
    .map(decode)
    .filter((name): name is string => !!name)
    .slice(0, MAX_LINKED_COLUMNS);

  return {database, tableName, columns};
}
