import {Component, forwardRef, memo, useReducer, useState} from 'react';
import {act, render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {expect, it, vi} from 'vitest';
import {createRenderCounter} from './renderCounter';

function Label({text}: {text: string}) {
  return <span>{text}</span>;
}
// A component under the memoised one, so a subtree React did not walk at all is in the fixture:
// its fibers keep the work mark from their last render, which is what the counter must not recount.
function Row({label}: {label: string}) {
  return (
    <li>
      <Label text={label} />
    </li>
  );
}
const MemoRow = memo(Row);

function List({memoised}: {memoised: boolean}) {
  const [count, setCount] = useState(0);
  const [, setSame] = useState('fixed');
  const Item = memoised ? MemoRow : Row;
  return (
    <>
      <button onClick={() => setCount((c) => c + 1)}>count {count}</button>
      <button onClick={() => setSame('fixed')}>set the same</button>
      <ul>
        <Item label="one" />
        <Item label="two" />
      </ul>
    </>
  );
}

function measured(memoised: boolean) {
  const counter = createRenderCounter();
  render(
    <counter.Probe>
      <List memoised={memoised} />
    </counter.Probe>
  );
  counter.reset();
  return counter;
}

it('counts a parent and not the memoised children it left alone, and counts them once the memo is gone', async () => {
  const user = userEvent.setup();

  const withMemo = measured(true);
  await user.click(screen.getByRole('button', {name: 'count 0'}));
  const skipped = withMemo.read();
  expect(skipped.commits).toBe(1);
  expect(skipped.rendered).toEqual({List: 1});

  document.body.innerHTML = '';
  const without = measured(false);
  await user.click(screen.getByRole('button', {name: 'count 0'}));
  const walked = without.read();
  expect(walked.rendered).toEqual({List: 1, Row: 2, Label: 2});
  // The two rows and their list items are cloned beside the parent's own nodes.
  expect(walked.reconciled).toBeGreaterThan(skipped.reconciled);
});

it('reports nothing for a state set to the value it already holds', async () => {
  const user = userEvent.setup();
  const counter = measured(true);

  await user.click(screen.getByRole('button', {name: 'set the same'}));

  expect(counter.read()).toMatchObject({commits: 0, rendered: {}, reconciled: 0});
});

it('reports a commit and no render for a reducer that returns the state it was given', () => {
  function Unmoved() {
    const [state, dispatch] = useReducer((held: {n: number}) => held, {n: 0});
    return <button onClick={() => dispatch()}>unmoved {state.n}</button>;
  }
  const counter = createRenderCounter();
  render(
    <counter.Probe>
      <Unmoved />
    </counter.Probe>
  );
  counter.reset();

  act(() => screen.getByRole('button', {name: 'unmoved 0'}).click());

  // React runs the function, finds nothing changed and still commits: a budget of "no commit"
  // is not met by a reducer returning its state, only by not dispatching.
  const tally = counter.read();
  expect(tally.commits).toBe(1);
  expect(tally.count('Unmoved')).toBe(0);
});

it('counts memoised, ref-forwarding and class components under the names DevTools shows', () => {
  const Plain = memo(function PlainImpl({n}: {n: number}) {
    return <i>{n}</i>;
  });
  const Titled = memo(function TitledImpl({n}: {n: number}) {
    return <b>{n}</b>;
  });
  Titled.displayName = 'Titled';
  const Forwarded = forwardRef<HTMLElement, {n: number}>(function Forwarded({n}, ref) {
    return <em ref={ref}>{n}</em>;
  });
  class Classy extends Component<{n: number}> {
    render() {
      return <u>{this.props.n}</u>;
    }
  }
  function Host() {
    const [n, setN] = useState(0);
    return (
      <>
        <button onClick={() => setN((v) => v + 1)}>bump</button>
        <Plain n={n} />
        <Titled n={n} />
        <Forwarded n={n} />
        <Classy n={n} />
      </>
    );
  }
  const counter = createRenderCounter();
  render(
    <counter.Probe>
      <Host />
    </counter.Probe>
  );
  counter.reset();

  act(() => screen.getByRole('button', {name: 'bump'}).click());

  expect(counter.read().rendered).toEqual({Host: 1, PlainImpl: 1, Titled: 1, Forwarded: 1, Classy: 1});
});

it('refuses a name no component has had, and a second probe on one counter', () => {
  const counter = measured(true);

  expect(() => counter.read().count('Lisst')).toThrow('No component named "Lisst" has been under the probe');
  expect(counter.read().count('Label')).toBe(0);

  const quiet = vi.spyOn(console, 'error').mockImplementation(() => {});
  expect(() =>
    render(
      <counter.Probe>
        <List memoised />
      </counter.Probe>
    )
  ).toThrow('A render counter takes one Probe');
  quiet.mockRestore();
});

it('counts one commit for updates in one task and one each for updates in separate tasks', () => {
  const counter = measured(true);
  const button = () => screen.getByRole('button', {name: /^count/});

  act(() => {
    button().click();
    button().click();
  });
  expect(counter.read()).toMatchObject({commits: 1, rendered: {List: 1}});

  counter.reset();
  act(() => button().click());
  act(() => button().click());
  expect(counter.read()).toMatchObject({commits: 2, rendered: {List: 2}});
});
