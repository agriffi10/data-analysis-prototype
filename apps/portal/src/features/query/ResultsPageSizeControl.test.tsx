import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {axe} from 'vitest-axe';
import {ResultsPageSizeControl} from './ResultsPageSizeControl';
import {MAX_RESULTS_PAGE_SIZE, MIN_RESULTS_PAGE_SIZE} from './query.constants';

function setup(props: Partial<React.ComponentProps<typeof ResultsPageSizeControl>> = {}) {
  const onCommit = vi.fn();
  const view = render(
    <ResultsPageSizeControl
      pageSize={100}
      onCommit={onCommit}
      {...props}
    />
  );
  return {onCommit, view, input: screen.getByLabelText('Rows per page')};
}

describe('ResultsPageSizeControl', () => {
  it('shows the current page size under the accessible name "Rows per page"', () => {
    const {input} = setup();
    expect(input).toHaveValue('100');
  });

  it('commits an in-range integer on Enter', () => {
    const {onCommit, input} = setup();
    fireEvent.change(input, {target: {value: '250'}});
    fireEvent.keyDown(input, {key: 'Enter'});
    expect(onCommit).toHaveBeenCalledWith(250);
  });

  it('commits on blur, not per keystroke (FR-002)', () => {
    const {onCommit, input} = setup();
    fireEvent.change(input, {target: {value: '4'}});
    fireEvent.change(input, {target: {value: '42'}});
    expect(onCommit).not.toHaveBeenCalled();
    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith(42);
  });

  it('clamps out-of-range values to the bounds (FR-003)', () => {
    const {onCommit, input} = setup();
    fireEvent.change(input, {target: {value: '0'}});
    fireEvent.keyDown(input, {key: 'Enter'});
    expect(onCommit).toHaveBeenCalledWith(MIN_RESULTS_PAGE_SIZE);
    expect(input).toHaveValue(String(MIN_RESULTS_PAGE_SIZE));

    fireEvent.change(input, {target: {value: '5000'}});
    fireEvent.keyDown(input, {key: 'Enter'});
    expect(onCommit).toHaveBeenCalledWith(MAX_RESULTS_PAGE_SIZE);
    expect(input).toHaveValue(String(MAX_RESULTS_PAGE_SIZE));
  });

  it('reverts non-numeric, empty, and fractional input to the last valid value (FR-003)', () => {
    for (const bad of ['abc', '', '2.5']) {
      const {onCommit, input, view} = setup();
      fireEvent.change(input, {target: {value: bad}});
      fireEvent.blur(input);
      expect(onCommit).not.toHaveBeenCalled();
      expect(input).toHaveValue('100');
      view.unmount();
    }
  });

  it('Escape abandons the draft without committing', () => {
    const {onCommit, input} = setup();
    fireEvent.change(input, {target: {value: '7'}});
    fireEvent.keyDown(input, {key: 'Escape'});
    expect(input).toHaveValue('100');
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('re-syncs when the committed value changes externally (FR-004: one global value)', () => {
    const {view, input} = setup();
    view.rerender(
      <ResultsPageSizeControl
        pageSize={500}
        onCommit={vi.fn()}
      />
    );
    expect(input).toHaveValue('500');
  });

  it('is rendered but non-interactive when disabled (FR-002: never hidden)', () => {
    const {input} = setup({disabled: true});
    expect(input).toBeDisabled();
    expect(input).toHaveValue('100');
  });

  it('has no axe violations, enabled or disabled (SPEC-045)', async () => {
    const {view} = setup();
    expect(await axe(view.container)).toHaveNoViolations();
    view.unmount();
    const {view: disabledView} = setup({disabled: true});
    expect(await axe(disabledView.container)).toHaveNoViolations();
  });
});
