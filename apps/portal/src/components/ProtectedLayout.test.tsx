import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';
import {render, screen, cleanup} from '@testing-library/react';
import {MemoryRouter, Routes, Route} from 'react-router-dom';
import {ProtectedLayout} from './ProtectedLayout';
import type {AuthContextValue, AuthStatus} from '../features/auth';

vi.mock('../features/auth', () => ({useAuth: vi.fn()}));
vi.mock('../lib/returnPath', () => ({setReturnPath: vi.fn()}));

import {useAuth} from '../features/auth';
import {setReturnPath} from '../lib/returnPath';

const mockUseAuth = useAuth as unknown as MockedFunction<() => AuthContextValue>;
const mockSetReturnPath = setReturnPath as unknown as MockedFunction<(path: string) => void>;

// Build a full auth context value for a given status (Header reads the rest).
const authValue = (status: AuthStatus): AuthContextValue => ({
  status,
  user: status === 'authenticated' ? {username: 'alice'} : null,
  error: null,
  signIn: vi.fn(),
  signUp: vi.fn(),
  signOut: vi.fn()
});

// Mirror the App route tree: a public landing marker plus the protected /files
// child, entered at /files so the guard decides what mounts.
const renderAtFiles = () =>
  render(
    <MemoryRouter initialEntries={['/files']}>
      <Routes>
        <Route
          path="/"
          element={<div>LANDING PAGE</div>}
        />
        <Route element={<ProtectedLayout />}>
          <Route
            path="/files"
            element={<div>PROTECTED CONTENT</div>}
          />
        </Route>
      </Routes>
    </MemoryRouter>
  );

beforeEach(() => {
  vi.resetAllMocks();
});

afterEach(() => {
  cleanup();
});

describe('ProtectedLayout', () => {
  it('while loading: shows a loading indicator and never mounts protected content', () => {
    mockUseAuth.mockReturnValue(authValue('loading'));

    renderAtFiles();

    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.queryByText('PROTECTED CONTENT')).not.toBeInTheDocument();
    expect(screen.queryByText('LANDING PAGE')).not.toBeInTheDocument();
  });

  it('when unauthenticated: redirects to / and never mounts protected content', () => {
    mockUseAuth.mockReturnValue(authValue('unauthenticated'));

    renderAtFiles();

    expect(screen.getByText('LANDING PAGE')).toBeInTheDocument();
    expect(screen.queryByText('PROTECTED CONTENT')).not.toBeInTheDocument();
  });

  it('when unauthenticated: stores the attempted path as the return path', () => {
    mockUseAuth.mockReturnValue(authValue('unauthenticated'));

    renderAtFiles();

    expect(mockSetReturnPath).toHaveBeenCalledWith('/files');
  });

  it('when authenticated: renders the child route content', () => {
    mockUseAuth.mockReturnValue(authValue('authenticated'));

    renderAtFiles();

    expect(screen.getByText('PROTECTED CONTENT')).toBeInTheDocument();
    expect(screen.queryByText('LANDING PAGE')).not.toBeInTheDocument();
  });
});
