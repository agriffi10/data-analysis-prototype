import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  afterEach,
  type MockedFunction,
} from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { RootLayout } from './RootLayout';
import type { AuthContextValue } from '../features/auth';

vi.mock('../features/auth', () => ({ useAuth: vi.fn() }));

import { useAuth } from '../features/auth';

const mockUseAuth = useAuth as unknown as MockedFunction<() => AuthContextValue>;

beforeEach(() => {
  mockUseAuth.mockReturnValue({
    status: 'unauthenticated',
    user: null,
    error: null,
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
});

describe('RootLayout', () => {
  it('renders the shared header and the child route content on every page', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<RootLayout />}>
            <Route path="/" element={<div>CHILD CONTENT</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText('S3 File Portal')).toBeInTheDocument();
    expect(screen.getByText('CHILD CONTENT')).toBeInTheDocument();
  });
});
