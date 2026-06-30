import {describe, it, expect, afterEach} from 'vitest';
import {render, screen, cleanup} from '@testing-library/react';
import {PageLayout} from './PageLayout';

afterEach(cleanup);

describe('PageLayout', () => {
  it('renders the title as the sole <h1> inside the <main id="main"> landmark', () => {
    render(
      <PageLayout title="Notifications">
        <p>body</p>
      </PageLayout>
    );
    const main = screen.getByRole('main');
    expect(main).toHaveAttribute('id', 'main');
    const headings = screen.getAllByRole('heading', {level: 1});
    expect(headings).toHaveLength(1);
    expect(headings[0]).toHaveTextContent('Notifications');
    expect(screen.getByText('body')).toBeInTheDocument();
  });

  it('renders the subtitle and actions when provided, and omits them otherwise', () => {
    const {rerender} = render(
      <PageLayout
        title="Connections"
        subtitle="Spaces you belong to"
        actions={<button type="button">New</button>}>
        body
      </PageLayout>
    );
    expect(screen.getByText('Spaces you belong to')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'New'})).toBeInTheDocument();

    rerender(<PageLayout title="Connections">body</PageLayout>);
    expect(screen.queryByText('Spaces you belong to')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'New'})).not.toBeInTheDocument();
  });

  it('appends contentClassName to the content column', () => {
    render(
      <PageLayout
        title="T"
        contentClassName="max-w-[760px] gap-2">
        <span>child</span>
      </PageLayout>
    );
    const content = screen.getByText('child').parentElement!;
    expect(content.className).toContain('max-w-[760px]');
    expect(content.className).toContain('gap-2');
  });
});
