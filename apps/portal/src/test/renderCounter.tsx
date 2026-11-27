import {Profiler, useRef, type ReactNode} from 'react';

/**
 * What a gesture cost React, read off the committed fiber tree.
 *
 * `rendered` counts, by component name, the components whose function ran and produced work in a
 * commit. `reconciled` counts every fiber React created or cloned, host elements included, so a
 * thousand rows re-walked under an unchanged parent show up even though no component is named.
 * `commits` is how many commits the gesture caused. None of the three is a time, so a budget on
 * them is stable on a loaded machine; `renderMillis` is React's own figure and is for reading only.
 */
export type RenderTally = {
  commits: number;
  rendered: Record<string, number>;
  reconciled: number;
  renderMillis: number;
};

type Fiber = {
  tag: number;
  flags: number;
  type: unknown;
  memoizedProps: unknown;
  child: Fiber | null;
  sibling: Fiber | null;
  return: Fiber | null;
  stateNode: unknown;
};

const FUNCTION_COMPONENT = 0;
const CLASS_COMPONENT = 1;
const HOST_ROOT = 3;
const FORWARD_REF = 11;
const PROFILER = 12;
const SIMPLE_MEMO_COMPONENT = 15;
const PERFORMED_WORK = 1;

function componentName(fiber: Fiber): string {
  const type = fiber.type as {displayName?: string; name?: string; render?: {displayName?: string; name?: string}};
  return type.displayName || type.name || type.render?.displayName || type.render?.name || 'Anonymous';
}

function fiberOf(node: Element): Fiber | null {
  const key = Object.keys(node).find((name) => name.startsWith('__reactFiber$'));
  return key ? (node as unknown as Record<string, Fiber>)[key] : null;
}

function currentRoot(anchor: Element): Fiber | null {
  let fiber = fiberOf(anchor);
  while (fiber && fiber.tag !== HOST_ROOT) fiber = fiber.return;
  return fiber ? (fiber.stateNode as {current: Fiber}).current : null;
}

function findProfiler(from: Fiber, id: string): Fiber | null {
  const pending: Fiber[] = [from];
  while (pending.length > 0) {
    const fiber = pending.pop() as Fiber;
    if (fiber.tag === PROFILER && (fiber.memoizedProps as {id?: string}).id === id) return fiber;
    if (fiber.sibling) pending.push(fiber.sibling);
    if (fiber.child) pending.push(fiber.child);
  }
  return null;
}

export type RenderCounter = {
  /** Wraps the tree to be measured. Everything under it is counted, portals included. */
  Probe: (props: {children: ReactNode}) => ReactNode;
  /** Forgets what has been counted so far; call it once the tree has settled, before the gesture. */
  reset: () => void;
  /** What has been counted since the last reset. */
  read: () => RenderTally;
};

let nextId = 0;

/**
 * Counts what React renders under a probe, without touching the components measured.
 *
 * React marks a fiber when its component ran and produced work, and a fiber object is new to the
 * current tree only when React created or cloned it for that commit. Both are read in the
 * `Profiler` callback, which runs once the commit's tree is current. The work mark is cleared as
 * it is read, since React leaves it in place on a fiber that later bails out, where it would be
 * counted again.
 *
 * A component that runs and then bails out because its state did not change is not counted: it
 * produced no work and its children were not walked.
 *
 * @returns The probe component and the reset and read functions.
 *
 * @example
 * const counter = createRenderCounter();
 * renderWithProviders(<counter.Probe><Page /></counter.Probe>);
 * counter.reset();
 * await user.type(field, 'a');
 * expect(counter.read().rendered.ResultRows ?? 0).toBe(0);
 */
export function createRenderCounter(): RenderCounter {
  const id = `render-counter-${nextId++}`;
  let tally: RenderTally = {commits: 0, rendered: {}, reconciled: 0, renderMillis: 0};
  let previous = new Set<Fiber>();
  let anchor: Element | null = null;

  const walk = () => {
    if (!anchor) return;
    const root = currentRoot(anchor);
    const profiler = root ? findProfiler(root, id) : null;
    if (!profiler) return;
    const seen = new Set<Fiber>();
    const pending: Fiber[] = profiler.child ? [profiler.child] : [];
    while (pending.length > 0) {
      const fiber = pending.pop() as Fiber;
      seen.add(fiber);
      if (!previous.has(fiber)) tally.reconciled += 1;
      const isComponent =
        fiber.tag === FUNCTION_COMPONENT ||
        fiber.tag === CLASS_COMPONENT ||
        fiber.tag === FORWARD_REF ||
        fiber.tag === SIMPLE_MEMO_COMPONENT;
      if (isComponent && (fiber.flags & PERFORMED_WORK) !== 0) {
        const name = componentName(fiber);
        tally.rendered[name] = (tally.rendered[name] ?? 0) + 1;
        fiber.flags &= ~PERFORMED_WORK;
      }
      if (fiber.sibling) pending.push(fiber.sibling);
      if (fiber.child) pending.push(fiber.child);
    }
    previous = seen;
  };

  function Probe({children}: {children: ReactNode}) {
    const ref = useRef<HTMLSpanElement>(null);
    return (
      <>
        <span
          hidden
          ref={(node) => {
            ref.current = node;
            anchor = node;
          }}
        />
        <Profiler
          id={id}
          onRender={(_id, _phase, actualDuration) => {
            tally.commits += 1;
            tally.renderMillis += actualDuration;
            walk();
          }}>
          {children}
        </Profiler>
      </>
    );
  }

  return {
    Probe,
    reset: () => {
      tally = {commits: 0, rendered: {}, reconciled: 0, renderMillis: 0};
    },
    read: () => ({...tally, rendered: {...tally.rendered}})
  };
}
