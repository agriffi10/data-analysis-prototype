import { describe, it, expect, vi, type MockedFunction } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import type { AuthContextValue } from '../features/auth';

vi.mock('../features/auth', () => ({ useAuth: vi.fn() }));

import { useAuth } from '../features/auth';

const mockUseAuth = useAuth as unknown as MockedFunction<() => AuthContextValue>;

const authValue = (username: string | null): AuthContextValue => ({
  status: username ? 'authenticated' : 'unauthenticated',
  user: username ? { username } : null,
  error: null,
  signIn: vi.fn(),
  signUp: vi.fn(),
  signOut: vi.fn(),
});

const renderSidebar = () =>
  render(
    <MemoryRouter initialEntries={['/files']}>
      <Sidebar />
    </MemoryRouter>
  );

describe('Sidebar', () => {
  it('shows the My Files section and the username as a link to /files', () => {
    mockUseAuth.mockReturnValue(authValue('alice'));
    renderSidebar();

    expect(screen.getByText('My Files')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /alice/i });
    expect(link).toHaveAttribute('href', '/files');
  });

  it('falls back to a generic label when there is no user (dev-unauth)', () => {
    mockUseAuth.mockReturnValue(authValue(null));
    renderSidebar();

    // "My Files" appears as the section label; the link reuses it as the label.
    expect(screen.getAllByText('My Files').length).toBeGreaterThan(0);
    expect(screen.getByRole('link')).toHaveAttribute('href', '/files');
  });
});
