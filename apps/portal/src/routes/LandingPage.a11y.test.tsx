import {describe, it, expect, vi} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {expectNoA11yViolations, ROUTE_AXE_OPTIONS} from '../test/axe';

// Unauthenticated visitor sees the marketing landing page (authenticated users
// are redirected away). Keep the auth mock in the "unauthenticated" state.
vi.mock('../features/auth', () => ({
  useAuth: () => ({status: 'unauthenticated', signIn: vi.fn(), signUp: vi.fn()})
}));
vi.mock('../hooks/usePageTitle', () => ({usePageTitle: vi.fn()}));

const {default: LandingPage} = await import('./LandingPage');

function renderLanding() {
  return (
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>
  );
}

describe('LandingPage accessibility (SPEC-045 FR-003)', () => {
  it('has no axe violations', async () => {
    await expectNoA11yViolations(renderLanding(), ROUTE_AXE_OPTIONS);
  });

  it('exposes exactly one <h1> and a <main> landmark', () => {
    render(renderLanding());
    expect(screen.getAllByRole('heading', {level: 1})).toHaveLength(1);
    expect(screen.getByRole('main')).toBeInTheDocument();
  });
});
