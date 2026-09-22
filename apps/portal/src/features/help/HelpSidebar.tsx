import {cx} from '../../lib/cx';
import {useBreakpoint} from '../../lib/useBreakpoint';
import {helpIcons} from './helpIcons';
import type {HelpSection, HelpSectionId} from './help.types';
import {SECTION_CAPTION} from '../../components/fieldStyles';

type HelpSidebarProps = {
  sections: HelpSection[];
  activeId: HelpSectionId;
  onSelect: (id: HelpSectionId) => void;
};

// Presentation-only compact labels for the narrowed tablet rail.
// Full labels are shown at desktop; not part of the content model (`helpContent.ts`).
const SHORT_SECTION_LABELS: Partial<Record<HelpSectionId, string>> = {
  'shared-connections': 'Shared'
};

/**
 * Left rail for the Help page — mirrors the app-shell `Sidebar` (248px surface
 * panel, right hairline, filled active item, hidden below `tablet`). One item per
 * section with its feature icon, label, and a right-aligned guide count derived
 * from the content. Selection drives the active section.
 *
 * @example
 * <HelpSidebar sections={HELP_SECTIONS} activeId={activeId} onSelect={setActiveId} />
 */
export function HelpSidebar({sections, activeId, onSelect}: HelpSidebarProps) {
  // Full labels at desktop; compact labels at the narrower tablet rail. Picked in
  // JS (not two CSS spans) so the button's accessible name is never doubled.
  const {isDesktop} = useBreakpoint();

  return (
    <aside
      aria-label="Guides navigation"
      className="hidden w-[220px] shrink-0 flex-col gap-1 overflow-y-auto border-r border-border bg-surface px-3 py-4 tablet:flex desktop:w-[248px]">
      <p className={`px-3 pb-2 pt-3 ${SECTION_CAPTION}`}>Guides</p>
      <ul
        role="list"
        className="flex flex-col gap-0.5">
        {sections.map((section) => {
          const Icon = helpIcons[section.icon];
          const active = section.id === activeId;
          return (
            <li key={section.id}>
              <button
                type="button"
                aria-current={active ? 'true' : undefined}
                onClick={() => onSelect(section.id)}
                className={cx(
                  'flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-base font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                  active ? 'bg-accent-soft text-accent-text' : 'text-text-2 hover:bg-surface-2 hover:text-text'
                )}>
                <Icon className="h-[18px] w-[18px] flex-none" />
                <span className="min-w-0 flex-1 truncate">
                  {isDesktop ? section.label : (SHORT_SECTION_LABELS[section.id] ?? section.label)}
                </span>
                <span
                  className={cx('ml-auto flex-none text-xs font-medium', active ? 'text-accent-text' : 'text-text-3')}>
                  {section.guides.length}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
