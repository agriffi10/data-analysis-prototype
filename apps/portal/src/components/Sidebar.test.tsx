import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent, within} from '@testing-library/react';
import {MemoryRouter} from 'react-router';
import {Sidebar} from './Sidebar';
import type {Connection} from '../features/query/query.types';

const personal: Connection = {id: 'personal', label: 'alice', database: 'alice', kind: 'personal'};
const activeShared: Connection = {
  id: 'marketing_data',
  label: 'marketing_data',
  database: 'marketing_data',
  kind: 'shared',
  status: 'active',
  role: 'member'
};
const pendingShared: Connection = {
  id: 'sales_2026',
  label: 'sales_2026',
  database: 'sales_2026',
  kind: 'shared',
  status: 'provisioning',
  role: 'owner'
};

const renderSidebar = (connections: Connection[], activeSpaceId = 'personal', onSelectSpace = vi.fn()) =>
  render(
    <MemoryRouter initialEntries={['/files']}>
      <Sidebar
        connections={connections}
        activeSpaceId={activeSpaceId}
        onSelectSpace={onSelectSpace}
      />
    </MemoryRouter>
  );

describe('Sidebar (SPEC-057)', () => {
  it('lists the personal space (by username) plus shared connections', () => {
    renderSidebar([personal, activeShared]);
    expect(screen.getByText('Spaces')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: /alice/i})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: /marketing_data/i})).toBeInTheDocument();
  });

  it('marks the active space with aria-current', () => {
    renderSidebar([personal, activeShared], 'marketing_data');
    expect(screen.getByRole('button', {name: /marketing_data/i})).toHaveAttribute('aria-current', 'true');
    expect(screen.getByRole('button', {name: /alice/i})).not.toHaveAttribute('aria-current');
  });

  it('selecting a usable space calls onSelectSpace with its id', () => {
    const onSelectSpace = vi.fn();
    renderSidebar([personal, activeShared], 'personal', onSelectSpace);
    fireEvent.click(screen.getByRole('button', {name: /marketing_data/i}));
    expect(onSelectSpace).toHaveBeenCalledWith('marketing_data');
  });

  it('renders provisioning/failed shared connections disabled with their status', () => {
    const onSelectSpace = vi.fn();
    renderSidebar([personal, pendingShared], 'personal', onSelectSpace);
    const btn = screen.getByRole('button', {name: /sales_2026/i});
    expect(btn).toBeDisabled();
    expect(screen.getByText('Provisioning…')).toBeInTheDocument();
    fireEvent.click(btn);
    expect(onSelectSpace).not.toHaveBeenCalled();
  });

  it('a personal-only user sees just their own space', () => {
    renderSidebar([personal]);
    // Exactly one space entry (the collapse control is rail chrome, not a space).
    const list = screen.getByRole('list', {name: 'Spaces'});
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
    expect(screen.getByRole('button', {name: /alice/i})).toBeInTheDocument();
  });

  it('does not render a manage-connections link (managing lives on the Connections tab)', () => {
    renderSidebar([personal]);
    expect(screen.queryByRole('link', {name: /manage connections/i})).not.toBeInTheDocument();
  });
});
