import {useEffect} from 'react';
import {useLocation, useNavigate} from 'react-router-dom';
import {PageLayout} from '../../components/PageLayout';
import {usePageTitle} from '../../hooks/usePageTitle';
import {HelpGuideCard} from './HelpGuideCard';
import {HelpSidebar} from './HelpSidebar';
import {HELP_SECTIONS} from './helpContent';
import type {HelpSectionId} from './help.types';

function sectionFromHash(hash: string): HelpSectionId {
  const id = hash.replace(/^#/, '');
  const match = HELP_SECTIONS.find((s) => s.id === id);
  return match ? match.id : HELP_SECTIONS[0].id;
}

/**
 * The Help & guides page (SPEC-074): a section sidebar beside the active
 * section's guides as accordion cards. The active section lives in the URL hash
 * (`/help#query`) so it's shareable and back/forward moves between sections
 * (FR-002/003/004). Static content — no loading/error/network states.
 *
 * @example
 * <HelpPage />
 */
export function HelpPage() {
  usePageTitle('Help & guides');

  const {hash} = useLocation();
  const navigate = useNavigate();
  const activeId = sectionFromHash(hash);
  const section = HELP_SECTIONS.find((s) => s.id === activeId) ?? HELP_SECTIONS[0];

  // Reset the content panel to the top when the section changes so a long
  // scroll position doesn't carry over (FR-003).
  useEffect(() => {
    document.getElementById('main')?.scrollTo?.({top: 0});
  }, [activeId]);

  const selectSection = (id: HelpSectionId) => {
    if (id !== activeId) navigate(`#${id}`);
  };

  return (
    <div className="flex min-h-0 flex-1">
      <HelpSidebar
        sections={HELP_SECTIONS}
        activeId={activeId}
        onSelect={selectSection}
      />
      <PageLayout
        title={section.label}
        subtitle={section.subtitle}
        contentClassName="max-w-[820px] gap-2.5">
        {section.guides.length === 0 ? (
          <p className="py-12 text-center text-sm text-text-3">No guides in this section yet.</p>
        ) : (
          section.guides.map((guide, i) => (
            <HelpGuideCard
              key={guide.id}
              guide={guide}
              iconName={section.icon}
              defaultOpen={i === 0}
            />
          ))
        )}
      </PageLayout>
    </div>
  );
}
