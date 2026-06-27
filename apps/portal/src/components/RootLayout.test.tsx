import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';
import {render, screen, cleanup} from '@testing-library/react';
import {MemoryRouter, Routes, Route} from 'react-router-dom';
import {RootLayout} from './RootLayout';
import type {AuthContextValue} from '../features/auth';

vi.mock('../features/auth', () => ({useAuth: vi.fn()}));

import {useAuth} from '../features/auth';

const mockUseAuth = useAuth as unknown as MockedFunction<() => AuthContextValue>;

beforeEach(() => {
  mockUseAuth.mockReturnValue({
    status: 'unauthenticated',
    user: null,
    error: null,
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn()
  });
});

afterEach(() => {
  cleanup();
});

describe('RootLayout', () => {
  it('renders the shared header and the child route content on non-landing routes', () => {
    render(
      <MemoryRouter initialEntries={['/files']}>
        <Routes>
          <Route element={<RootLayout />}>
            <Route
              path="/files"
              element={<div>CHILD CONTENT</div>}
            />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    // "S3 File Portal" comes from the Header's BrandMark.
    expect(screen.getByText('S3 File Portal')).toBeInTheDocument();
    expect(screen.getByText('CHILD CONTENT')).toBeInTheDocument();
  });

  it('suppresses the app header on the landing route (it has its own nav)', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<RootLayout />}>
            <Route
              path="/"
              element={<div>LANDING CONTENT</div>}
            />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    // The stub landing route renders no brand mark, so the only source of
    // "S3 File Portal" (the Header) must be absent.
    expect(screen.queryByText('S3 File Portal')).not.toBeInTheDocument();
    expect(screen.getByText('LANDING CONTENT')).toBeInTheDocument();
  });
});
