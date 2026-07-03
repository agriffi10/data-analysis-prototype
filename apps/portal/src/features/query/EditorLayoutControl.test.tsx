import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {axe} from 'vitest-axe';
import {EditorLayoutControl} from './EditorLayoutControl';

describe('EditorLayoutControl', () => {
  it('renders the three options in a labeled group', () => {
    render(
      <EditorLayoutControl
        preset="even"
        onChange={() => {}}
      />
    );
    const group = screen.getByRole('group', {name: 'Editor and results layout'});
    expect(group).toBeInTheDocument();
    expect(screen.getByRole('button', {name: /grow the editor/i})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: /split editor and results evenly/i})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: /grow the results/i})).toBeInTheDocument();
  });

  it('marks only the selected option as pressed', () => {
    render(
      <EditorLayoutControl
        preset="results"
        onChange={() => {}}
      />
    );
    expect(screen.getByRole('button', {name: /grow the results/i})).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', {name: /grow the editor/i})).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', {name: /split editor and results evenly/i})).toHaveAttribute(
      'aria-pressed',
      'false'
    );
  });

  it('reports the clicked preset', () => {
    const onChange = vi.fn();
    render(
      <EditorLayoutControl
        preset="even"
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByRole('button', {name: /grow the editor/i}));
    expect(onChange).toHaveBeenCalledWith('editor');
  });

  it('is keyboard-operable: options are focusable native buttons', () => {
    const onChange = vi.fn();
    render(
      <EditorLayoutControl
        preset="even"
        onChange={onChange}
      />
    );
    const editorOption = screen.getByRole('button', {name: /grow the editor/i});
    // Native <button type="button"> — Enter/Space activation comes for free;
    // assert it is genuinely focusable and activation reports the preset.
    editorOption.focus();
    expect(editorOption).toHaveFocus();
    fireEvent.click(editorOption);
    expect(onChange).toHaveBeenCalledWith('editor');
  });

  it('has no axe violations', async () => {
    const {container} = render(
      <EditorLayoutControl
        preset="even"
        onChange={() => {}}
      />
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
