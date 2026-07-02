import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {MemoryRouter, Routes, Route} from 'react-router-dom';

// A signed-in visitor who opens "/" stays on the marketing page but sees
// "Go to Dashboard" entry points instead of sign-in/sign-up, unless a pending
// return path redirects them.
const {takeReturnPath} = vi.hoisted(() => ({takeReturnPath: vi.fn()}));

vi.mock('../features/auth', () => ({
  useAuth: () => ({status: 'authenticated', signIn: vi.fn(), signUp: vi.fn()})
}));
vi.mock('../lib/returnPath', () => ({takeReturnPath}));
vi.mock('../hooks/usePageTitle', () => ({usePageTitle: vi.fn()}));

const {default: LandingPage} = await import('./LandingPage');

function renderAt() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route
          path="/"
          element={<LandingPage />}
        />
        <Route
          path="/files"
          element={<div>files-page</div>}
        />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('LandingPage when authenticated', () => {
  it('shows Go to Dashboard instead of sign-in/sign-up when no return path is pending', () => {
    takeReturnPath.mockReturnValue(null);
    renderAt();

    expect(screen.getAllByRole('button', {name: /go to dashboard/i}).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', {name: /^sign in$/i})).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /create account/i})).not.toBeInTheDocument();
  });

  it('navigates to /files when Go to Dashboard is clicked', () => {
    takeReturnPath.mockReturnValue(null);
    renderAt();

    fireEvent.click(screen.getAllByRole('button', {name: /go to dashboard/i})[0]);

    expect(screen.getByText('files-page')).toBeInTheDocument();
  });

  it('redirects to the pending return path instead of rendering the page', () => {
    takeReturnPath.mockReturnValue('/files');
    renderAt();

    expect(screen.getByText('files-page')).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /go to dashboard/i})).not.toBeInTheDocument();
  });
});
