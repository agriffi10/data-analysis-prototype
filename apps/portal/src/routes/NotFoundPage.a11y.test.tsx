import {describe, it, expect, vi} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {expectNoA11yViolations, ROUTE_AXE_OPTIONS} from '../test/axe';

vi.mock('../hooks/usePageTitle', () => ({usePageTitle: vi.fn()}));

const {default: NotFoundPage} = await import('./NotFoundPage');

const tree = (
  <MemoryRouter>
    <NotFoundPage />
  </MemoryRouter>
);

describe('NotFoundPage accessibility (SPEC-045 FR-003)', () => {
  it('has no axe violations', async () => {
    await expectNoA11yViolations(tree, ROUTE_AXE_OPTIONS);
  });

  it('exposes exactly one <h1> and a <main> landmark', () => {
    render(tree);
    expect(screen.getAllByRole('heading', {level: 1})).toHaveLength(1);
    expect(screen.getByRole('main')).toBeInTheDocument();
  });
});
