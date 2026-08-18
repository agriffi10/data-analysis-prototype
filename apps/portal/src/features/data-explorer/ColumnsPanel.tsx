import {useState} from 'react';
import {Button} from '../../components/Button';
import {Drawer} from '../../components/Drawer';
import type {UseColumnGeometryResult} from './useColumnGeometry';

export type ColumnsPanelProps = {
  open: boolean;
  onClose: () => void;
  geometry: UseColumnGeometryResult;
};

/**
 * Hide/show, pin and reorder, away from the header row.
 *
 * It is a panel rather than a header menu because SPEC-181 owns the per-column header
 * menu, and because these are the gestures a keyboard user needs an alternative for: drag
 * has no keyboard equivalent, so **Move earlier / Move later** is that equivalent and the
 * live region below is where it is announced.
 *
 * Every refusal here rides `Button.disabledReason` — `aria-disabled`, so the control keeps
 * its place in the tab order and the reason is reachable rather than hover-only, and never
 * inside the button, where it would become part of the accessible name.
 */
export function ColumnsPanel({open, onClose, geometry}: ColumnsPanelProps) {
  const [announcement, setAnnouncement] = useState('');
  const {all, visible} = geometry;

  const move = (name: string, direction: -1 | 1) => {
    const column = all.find((c) => c.name === name);
    if (!column || geometry.moveRefusal(name, direction) !== null) return;
    // Position is announced within the column's own block, because that is what the move
    // is bounded by — a pinned column reorders among the pinned.
    const block = all.filter((c) => c.pinned === column.pinned);
    const at = block.findIndex((c) => c.name === name);
    geometry.move(name, direction);
    setAnnouncement(`${name} moved to position ${at + direction + 1} of ${block.length}.`);
  };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Columns"
      subtitle={`${visible.length} of ${all.length} shown`}>
      <p
        role="status"
        aria-live="polite"
        className="sr-only">
        {announcement}
      </p>
      <ul className="flex flex-col gap-1">
        {all.map((column) => (
          <li
            key={column.name}
            className="flex items-center gap-2 rounded-md border border-border px-3 py-2">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm text-text">{column.name}</span>
              <span className="block truncate font-mono text-[10px] text-text-3">{column.type}</span>
            </span>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Move ${column.name} earlier`}
              disabledReason={geometry.moveRefusal(column.name, -1) ?? undefined}
              onClick={() => move(column.name, -1)}>
              ↑
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Move ${column.name} later`}
              disabledReason={geometry.moveRefusal(column.name, 1) ?? undefined}
              onClick={() => move(column.name, 1)}>
              ↓
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`${column.pinned ? 'Unpin' : 'Pin'} ${column.name}`}
              onClick={() => {
                geometry.togglePinned(column.name);
                setAnnouncement(`${column.name} ${column.pinned ? 'unpinned' : 'pinned to the left'}.`);
              }}>
              {column.pinned ? 'Unpin' : 'Pin'}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`${column.hidden ? 'Show' : 'Hide'} ${column.name}`}
              disabledReason={geometry.hideRefusal(column.name) ?? undefined}
              onClick={() => {
                geometry.toggleHidden(column.name);
                setAnnouncement(`${column.name} ${column.hidden ? 'shown' : 'hidden'}.`);
              }}>
              {column.hidden ? 'Show' : 'Hide'}
            </Button>
          </li>
        ))}
      </ul>
    </Drawer>
  );
}
