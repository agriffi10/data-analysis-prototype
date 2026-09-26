import {useState} from 'react';
import {Badge} from '../../components/Badge';
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
 * It is a panel rather than a header menu because the header menu owns the per-column
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
      <div className="mb-3 flex flex-wrap gap-2">
        <Button
          size="sm"
          disabledReason={all.some((column) => column.hidden) ? undefined : 'No column is hidden.'}
          onClick={() => {
            geometry.showAll();
            setAnnouncement('Every column shown.');
          }}>
          Show all
        </Button>
        <Button
          size="sm"
          disabledReason={all.some((column) => column.pinned) ? undefined : 'No column is pinned.'}
          onClick={() => {
            geometry.unpinAll();
            setAnnouncement('Every column unpinned.');
          }}>
          Unpin all
        </Button>
      </div>
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
            {/* A chip rather than a text button, because pinning is the one column property
                whose CURRENT state the user needs to read off the row — hidden is legible
                from the grid, pinned is not. The accessible name still names the ACTION and
                flips with the state, which is why there is no `aria-pressed` here: a toggle
                label that already changes, announced as pressed, says the state twice. It
                opens with the chip's own word, so a spoken "click Pinned" finds it (WCAG 2.5.3). */}
            <button
              type="button"
              aria-label={column.pinned ? `Pinned, unpin ${column.name}` : `Pin ${column.name}`}
              onClick={() => {
                geometry.togglePinned(column.name);
                setAnnouncement(`${column.name} ${column.pinned ? 'unpinned' : 'pinned to the left'}.`);
              }}
              // `h-8` matches the buttons either side and keeps the target above WCAG 2.2
              // SC 2.5.8's minimum, which the chip on its own would sit under.
              className="flex h-8 items-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
              <Badge className={column.pinned ? 'border-accent-border bg-accent-soft text-accent-text' : undefined}>
                {column.pinned ? 'Pinned' : 'Pin'}
              </Badge>
            </button>
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
