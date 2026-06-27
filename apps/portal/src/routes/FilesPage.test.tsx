import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// Capture the props FileBrowser is rendered with so we can assert the seeded prefix.
const fileBrowserProps = vi.fn();
vi.mock('../features/file-browser', () => ({
  FileBrowser: (props: Record<string, unknown>) => {
    fileBrowserProps(props);
    return <div data-testid="file-browser" />;
  },
  ensurePrefixMarker: vi.fn().mockResolvedValue({ success: true }),
  prefixMarkerKey: (u: string) => `${u}/DO_NOT_DELETE.txt`,
}));
vi.mock('../features/auth', () => ({
  useAuth: () => ({ user: { username: 'alice' }, status: 'authenticated' }),
}));
vi.mock('../hooks/usePageTitle', () => ({ usePageTitle: vi.fn() }));
vi.mock('../components/Sidebar', () => ({ Sidebar: () => <div /> }));

// FilesPage reads VITE_S3_USER_SPACE_BUCKET in a module-level const (evaluated at
// import), so the env must be stubbed BEFORE the module loads — hence the dynamic
// import. (CI has no .env; a static import would see an undefined bucket.)
vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
const { default: FilesPage } = await import('./FilesPage');

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <FilesPage />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('FilesPage deep-link (SPEC-044 FR-002)', () => {
  it('seeds the browser at an in-space ?prefix=', () => {
    renderAt('/files?prefix=alice%2Fsales%2F');
    expect(fileBrowserProps).toHaveBeenCalledWith(
      expect.objectContaining({ prefix: 'alice/sales/', rootPrefix: 'alice/' })
    );
  });

  it('ignores an out-of-space ?prefix= and falls back to the user root', () => {
    renderAt('/files?prefix=bob%2Fsecret%2F');
    expect(fileBrowserProps).toHaveBeenCalledWith(expect.objectContaining({ prefix: 'alice/' }));
  });

  it('defaults to the user root when no ?prefix= is present', () => {
    renderAt('/files');
    expect(fileBrowserProps).toHaveBeenCalledWith(expect.objectContaining({ prefix: 'alice/' }));
  });
});
