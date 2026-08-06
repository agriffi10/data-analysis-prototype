import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, it, expect, vi} from 'vitest';
import {SegmentedFilter} from './SegmentedFilter';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../test/axe';

const OPTIONS = [
  {value: 'all', label: 'All'},
  {value: 'clean', label: 'Clean'},
  {value: 'issues', label: 'Issues'}
] as const;

describe('SegmentedFilter', () => {
  it('is one labelled group whose chosen option carries aria-pressed', () => {
    // The choice must not be conveyed by styling alone — that is the whole reason
    // this is a pressed-button group rather than a row of styled links.
    render(
      <SegmentedFilter
        label="Filter checks"
        options={OPTIONS}
        value="clean"
        onChange={vi.fn()}
      />
    );

    const group = screen.getByRole('group', {name: 'Filter checks'});
    expect(group).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Clean'})).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', {name: 'All'})).toHaveAttribute('aria-pressed', 'false');
  });

  it('reports the chosen value', async () => {
    const onChange = vi.fn();
    render(
      <SegmentedFilter
        label="Filter checks"
        options={OPTIONS}
        value="all"
        onChange={onChange}
      />
    );

    await userEvent.click(screen.getByRole('button', {name: 'Issues'}));
    expect(onChange).toHaveBeenCalledWith('issues');
  });

  it('renders the given labels, not the raw values', () => {
    render(
      <SegmentedFilter
        label="Filter notifications"
        options={[
          {value: 'all', label: 'All'},
          {value: 'unread', label: 'Unread'}
        ]}
        value="all"
        onChange={vi.fn()}
      />
    );
    expect(screen.getByRole('button', {name: 'Unread'})).toBeInTheDocument();
    // The negative is the point: the page this replaced rendered the raw value and
    // leaned on a CSS `capitalize`, so the accessible name was lowercase.
    expect(screen.queryByText('unread')).toBeNull();
  });

  it('has no axe violations', async () => {
    await expectNoA11yViolations(
      <SegmentedFilter
        label="Filter checks"
        options={OPTIONS}
        value="all"
        onChange={vi.fn()}
      />,
      COMPONENT_AXE_OPTIONS
    );
  });
});
