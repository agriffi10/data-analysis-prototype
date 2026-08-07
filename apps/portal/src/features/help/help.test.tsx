import {afterEach, describe, expect, it, vi} from 'vitest';
import {fireEvent, render, screen} from '@testing-library/react';
import {HelpGuideCard} from './HelpGuideCard';
import {MemoryRouter} from 'react-router';
import {HelpPage} from './HelpPage';
import {HELP_SECTIONS} from './helpContent';
import {COMPONENT_AXE_OPTIONS, ROUTE_AXE_OPTIONS, expectNoA11yViolations} from '../../test/axe';
import {HelpLink} from './HelpLink';
import {HelpSectionChips} from './HelpSectionChips';
import {HelpSidebar} from './HelpSidebar';
import type {HelpGuide, HelpSection} from './help.types';

// ─── from HelpGuideCard.test.tsx ───
describe('HelpGuideCard', () => {
  const guide: HelpGuide = {
    id: 'upload-files',
    title: 'Upload files',
    subtitle: 'Add files from your computer.',
    steps: ['Open the <b>Files</b> tab.', 'Click <b>Upload</b>.'],
    callout: {kind: 'warning', text: 'Use <b>Cancel</b> to back out.'}
  };

  describe('HelpGuideCard (SPEC-074 FR-004)', () => {
    it('renders a collapsed card by default — title/subtitle visible, steps hidden', () => {
      render(
        <HelpGuideCard
          guide={guide}
          iconName="files"
        />
      );
      const header = screen.getByRole('button', {name: /Upload files/});
      expect(header).toHaveAttribute('aria-expanded', 'false');
      expect(screen.getByText('Add files from your computer.')).toBeInTheDocument();
      expect(screen.queryByRole('list')).not.toBeInTheDocument();
    });

    it('toggles open on click, revealing numbered steps and the callout', () => {
      render(
        <HelpGuideCard
          guide={guide}
          iconName="files"
        />
      );
      const header = screen.getByRole('button', {name: /Upload files/});
      fireEvent.click(header);
      expect(header).toHaveAttribute('aria-expanded', 'true');
      expect(header).toHaveAttribute('aria-controls');
      const steps = screen.getByRole('list');
      expect(steps).toBeInTheDocument();
      expect(screen.getAllByRole('listitem')).toHaveLength(2);
      // Inline <b> is parsed to <strong>, not rendered as literal markup.
      expect(screen.getByText('Files')).toBeInTheDocument();
      expect(screen.queryByText(/<b>/)).not.toBeInTheDocument();
      // Warning callout prefix present.
      expect(screen.getByText(/Careful\./)).toBeInTheDocument();
      // Callout text is parsed too — <b> becomes <strong>, never literal markup.
      const cancel = screen.getByText('Cancel');
      expect(cancel.tagName).toBe('STRONG');
      expect(screen.queryByText(/<b>Cancel<\/b>/)).not.toBeInTheDocument();
    });

    it('honors defaultOpen', () => {
      render(
        <HelpGuideCard
          guide={guide}
          iconName="files"
          defaultOpen
        />
      );
      expect(screen.getByRole('button', {name: /Upload files/})).toHaveAttribute('aria-expanded', 'true');
    });

    it('renders no callout when the guide has none', async () => {
      render(
        <HelpGuideCard
          guide={{...guide, callout: undefined}}
          iconName="files"
          defaultOpen
        />
      );
      expect(screen.queryByText(/Careful\./)).not.toBeInTheDocument();
      expect(screen.queryByText(/Tip\./)).not.toBeInTheDocument();
    });
  });
});

// ─── from HelpPage.test.tsx ───
describe('HelpPage', () => {
  function renderAt(path: string) {
    return render(
      <MemoryRouter initialEntries={[path]}>
        <HelpPage />
      </MemoryRouter>
    );
  }

  function setWidth(w: number) {
    Object.defineProperty(window, 'innerWidth', {value: w, writable: true, configurable: true});
  }

  afterEach(() => setWidth(1024));

  describe('HelpPage (SPEC-074 FR-002/003)', () => {
    it('activates the first section by default (no hash)', () => {
      renderAt('/help');
      expect(screen.getByRole('heading', {level: 1})).toHaveTextContent(HELP_SECTIONS[0].label);
      expect(screen.getByRole('button', {name: new RegExp(HELP_SECTIONS[0].label)})).toHaveAttribute(
        'aria-current',
        'true'
      );
    });

    it('activates the section named by the URL hash', () => {
      renderAt('/help#query');
      expect(screen.getByRole('heading', {level: 1})).toHaveTextContent('Query');
    });

    it('falls back to the first section for an unknown hash', () => {
      renderAt('/help#does-not-exist');
      expect(screen.getByRole('heading', {level: 1})).toHaveTextContent(HELP_SECTIONS[0].label);
    });

    it('switches sections when a sidebar item is selected', () => {
      renderAt('/help');
      fireEvent.click(screen.getByRole('button', {name: /Notifications/}));
      expect(screen.getByRole('heading', {level: 1})).toHaveTextContent('Notifications');
    });

    it('opens the first guide of a section by default', () => {
      renderAt('/help');
      const firstGuide = HELP_SECTIONS[0].guides[0];
      expect(screen.getByRole('button', {name: new RegExp(firstGuide.title)})).toHaveAttribute('aria-expanded', 'true');
    });

    // ── SPEC-103: responsive section selector ──────────────────────────────────

    it('shows the rail (not chips) at ≥ tablet, and chips (not rail) on mobile', () => {
      setWidth(1024);
      const {unmount} = renderAt('/help');
      expect(screen.getByRole('complementary', {name: 'Guides navigation'})).toBeInTheDocument();
      expect(screen.queryByRole('navigation', {name: 'Guides sections'})).not.toBeInTheDocument();
      unmount();

      setWidth(400);
      renderAt('/help');
      expect(screen.getByRole('navigation', {name: 'Guides sections'})).toBeInTheDocument();
      expect(screen.queryByRole('complementary', {name: 'Guides navigation'})).not.toBeInTheDocument();
    });

    it('selects a section from the mobile chips via the hash path', () => {
      setWidth(400);
      renderAt('/help');
      fireEvent.click(screen.getByRole('button', {name: 'Query'}));
      expect(screen.getByRole('heading', {level: 1})).toHaveTextContent('Query');
    });

    it('renders no search control at any breakpoint (FR-005)', () => {
      for (const w of [400, 1024, 1400]) {
        setWidth(w);
        const {unmount} = renderAt('/help');
        expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', {name: /search/i})).not.toBeInTheDocument();
        expect(screen.queryByPlaceholderText(/search/i)).not.toBeInTheDocument();
        unmount();
      }
    });
  });
});

// ─── from HelpPage.a11y.test.tsx ───
describe('HelpPage.a11y', () => {
  const page = (
    <MemoryRouter initialEntries={['/help']}>
      <HelpPage />
    </MemoryRouter>
  );

  describe('Help page accessibility (SPEC-074 FR-006 / SPEC-045)', () => {
    it('has no axe violations with the first section rendered (first guide expanded)', async () => {
      await expectNoA11yViolations(page, ROUTE_AXE_OPTIONS);
    });

    it('exposes exactly one <h1> and a <main> landmark', () => {
      render(page);
      expect(screen.getAllByRole('heading', {level: 1})).toHaveLength(1);
      expect(screen.getByRole('main')).toBeInTheDocument();
    });

    it('gives the header help link an accessible name (FR-001)', async () => {
      await expectNoA11yViolations(
        <MemoryRouter>
          <HelpLink />
        </MemoryRouter>,
        COMPONENT_AXE_OPTIONS
      );
      render(
        <MemoryRouter>
          <HelpLink />
        </MemoryRouter>
      );
      expect(screen.getByRole('link', {name: 'Help & guides'})).toBeInTheDocument();
    });
  });
});

// ─── from HelpSectionChips.test.tsx ───
describe('HelpSectionChips', () => {
  const sections: HelpSection[] = [
    {
      id: 'files',
      label: 'Files',
      subtitle: '',
      icon: 'files',
      guides: [{id: 'a', title: 'A', subtitle: '', steps: ['x']}]
    },
    {
      id: 'query',
      label: 'Query',
      subtitle: '',
      icon: 'query',
      guides: [{id: 'c', title: 'C', subtitle: '', steps: ['x']}]
    },
    {
      id: 'shared-connections',
      label: 'Shared connections',
      subtitle: '',
      icon: 'connections',
      guides: [{id: 'd', title: 'D', subtitle: '', steps: ['x']}]
    }
  ];

  describe('HelpSectionChips (SPEC-103 FR-003)', () => {
    it('renders a labelled nav with one chip per section (full labels)', () => {
      render(
        <HelpSectionChips
          sections={sections}
          activeId="files"
          onSelect={vi.fn()}
        />
      );
      const nav = screen.getByRole('navigation', {name: 'Guides sections'});
      expect(nav).toBeInTheDocument();
      expect(nav).toHaveClass('overflow-x-auto');
      expect(screen.getAllByRole('button')).toHaveLength(3);
      expect(screen.getByRole('button', {name: 'Shared connections'})).toBeInTheDocument();
    });

    it('highlights exactly the active section chip', () => {
      render(
        <HelpSectionChips
          sections={sections}
          activeId="query"
          onSelect={vi.fn()}
        />
      );
      expect(screen.getByRole('button', {name: 'Query'})).toHaveAttribute('aria-current', 'true');
      expect(screen.getByRole('button', {name: 'Files'})).not.toHaveAttribute('aria-current');
      expect(screen.getAllByRole('button').filter((b) => b.getAttribute('aria-current') === 'true')).toHaveLength(1);
    });

    it('calls onSelect with the section id when a chip is activated', () => {
      const onSelect = vi.fn();
      render(
        <HelpSectionChips
          sections={sections}
          activeId="files"
          onSelect={onSelect}
        />
      );
      fireEvent.click(screen.getByRole('button', {name: 'Shared connections'}));
      expect(onSelect).toHaveBeenCalledWith('shared-connections');
    });

    it('keeps chips on a single line (no wrap)', () => {
      render(
        <HelpSectionChips
          sections={sections}
          activeId="files"
          onSelect={vi.fn()}
        />
      );
      for (const chip of screen.getAllByRole('button')) {
        expect(chip).toHaveClass('shrink-0', 'whitespace-nowrap');
      }
    });

    it('has no a11y violations', async () => {
      await expectNoA11yViolations(
        <HelpSectionChips
          sections={sections}
          activeId="files"
          onSelect={vi.fn()}
        />,
        COMPONENT_AXE_OPTIONS
      );
    });
  });
});

// ─── from HelpSidebar.test.tsx ───
describe('HelpSidebar', () => {
  const sections: HelpSection[] = [
    {
      id: 'files',
      label: 'Files',
      subtitle: 'files sub',
      icon: 'files',
      guides: [
        {id: 'a', title: 'A', subtitle: '', steps: ['x']},
        {id: 'b', title: 'B', subtitle: '', steps: ['x']}
      ]
    },
    {
      id: 'query',
      label: 'Query',
      subtitle: 'query sub',
      icon: 'query',
      guides: [{id: 'c', title: 'C', subtitle: '', steps: ['x']}]
    }
  ];

  // A section whose short label differs from its full label (SPEC-103 FR-002).
  const sharedSection: HelpSection[] = [
    {
      id: 'shared-connections',
      label: 'Shared connections',
      subtitle: 'shared sub',
      icon: 'connections',
      guides: [{id: 'd', title: 'D', subtitle: '', steps: ['x']}]
    }
  ];

  function setWidth(w: number) {
    Object.defineProperty(window, 'innerWidth', {value: w, writable: true, configurable: true});
  }

  afterEach(() => setWidth(1024));

  describe('HelpSidebar (SPEC-074 FR-003)', () => {
    it('renders one item per section with a guide count derived from content', () => {
      render(
        <HelpSidebar
          sections={sections}
          activeId="files"
          onSelect={vi.fn()}
        />
      );
      const items = screen.getAllByRole('button');
      expect(items).toHaveLength(2);
      expect(items[0]).toHaveTextContent('Files');
      expect(items[0]).toHaveTextContent('2');
      expect(items[1]).toHaveTextContent('Query');
      expect(items[1]).toHaveTextContent('1');
    });

    it('marks the active section with aria-current', () => {
      render(
        <HelpSidebar
          sections={sections}
          activeId="query"
          onSelect={vi.fn()}
        />
      );
      expect(screen.getByRole('button', {name: /Query/})).toHaveAttribute('aria-current', 'true');
      expect(screen.getByRole('button', {name: /Files/})).not.toHaveAttribute('aria-current');
    });

    it('calls onSelect with the section id when clicked', async () => {
      const onSelect = vi.fn();
      render(
        <HelpSidebar
          sections={sections}
          activeId="files"
          onSelect={onSelect}
        />
      );
      fireEvent.click(screen.getByRole('button', {name: /Query/}));
      expect(onSelect).toHaveBeenCalledWith('query');
    });

    // ── SPEC-103 FR-002: narrowed tablet rail with short labels ────────────────

    it('renders the short section label at tablet width', () => {
      setWidth(1000); // tablet band (< desktop)
      render(
        <HelpSidebar
          sections={sharedSection}
          activeId="shared-connections"
          onSelect={vi.fn()}
        />
      );
      expect(screen.getByText('Shared')).toBeInTheDocument();
      expect(screen.queryByText('Shared connections')).not.toBeInTheDocument();
    });

    it('renders the full section label at desktop width', () => {
      setWidth(1400); // desktop
      render(
        <HelpSidebar
          sections={sharedSection}
          activeId="shared-connections"
          onSelect={vi.fn()}
        />
      );
      expect(screen.getByText('Shared connections')).toBeInTheDocument();
    });
  });
});
