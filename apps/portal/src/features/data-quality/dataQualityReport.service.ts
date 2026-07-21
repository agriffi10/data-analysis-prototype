import {GetObjectCommand} from '@aws-sdk/client-s3';
import {getS3Client} from '../../lib/s3Client';
import {withCredentialRetry} from '../../lib/credentialRetry';
import {toServiceError} from '../../lib/serviceResult';
import {isNotFound} from '../../lib/s3Errors';
import type {ServiceResult} from '../../types/service.types';
import type {DataQualityReport} from './dataQuality.types';

/** The folder `assemble-report` writes into, hidden from the browser (FR-004). */
export const REPORTS_FOLDER = '_data-quality-reports';

/**
 * `{space}/_data-quality-reports/{requestId}/report.json` — the same key
 * `dq_assemble_report.report_key` builds, and a pure function of the request id.
 *
 * @param space - The space NAME: the username for a personal space, the shared-space
 *   name for a shared one. It is also the space's root prefix in its bucket.
 */
export function reportKey(space: string, requestId: string): string {
  return `${space}/${REPORTS_FOLDER}/${requestId}/report.json`;
}

/**
 * Is this a report document rather than some other JSON that happens to live at the key?
 *
 * Checked STRUCTURALLY, on the fields every render path indexes into. The report is
 * machine-written so a partial document should be impossible — but the alternative to
 * this check is a page that throws mid-render on `report.exact.columns.map`, which is a
 * blank screen rather than the friendly empty state FR-005 requires.
 */
function isReport(doc: unknown): doc is DataQualityReport {
  const r = doc as Partial<DataQualityReport> | null;
  return (
    !!r &&
    typeof r === 'object' &&
    typeof r.requestId === 'string' &&
    (r.verdict === 'clean' || r.verdict === 'issues_found') &&
    !!r.exact &&
    Array.isArray(r.exact.columns) &&
    !!r.approximate
  );
}

/**
 * Read one report. A missing object and a malformed one both surface as a typed failure
 * rather than an empty success: unlike the notifications inbox, "not there" is NOT a
 * legitimate empty state here — the user followed a link to a specific report, so the
 * honest answer is that this report can't be shown, not that it is empty and clean.
 *
 * The caller passes the bucket it resolved from the space; this service never guesses one.
 */
export async function getQualityReport(
  bucket: string,
  space: string,
  requestId: string
): Promise<ServiceResult<DataQualityReport>> {
  return withCredentialRetry(getS3Client, async (client) => {
    try {
      const response = await client.send(new GetObjectCommand({Bucket: bucket, Key: reportKey(space, requestId)}));
      const body = await response.Body?.transformToString();
      const parsed: unknown = body ? JSON.parse(body) : null;
      if (!isReport(parsed)) {
        return {
          success: false,
          error: {message: 'That report could not be read.', code: 'DataQualityReportUnreadable'}
        };
      }
      return {success: true, data: parsed};
    } catch (err) {
      if (isNotFound(err)) {
        return {
          success: false,
          error: {message: 'That report could not be found.', code: 'DataQualityReportNotFound'}
        };
      }
      // A body that isn't JSON at all lands here as a SyntaxError; it is the same
      // user-facing outcome as a structurally-invalid one.
      if (err instanceof SyntaxError) {
        return {
          success: false,
          error: {message: 'That report could not be read.', code: 'DataQualityReportUnreadable'}
        };
      }
      return toServiceError(err, 'Failed to load the data quality report');
    }
  });
}
