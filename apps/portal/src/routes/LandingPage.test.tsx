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

describe('LandingPage responsive markers (SPEC-104)', () => {
  beforeEach(() => takeReturnPath.mockReturnValue(null));

  it('renders the mobile nav hamburger and hides the inline links below tablet', () => {
    renderAt();
    expect(screen.getByRole('button', {name: 'Open menu'})).toBeInTheDocument();
    // Inline anchor group is desktop/tablet-only.
    const inline = screen.getByRole('link', {name: 'Features'}).closest('div');
    expect(inline).toHaveClass('hidden', 'tablet:flex');
  });

  it('scales the hero headline fluidly across the three tiers', () => {
    renderAt();
    const h1 = screen.getByRole('heading', {level: 1});
    expect(h1).toHaveClass('text-[32px]', 'tablet:text-[40px]', 'desktop:text-[46px]');
  });

  it('stacks the hero/strip CTAs full-width on mobile', () => {
    renderAt();
    // The nav "Go to Dashboard" is icon-sized; the hero + CTA-strip ones are w-full.
    const fullWidth = screen
      .getAllByRole('button', {name: /go to dashboard/i})
      .filter((b) => b.className.includes('w-full'));
    expect(fullWidth.length).toBeGreaterThan(0);
    for (const cta of fullWidth) {
      expect(cta).toHaveClass('w-full', 'tablet:w-auto');
      expect(cta.parentElement).toHaveClass('flex-col', 'tablet:flex-row');
    }
  });

  it('steps the feature grid 1 → 2 (3rd spans) → 3', () => {
    renderAt();
    const grid = document.querySelector('#features .grid')!;
    expect(grid).toHaveClass('grid-cols-1', 'tablet:grid-cols-2', 'desktop:grid-cols-3');
    expect(grid.children[2]).toHaveClass('tablet:col-span-2', 'desktop:col-span-1');
  });
});
