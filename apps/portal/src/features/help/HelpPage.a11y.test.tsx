import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router';
import {expectNoA11yViolations, ROUTE_AXE_OPTIONS, COMPONENT_AXE_OPTIONS} from '../../test/axe';
import {HelpPage} from './HelpPage';
import {HelpLink} from './HelpLink';

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
