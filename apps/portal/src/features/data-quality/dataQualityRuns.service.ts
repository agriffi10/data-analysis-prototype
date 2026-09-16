import {appManagedPrefix, DATA_QUALITY_REPORTS_FOLDER} from '../../lib/appManagedPaths';
import {readJsonDocument} from '../../lib/s3Json';
import {ok} from '../../lib/serviceResult';
import type {ServiceResult} from '../../types/service.types';
import type {DataQualityRunSummary} from './dataQuality.types';

/** `{space}/_data-quality-reports/index.json` — the same key `dqcommon/index_store.py` writes. */
export function runsIndexKey(space: string): string {
  return `${appManagedPrefix(`${space}/`, DATA_QUALITY_REPORTS_FOLDER)}index.json`;
}

/**
 * Is this an index entry rather than some other JSON that happens to live at the key?
 *
 * Checked field by field, and entries that fail are DROPPED rather than failing the whole
 * space: an index is an append-only log written by many runs over time, so one malformed
 * entry (a partial write, an older shape) should cost that row and not the user's entire
 * history. The report view takes the opposite stance for the same reason in reverse — there,
 * "not there" is the answer to a specific question the user asked.
 */
function isEntry(value: unknown): value is Omit<DataQualityRunSummary, 'space'> {
  const entry = value as Partial<DataQualityRunSummary> | null;
  return (
    !!entry &&
    typeof entry === 'object' &&
    typeof entry.requestId === 'string' &&
    typeof entry.location === 'string' &&
    typeof entry.timestamp === 'string' &&
    (entry.verdict === 'clean' || entry.verdict === 'issues_found')
  );
}

/**
 * Interpret an index body. TOTAL: a body that is not JSON, is not an object, or carries no
 * `entries` array reads as the empty list, mirroring the writer — which rebuilds the index
 * on the next run rather than treating a corrupt one as fatal. `space` is stamped onto every
 * entry here because the entry on S3 does not carry its own, and the row's link needs it.
 */
function parseIndex(body: string | undefined, space: string): DataQualityRunSummary[] {
  let parsed: unknown;
  try {
    parsed = body ? JSON.parse(body) : null;
  } catch {
    return [];
  }
  const entries = (parsed as {entries?: unknown})?.entries;
  if (!Array.isArray(entries)) return [];
  return entries.filter(isEntry).map((entry) => ({...entry, space}));
}

/**
 * Read one space's runs index.
 *
 * A MISSING INDEX IS AN EMPTY SUCCESS, not a failure: a space where no check has ever
 * completed has no index object at all, and that is the ordinary state of every space until
 * its first run — surfacing it as an error would put a red banner on a page whose correct
 * answer is the empty state.
 *
 * `space` is stamped onto every entry here, which is the only place that knows it: the
 * entry on S3 does not carry its own space, and the row's link needs it.
 */
export async function getRunsIndex(bucket: string, space: string): Promise<ServiceResult<DataQualityRunSummary[]>> {
  return readJsonDocument({
    bucket,
    key: runsIndexKey(space),
    parse: (body) => ok(parseIndex(body, space)),
    onMissing: () => ({success: true, data: []}),
    fallbackMessage: 'Failed to load data quality checks'
  });
}
