'use client';
import dynamic from 'next/dynamic';

/** The runs view, reached client-only so the application graph is evaluated after the boot. */
const DataQualityView = dynamic(
  () => import('../../../routes/areas/data-quality').then((module) => module.DataQualityView),
  {ssr: false}
);

/**
 * The data-quality runs page, at `/data-quality`.
 *
 * @returns The runs view behind its flag.
 */
export default function DataQualityRunsPage() {
  return <DataQualityView />;
}
