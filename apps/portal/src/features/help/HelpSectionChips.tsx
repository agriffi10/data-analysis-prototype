import {cx} from '../../lib/cx';
import type {HelpSection, HelpSectionId} from './help.types';

type HelpSectionChipsProps = {
  sections: HelpSection[];
  activeId: HelpSectionId;
  onSelect: (id: HelpSectionId) => void;
};

/**
 * Mobile (`< tablet`) section selector for the Help page — a horizontal,
 * `overflow-x-auto` single row of chips replacing the vertical rail.
 * The active section's chip is highlighted; selecting one drives the
 * same URL-hash `onSelect` path the rail uses. Mount-gated by `HelpPage`
 * to mobile only, so it and the rail are never both in the layout.
 *
 * @example
 * <HelpSectionChips sections={HELP_SECTIONS} activeId={activeId} onSelect={selectSection} />
 */
export function HelpSectionChips({sections, activeId, onSelect}: HelpSectionChipsProps) {
  return (
    <nav
      aria-label="Guides sections"
      className="-mx-6 mb-1 flex gap-2 overflow-x-auto px-6 pb-1">
      {sections.map((section) => {
        const active = section.id === activeId;
        return (
          <button
            key={section.id}
            type="button"
            aria-current={active ? 'true' : undefined}
            onClick={() => onSelect(section.id)}
            className={cx(
              'shrink-0 whitespace-nowrap rounded-full border px-3.5 py-1.5 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
              active
                ? 'border-accent-border bg-accent-soft text-accent-text'
                : 'border-border bg-surface text-text-2 hover:bg-surface-2 hover:text-text'
            )}>
            {section.label}
          </button>
        );
      })}
    </nav>
  );
}
