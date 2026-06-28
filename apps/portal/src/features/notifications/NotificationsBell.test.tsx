import {describe, it, expect, afterEach} from 'vitest';
import {render, screen, cleanup} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {NotificationsBell} from './NotificationsBell';

function renderBell(props: {hasUnread: boolean; unreadCount: number}, initialPath = '/files') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <NotificationsBell {...props} />
    </MemoryRouter>
  );
}

afterEach(cleanup);

describe('NotificationsBell (SPEC-060 FR-001)', () => {
  it('links to /notifications', () => {
    renderBell({hasUnread: false, unreadCount: 0});
    expect(screen.getByRole('link')).toHaveAttribute('href', '/notifications');
  });

  it('conveys the unread count in the accessible name (not color-only)', () => {
    renderBell({hasUnread: true, unreadCount: 3});
    expect(screen.getByRole('link', {name: 'Notifications, 3 unread'})).toBeInTheDocument();
  });

  it('reports none unread when there is nothing unread', () => {
    renderBell({hasUnread: false, unreadCount: 0});
    expect(screen.getByRole('link', {name: 'Notifications, none unread'})).toBeInTheDocument();
  });

  it('marks the link current when on /notifications', () => {
    renderBell({hasUnread: false, unreadCount: 0}, '/notifications');
    expect(screen.getByRole('link')).toHaveAttribute('aria-current', 'page');
  });

  it('is not current on other routes', () => {
    renderBell({hasUnread: false, unreadCount: 0}, '/files');
    expect(screen.getByRole('link')).not.toHaveAttribute('aria-current');
  });
});
