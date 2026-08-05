import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';
import {render, screen, cleanup} from '@testing-library/react';
import {MemoryRouter, Routes, Route} from 'react-router';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import type {ReactNode} from 'react';
import {RootLayout} from './RootLayout';
import type {AuthContextValue} from '../features/auth';

vi.mock('../features/auth', () => ({useAuth: vi.fn()}));
// The Header mounts useNotifications for the bell indicator — stub the read so
// RootLayout tests make no S3/SQS call and stay focused on layout.
vi.mock('../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));

import {useAuth} from '../features/auth';

const mockUseAuth = useAuth as unknown as MockedFunction<() => AuthContextValue>;

// Header reads useNotifications (TanStack), which needs a QueryClientProvider.
const withProviders = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}>{ui}</QueryClientProvider>
);

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
      withProviders(
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
      )
    );

    // "Data Workspace" comes from the Header's BrandMark.
    expect(screen.getByText('Data Workspace')).toBeInTheDocument();
    expect(screen.getByText('CHILD CONTENT')).toBeInTheDocument();
  });

  it('suppresses the app header on the landing route (it has its own nav)', () => {
    render(
      withProviders(
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
      )
    );

    // The stub landing route renders no brand mark, so the only source of
    // "Data Workspace" (the Header) must be absent.
    expect(screen.queryByText('Data Workspace')).not.toBeInTheDocument();
    expect(screen.getByText('LANDING CONTENT')).toBeInTheDocument();
  });
});
