import {describe, it, expect} from 'vitest';
import {screen} from '@testing-library/react';
import {renderWithProviders} from '../test/renderWithProviders';
import HelpPage from './HelpPage';

// Static content route (SPEC-074): the wrapper renders the real feature view,
// which owns the content + document title. No data layer / network to mock.
describe('HelpPage route', () => {
  it('renders the help feature with its first-section guide content', () => {
    renderWithProviders(<HelpPage />, {route: '/help'});

    // Default section is the first (Files); its first guide card is "Upload files"
    // (accordion header button, collapsed by default).
    expect(screen.getByRole('button', {name: /Upload files/})).toBeInTheDocument();
  });

  it('sets the page title', () => {
    renderWithProviders(<HelpPage />, {route: '/help'});
    expect(document.title).toMatch(/Help & guides/);
  });
});
