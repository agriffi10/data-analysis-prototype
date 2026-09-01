import {Link} from 'react-router';
import {Drawer} from '../../components/Drawer';
import {HelpGuideCard} from './HelpGuideCard';
import {useVisibleHelpSections} from './visibleSections';
import type {HelpSectionId} from './help.types';

type HelpPanelProps = {
  /** Which section to render; resolved from the route by `useContextualHelp`. */
  sectionId: HelpSectionId;
  open: boolean;
  onClose: () => void;
};

/**
 * One help section's guides, over whatever route is mounted — the contextual half of Help &
 * guides. The route beneath stays mounted, so a half-filled form survives reading the guide.
 *
 * The section comes from the same flag-filtered set the full page renders, never from
 * `HELP_SECTIONS`: a panel reading the raw content would show a guide `/help` hides. An id
 * that is not in that set renders nothing — the control resolves to no section in that case
 * and navigates instead, so this is a guard, not a state a user reaches.
 *
 * Escape, the focus trap, focus restoration and backdrop dismissal all come from `Drawer`,
 * including the depth dispatch that would let a dialog opened inside it take Escape first.
 *
 * @example
 * <HelpPanel sectionId="files" open={open} onClose={close} />
 */
export function HelpPanel({sectionId, open, onClose}: HelpPanelProps) {
  const sections = useVisibleHelpSections();
  const section = sections.find((candidate) => candidate.id === sectionId);
  if (!section) return null;

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={section.label}
      subtitle={section.subtitle}
      closeLabel="Close help"
      mobileVariant="full-height"
      bodyClassName="gap-2.5"
      footer={
        <div className="shrink-0 border-t border-border px-5 py-3">
          {/* A standalone link has no height of its own: as a bare inline element its box is
              the font's content area — 15.5px here — not the 18px line box, which applies
              once it is no longer a bare inline box. Nothing sits next to it, so spacing
              alone already made that conformant; this is comfort rather than a fix. The 24
              is an accessibility THRESHOLD, not a spacing step, so it is written absolutely
              — a rem-derived step reads as 24.5px today and would fall under the threshold
              if the root ever shrank. */}
          <Link
            to={`/help#${section.id}`}
            className="inline-flex min-h-[24px] items-center text-sm font-medium text-accent-text underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            Open the full guide
          </Link>
        </div>
      }>
      {section.guides.map((guide, i) => (
        <HelpGuideCard
          key={guide.id}
          guide={guide}
          iconName={section.icon}
          defaultOpen={i === 0}
        />
      ))}
    </Drawer>
  );
}
