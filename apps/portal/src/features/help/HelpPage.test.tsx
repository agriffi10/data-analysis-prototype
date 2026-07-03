import {describe, it, expect} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {HelpPage} from './HelpPage';
import {HELP_SECTIONS} from './helpContent';

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <HelpPage />
    </MemoryRouter>
  );
}

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
});
