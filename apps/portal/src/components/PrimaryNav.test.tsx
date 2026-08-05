import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router';
import {PrimaryNav} from './PrimaryNav';

describe('PrimaryNav (SPEC-035 + SPEC-052)', () => {
  it('renders Files, Query, Connections and Data quality tabs with their routes', () => {
    render(
      <MemoryRouter>
        <PrimaryNav />
      </MemoryRouter>
    );
    expect(screen.getByRole('link', {name: 'Files'})).toHaveAttribute('href', '/files');
    expect(screen.getByRole('link', {name: 'Query'})).toHaveAttribute('href', '/query');
    expect(screen.getByRole('link', {name: 'Connections'})).toHaveAttribute('href', '/connections');
    // SPEC-123 FR-004: the runs dashboard is a primary destination, after Connections.
    expect(screen.getByRole('link', {name: 'Data quality'})).toHaveAttribute('href', '/data-quality');
  });

  it('orders Data quality last, after Connections', () => {
    render(
      <MemoryRouter>
        <PrimaryNav />
      </MemoryRouter>
    );
    expect(screen.getAllByRole('link').map((link) => link.textContent)).toEqual([
      'Files',
      'Query',
      'Connections',
      'Data quality'
    ]);
  });

  it('marks the Data quality tab active on its own route', () => {
    render(
      <MemoryRouter initialEntries={['/data-quality']}>
        <PrimaryNav />
      </MemoryRouter>
    );
    expect(screen.getByRole('link', {name: 'Data quality'})).toHaveAttribute('aria-current', 'page');
  });

  it('marks the active tab via aria-current', () => {
    render(
      <MemoryRouter initialEntries={['/connections']}>
        <PrimaryNav />
      </MemoryRouter>
    );
    expect(screen.getByRole('link', {name: 'Connections'})).toHaveAttribute('aria-current', 'page');
  });
});
