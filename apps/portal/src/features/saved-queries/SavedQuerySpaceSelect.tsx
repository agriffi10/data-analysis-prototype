import {useId} from 'react';
import {cx} from '../../lib/cx';
import type {QuerySpace} from '../catalog/catalog.types';

type Props = {
  spaces: QuerySpace[];
  /** The resolved space; null only while there is no space at all. */
  space: QuerySpace | null;
  onSelectSpace: (spaceId: string) => void;
  className?: string;
};

/**
 * SPEC-174 FR-001: the labelled space control the saved-queries surfaces open on —
 * the user's own space first, then each active shared space.
 *
 * Rendered even with one option: a control that appears once a user joins their first
 * shared space is a control they never learn to look for, and the label is what says
 * *whose* saved queries these are.
 */
export function SavedQuerySpaceSelect({spaces, space, onSelectSpace, className}: Props) {
  const selectId = useId();
  if (spaces.length === 0) return null;

  return (
    <div className={cx('flex items-center gap-2', className)}>
      <label
        htmlFor={selectId}
        className="flex-none text-sm text-text-2">
        Space
      </label>
      <select
        id={selectId}
        value={space?.id ?? ''}
        onChange={(e) => onSelectSpace(e.target.value)}
        className="h-9 min-w-0 flex-1 rounded-md border border-border bg-surface px-2 text-sm text-text focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
        {spaces.map((s) => (
          <option
            key={s.id}
            value={s.id}>
            {s.label}
          </option>
        ))}
      </select>
    </div>
  );
}
