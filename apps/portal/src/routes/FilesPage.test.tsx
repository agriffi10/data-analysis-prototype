import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import type {Connection} from '../features/query/query.types';

// Capture the props FileBrowser is rendered with so we can assert the target space.
const fileBrowserProps = vi.fn();
vi.mock('../features/file-browser', async () => {
  // Exercise the real useFileSpace (light deps) while stubbing the heavy browser.
  const {useFileSpace} = await vi.importActual<typeof import('../features/file-browser/useFileSpace')>(
    '../features/file-browser/useFileSpace'
  );
  return {
    FileBrowser: (props: Record<string, unknown>) => {
      fileBrowserProps(props);
      return <div data-testid="file-browser" />;
    },
    ensurePrefixMarker: vi.fn().mockResolvedValue({success: true}),
    prefixMarkerKey: (u: string) => `${u}/DO_NOT_DELETE.txt`,
    useFileSpace
  };
});
vi.mock('../features/auth', () => ({
  useAuth: () => ({user: {username: 'alice'}, status: 'authenticated'})
}));
vi.mock('../hooks/usePageTitle', () => ({usePageTitle: vi.fn()}));
vi.mock('../components/Sidebar', () => ({Sidebar: () => <nav aria-label="Your spaces" />}));

// useConnections is mocked so the page needs no QueryClient / live AWS.
const connectionsValue = vi.fn();
vi.mock('../features/query/useConnections', () => ({
  useConnections: () => connectionsValue()
}));

const personal: Connection = {id: 'personal', label: 'alice', database: 'alice', kind: 'personal'};
const marketing: Connection = {
  id: 'marketing_data',
  label: 'marketing_data',
  database: 'marketing_data',
  kind: 'shared',
  status: 'active',
  role: 'member'
};
const provisioning: Connection = {
  id: 'sales_2026',
  label: 'sales_2026',
  database: 'sales_2026',
  kind: 'shared',
  status: 'provisioning',
  role: 'owner'
};

// FilesPage reads the bucket env in module-level consts (evaluated at import), so
// the env must be stubbed BEFORE the module loads — hence the dynamic import.
vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-bucket');
const {default: FilesPage} = await import('./FilesPage');

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <FilesPage />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  connectionsValue.mockReturnValue({connections: [personal, marketing, provisioning], isLoading: false});
});

describe('FilesPage personal space (SPEC-013/044)', () => {
  it('defaults to the personal space rooted at {username}/', () => {
    renderAt('/files');
    expect(fileBrowserProps).toHaveBeenCalledWith(
      expect.objectContaining({
        bucket: 'user-bucket',
        prefix: 'alice/',
        rootPrefix: 'alice/',
        rootLabel: 'alice',
        markerKey: 'alice/DO_NOT_DELETE.txt',
        username: 'alice',
        writable: true
      })
    );
  });

  it('seeds the browser at an in-space ?prefix=', () => {
    renderAt('/files?prefix=alice%2Fsales%2F');
    expect(fileBrowserProps).toHaveBeenCalledWith(
      expect.objectContaining({prefix: 'alice/sales/', rootPrefix: 'alice/'})
    );
  });

  it('ignores an out-of-space ?prefix= and falls back to the space root', () => {
    renderAt('/files?prefix=bob%2Fsecret%2F');
    expect(fileBrowserProps).toHaveBeenCalledWith(expect.objectContaining({prefix: 'alice/'}));
  });
});

describe('FilesPage shared space (SPEC-057 FR-002/FR-004)', () => {
  it('targets the shared bucket + space root for ?space=', () => {
    renderAt('/files?space=marketing_data');
    expect(fileBrowserProps).toHaveBeenCalledWith(
      expect.objectContaining({
        bucket: 'shared-bucket',
        prefix: 'marketing_data/',
        rootPrefix: 'marketing_data/',
        rootLabel: 'marketing_data',
        markerKey: 'marketing_data/DO_NOT_DELETE.txt',
        username: 'marketing_data',
        writable: true
      })
    );
  });

  it('seeds an in-space ?prefix= within the shared space', () => {
    renderAt('/files?space=marketing_data&prefix=marketing_data%2Fq1%2F');
    expect(fileBrowserProps).toHaveBeenCalledWith(
      expect.objectContaining({rootPrefix: 'marketing_data/', prefix: 'marketing_data/q1/'})
    );
  });

  it('falls back to personal with a notice for an unknown ?space=', () => {
    renderAt('/files?space=ghost');
    expect(screen.getByRole('status')).toHaveTextContent(/no longer available/i);
    expect(fileBrowserProps).toHaveBeenCalledWith(expect.objectContaining({rootPrefix: 'alice/'}));
  });

  it('falls back to personal for a not-yet-usable (provisioning) ?space=', () => {
    renderAt('/files?space=sales_2026');
    expect(screen.getByRole('status')).toHaveTextContent(/no longer available/i);
    expect(fileBrowserProps).toHaveBeenCalledWith(expect.objectContaining({rootPrefix: 'alice/'}));
  });
});
