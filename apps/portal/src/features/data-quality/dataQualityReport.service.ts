import {appManagedPrefix, DATA_QUALITY_REPORTS_FOLDER} from '../../lib/appManagedPaths';
import {readJsonDocument} from '../../lib/s3Json';
import type {ServiceResult} from '../../types/service.types';
import type {DataQualityReport} from './dataQuality.types';

/**
 * `{space}/_data-quality-reports/{requestId}/report.json` — the same key
 * `dq_assemble_report.report_key` builds, and a pure function of the request id.
 *
 * @param space - The space NAME: the username for a personal space, the shared-space
 *   name for a shared one. It is also the space's root prefix in its bucket.
 */
export function reportKey(space: string, requestId: string): string {
  return `${appManagedPrefix(`${space}/`, DATA_QUALITY_REPORTS_FOLDER)}${requestId}/report.json`;
}

/**
 * Is this a report document rather than some other JSON that happens to live at the key?
 *
 * Checked STRUCTURALLY, on the fields every render path indexes into. The report is
 * machine-written so a partial document should be impossible — but the alternative to
 * this check is a page that throws mid-render on `report.exact.columns.map`, which is a
 * blank screen rather than the friendly empty state the rule requires.
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
 * Interpret a report body. TOTAL: a body that isn't JSON at all and one that is JSON but
 * not a report are the same user-facing outcome, so the `SyntaxError` is caught here rather
 * than left to escape as an exception.
 */
function parseReport(body: string | undefined): ServiceResult<DataQualityReport> {
  const unreadable: ServiceResult<DataQualityReport> = {
    success: false,
    error: {message: 'That report could not be read.', code: 'DataQualityReportUnreadable'}
  };
  let parsed: unknown;
  try {
    parsed = body ? JSON.parse(body) : null;
  } catch {
    return unreadable;
  }
  return isReport(parsed) ? {success: true, data: parsed} : unreadable;
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
  return readJsonDocument<DataQualityReport>({
    bucket,
    key: reportKey(space, requestId),
    parse: parseReport,
    onMissing: () => ({
      success: false,
      error: {message: 'That report could not be found.', code: 'DataQualityReportNotFound'}
    }),
    fallbackMessage: 'Failed to load the data quality report'
  });
}
