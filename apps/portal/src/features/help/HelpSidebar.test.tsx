import {describe, it, expect, vi, afterEach} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {HelpSidebar} from './HelpSidebar';
import type {HelpSection} from './help.types';

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
