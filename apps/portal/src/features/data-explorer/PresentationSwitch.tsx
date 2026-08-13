import {SegmentedFilter} from '../../components/SegmentedFilter';
import type {GridPresentation} from './dataExplorer.types';

const OPTIONS = [
  {value: 'grid', label: 'Grid'},
  {value: 'record', label: 'Record'},
  {value: 'text', label: 'Text'}
] as const satisfies readonly {value: GridPresentation; label: string}[];

export type PresentationSwitchProps = {
  value: GridPresentation;
  onChange: (next: GridPresentation) => void;
};

/**
 * Grid / Record / Text (SPEC-180 FR-004, FR-005).
 *
 * Three presentations of rows that have ALREADY been fetched, so switching runs no query
 * — the same rule that makes column geometry free. `SegmentedFilter` carries the choice
 * in `aria-pressed`, never in styling alone.
 */
export function PresentationSwitch({value, onChange}: PresentationSwitchProps) {
  return (
    <SegmentedFilter
      label="Presentation"
      options={OPTIONS}
      value={value}
      onChange={onChange}
    />
  );
}
