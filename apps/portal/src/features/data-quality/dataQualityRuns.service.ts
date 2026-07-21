import {GetObjectCommand} from '@aws-sdk/client-s3';
import {getS3Client} from '../../lib/s3Client';
import {withCredentialRetry} from '../../lib/credentialRetry';
import {toServiceError} from '../../lib/serviceResult';
import {isNotFound} from '../../lib/s3Errors';
import type {ServiceResult} from '../../types/service.types';
import type {DataQualityRunSummary} from './dataQuality.types';
import {REPORTS_FOLDER} from './dataQualityReport.service';

/** `{space}/_data-quality-reports/index.json` — the same key `dqcommon/index_store.py` writes. */
export function runsIndexKey(space: string): string {
  return `${space}/${REPORTS_FOLDER}/index.json`;
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
  return withCredentialRetry(getS3Client, async (client) => {
    try {
      const response = await client.send(new GetObjectCommand({Bucket: bucket, Key: runsIndexKey(space)}));
      const body = await response.Body?.transformToString();
      const parsed: unknown = body ? JSON.parse(body) : null;
      const entries = (parsed as {entries?: unknown})?.entries;
      if (!Array.isArray(entries)) {
        // A corrupt index reads as empty, mirroring the writer, which rebuilds it on the
        // next run rather than treating it as fatal.
        return {success: true, data: []};
      }
      return {success: true, data: entries.filter(isEntry).map((entry) => ({...entry, space}))};
    } catch (err) {
      if (isNotFound(err)) return {success: true, data: []};
      if (err instanceof SyntaxError) return {success: true, data: []};
      return toServiceError(err, 'Failed to load data quality checks');
    }
  });
}
