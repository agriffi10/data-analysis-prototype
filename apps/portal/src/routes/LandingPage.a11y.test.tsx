import {describe, it, expect, beforeEach} from 'vitest';
import {screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {AuthContext} from '../features/auth/authContext';
import {unauthenticated} from '../test/authFixtures';
import {renderWithProviders} from '../test/renderWithProviders';
import {expectNoA11yViolations, ROUTE_AXE_OPTIONS} from '../test/axe';
import LandingPage from './LandingPage';

// Integration style (react.md §21): render the REAL LandingPage in the signed-out
// state (authenticated visitors are redirected away). No AWS boundary to mock; auth
// is injected via AuthContext. `expectNoA11yViolations` renders the node itself, so
// the router + auth providers are composed inline here.
const signedOut = (
  <AuthContext.Provider value={unauthenticated()}>
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>
  </AuthContext.Provider>
);

beforeEach(() => {
  sessionStorage.clear();
});

describe('LandingPage accessibility (SPEC-045 FR-003)', () => {
  it('has no axe violations', async () => {
    await expectNoA11yViolations(signedOut, ROUTE_AXE_OPTIONS);
  });

  it('exposes exactly one <h1> and a <main> landmark', () => {
    renderWithProviders(<LandingPage />, {route: '/', auth: unauthenticated()});
    expect(screen.getAllByRole('heading', {level: 1})).toHaveLength(1);
    expect(screen.getByRole('main')).toBeInTheDocument();
  });
});
