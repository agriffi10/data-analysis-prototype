import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {HelpSectionChips} from './HelpSectionChips';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';
import type {HelpSection} from './help.types';

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
