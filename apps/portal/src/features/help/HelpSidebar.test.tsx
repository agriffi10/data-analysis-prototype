import {describe, it, expect, vi} from 'vitest';
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
});
