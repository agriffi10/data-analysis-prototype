import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { PrimaryNav } from './PrimaryNav';

describe('PrimaryNav (SPEC-035 + SPEC-052)', () => {
  it('renders Files, Query, and Connections tabs with their routes', () => {
    render(
      <MemoryRouter>
        <PrimaryNav />
      </MemoryRouter>
    );
    expect(screen.getByRole('link', { name: 'Files' })).toHaveAttribute('href', '/files');
    expect(screen.getByRole('link', { name: 'Query' })).toHaveAttribute('href', '/query');
    expect(screen.getByRole('link', { name: 'Connections' })).toHaveAttribute('href', '/connections');
  });

  it('marks the active tab via aria-current', () => {
    render(
      <MemoryRouter initialEntries={['/connections']}>
        <PrimaryNav />
      </MemoryRouter>
    );
    expect(screen.getByRole('link', { name: 'Connections' })).toHaveAttribute('aria-current', 'page');
  });
});
