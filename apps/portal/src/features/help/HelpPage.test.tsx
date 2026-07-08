import {describe, it, expect, afterEach} from 'vitest';
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
