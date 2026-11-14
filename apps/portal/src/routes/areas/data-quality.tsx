import {FeatureRoute} from '../FeatureRoute';
import DataQualityPage from '../DataQualityPage';
import DataQualityReportPage from '../DataQualityReportPage';

/**
 * The data-quality runs dashboard, at `/data-quality`. Eager, as the report view is.
 *
 * @returns The dashboard behind its flag.
 */
export function DataQualityView() {
  return (
    <FeatureRoute flag="dataQuality">
      <DataQualityPage />
    </FeatureRoute>
  );
}

/**
 * One run's report, at `/data-quality/:space/:requestId`, reached from the dashboard or from a
 * notification's deep link. The space is in the path because a request id alone does not say which
 * space holds the report. Eager: it reuses the storage client Files already pulls in.
 *
 * The gate matters MORE here than on the dashboard: this page reads a report on mount, so a page
 * that mounted before the flag resolved would turn a disabled feature into an existence oracle for
 * someone else's report, the exact disclosure the path is designed to avoid.
 *
 * @returns The report behind its flag.
 */
export function DataQualityReportView() {
  return (
    <FeatureRoute flag="dataQuality">
      <DataQualityReportPage />
    </FeatureRoute>
  );
}
