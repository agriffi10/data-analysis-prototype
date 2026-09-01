import {describe, it, expect} from 'vitest';

/**
 * SPEC-186 FR-009 AC7 / FR-010 AC7, on SPEC-165's one-builder sweep precedent.
 *
 * The finding this spec recorded is that the problem is not missing components — it is existing
 * components being bypassed and then DRIFTING. Three chip lists were byte-identical until one
 * grew an `h-6 w-6` remove target and the other two stayed at `h-5 w-5` — 21px and 17.5px at
 * this app's 14px root, both under WCAG 2.2 SC 2.5.8's 24px minimum;
 * `Badge` shipped and was used by two files while three others hand-rolled it, each
 * differing by a token or two. Nothing was holding any of it.
 *
 * These sweeps hold it. A second copy of a consolidated shape fails here rather than in a
 * screenshot six months from now.
 *
 * Read through Vite's own `?raw` glob rather than `node:fs`: the app tsconfig carries no node
 * types, so `tsc -b` — the only typecheck CI runs — rejects an fs import here
 * (`archiveWriteLock.test.ts` records the same constraint), and a constructed path is what
 * `security/detect-non-literal-fs-filename` exists to flag.
 */
const SOURCES = import.meta.glob('/src/**/*.{ts,tsx}', {query: '?raw', import: 'default', eager: true}) as Record<
  string,
  string
>;

/** Every source as `[path relative to src/, contents]`; tests excluded. */
const FILES: [string, string][] = Object.entries(SOURCES)
  .map(([path, source]): [string, string] => [path.replace(/^\/src\//, ''), source])
  .filter(([path]) => !/\.test\.tsx?$/.test(path))
  .sort(([a], [b]) => a.localeCompare(b));

/** Files carrying `needle`, reported src-relative so a failure names the offender. */
function filesContaining(needle: string, exclude: string[] = []): string[] {
  return FILES.filter(([path, source]) => !exclude.includes(path) && source.includes(needle)).map(([path]) => path);
}

/** Each consolidated shape, its one legitimate home, and a label for the failure message. */
const OWNED: {what: string; needle: string; owner: string}[] = [
  {what: 'the status-pill dot', needle: 'h-[7px] w-[7px]', owner: 'components/StatusPill.tsx'},
  {
    what: 'the removable-chip shell',
    needle: 'rounded-full border border-border bg-surface-2 py-0.5 pl-2.5 pr-1',
    owner: 'components/Chip.tsx'
  },
  {what: 'the field label', needle: 'mb-1.5 block text-sm font-medium text-text', owner: 'components/fieldStyles.ts'},
  {what: 'the field hint', needle: 'mt-1.5 text-xs text-text-3', owner: 'components/fieldStyles.ts'},
  {
    what: 'the section caption',
    needle: 'text-xs font-semibold uppercase tracking-wide text-text-3',
    owner: 'components/fieldStyles.ts'
  },
  {
    what: 'the Modal-direct dialog panel',
    needle: 'flex max-w-lg flex-col px-5 pb-4 pt-5',
    owner: 'components/dialogChrome.ts'
  },
  {
    what: 'the neutral pill',
    needle: 'rounded-full bg-surface-2 border border-border px-2 py-0.5 text-xs font-medium',
    owner: 'components/Badge.tsx'
  }
];

describe('shared primitives are not re-implemented (SPEC-186)', () => {
  // Without this, a broken glob or a needle that no longer matches anything would make every
  // assertion below pass vacuously — "found nowhere" reads exactly like "consolidated".
  it('guards the guard — the glob is real and every needle still matches its owner', () => {
    expect(FILES.length).toBeGreaterThan(150);
    expect(FILES.map(([path]) => path)).toContain('components/Chip.tsx');
    for (const {needle, owner} of OWNED) {
      expect(filesContaining(needle)).toEqual([owner]);
    }
  });

  it.each(OWNED)('has exactly one copy of $what', ({needle, owner}) => {
    // Six sites hand-rolled the status pill, plus a seventh in `LandingPage` that the spec's own
    // list missed — which is the argument for a sweep over an enumeration.
    expect(filesContaining(needle, [owner])).toEqual([]);
  });

  it('has no surviving spelling of the section caption', () => {
    // The two variants that were folded INTO the survivor. A drifted third spelling reappearing
    // is exactly how this pattern got to eleven sites and three styles.
    for (const variant of [
      'text-xs font-medium uppercase tracking-wide text-text-2',
      'text-xs font-semibold uppercase tracking-[.04em] text-text-3'
    ]) {
      expect(filesContaining(variant)).toEqual([]);
    }
  });

  // The chip's remove target is the one size in this file that encodes an ACCESSIBILITY
  // THRESHOLD rather than a visual step, and the difference is invisible on the page: the
  // spacing scale is rem-derived against a 14px root, so `h-6` draws 21px and `h-7` 24.5 —
  // both of which look right and one of which is under WCAG 2.2 SC 2.5.8's 24. This target
  // carried a comment claiming 24x24 over a class drawing 21 for the whole of its life,
  // because nothing but prose was holding it.
  //
  // This is a TRIPWIRE, not a behavioural test: it restates the source, which is the point,
  // since the regression it exists for is a textual tidy back onto the scale. Do not delete it
  // to make a restyle pass — revisit the decision instead, and note that the measured check
  // lives in docs/testing/e2e.md, because jsdom has no layout and axe's `target-size` cannot
  // fail here. `toContain` rather than set equality: the divider's step buttons legitimately
  // carry the same class, and a second correct user must not redden this.
  it('pins the chip remove target to an absolute 24px', () => {
    expect(filesContaining('h-[24px] w-[24px]')).toContain('components/Chip.tsx');
  });
});
