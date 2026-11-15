'use client';
import dynamic from 'next/dynamic';
import {usePageTitleOnMount} from '../../../../../hooks/usePageTitle';

/** The report view, reached client-only so the application graph is evaluated after the boot. */
const DataQualityReportView = dynamic(
  () => import('../../../../../routes/areas/data-quality').then((module) => module.DataQualityReportView),
  {ssr: false}
);

/**
 * One run's report, at `/data-quality/<space>/<requestId>`. It takes no props: the view reads the
 * space and the request id through the seam, decoded, because a native navigation leaves a page's
 * `params` as they were.
 *
 * @returns The report view behind its flag.
 */
export default function DataQualityReportPage() {
  usePageTitleOnMount('Data quality report');
  return <DataQualityReportView />;
}
