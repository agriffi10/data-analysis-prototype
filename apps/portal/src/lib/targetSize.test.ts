import {readFileSync} from 'node:fs';
import {describe, expect, it} from 'vitest';
import {configureAxe} from 'vitest-axe';
import {COMPONENT_AXE_OPTIONS, ROUTE_AXE_OPTIONS, RULES_JSDOM_CANNOT_DECIDE} from '../test/axe';
import {readCss} from '../test/cssTokens';

// WCAG 2.2 SC 2.5.8 asks for a pointer target of at least 24×24 CSS px, or enough space around a
// smaller one. axe has a rule for it, the suite runs axe, and the rule cannot fire — jsdom has no
// layout, so every rect is 0×0 and the rule reports a PASS carrying a measurement it never made.
// The second describe below pins that, and `test/axe.ts` disables the rule because of it.
//
// This file is what covers the part a class name CAN answer: a control sized from the spacing
// scale. WHAT IT DOES NOT COVER, said plainly so nobody reads its silence as coverage:
//
//   1. A control with NO size class, whose height is its line box plus padding. A bare `text-sm`
//      link is a ~15.5px content-area box; a `px-3 py-2 text-sm` menu row is 32px. Both carry no
//      `h-*`, one is undersized and the other is fine, and only layout separates them. A rule
//      demanding `min-h-[24px]` on every text-only control would fire on the correct one, which is
//      the same defect as the axe rule pointing the other way. Left uncovered on purpose.
//   2. Whether an undersized control is actually a VIOLATION. SC 2.5.8's spacing exception exempts
//      a small target that no other target comes within a 24px-diameter circle of. That is
//      geometry, so under 24px is a CANDIDATE here and nothing more — which is why the register
//      below is named for acceptance rather than for exemption.
//   3. A class string assembled somewhere other than the tag, a size given in an inline style, and
//      an arbitrary value in a unit other than px (`h-[1.5rem]`, `w-[100%]`) — read as unmeasurable
//      and skipped rather than guessed at.
//
// The one thing that settles any of the three is a browser. The console one-liner and both
// mechanisms are written up in `info/best-practices/accessibility/accessibility.md`; what has not
// been run is in `docs/testing/owed.md`.

const SOURCES = import.meta.glob('/src/**/*.tsx', {query: '?raw', import: 'default', eager: true}) as Record<
  string,
  string
>;

/** Not app code: the suite itself and its harness. */
const NOT_APP_CODE = /\.test\.tsx$|^\/src\/test\//;

/** SC 2.5.8's floor, in CSS px. Absolute — it does not track the root font size, and neither may anything encoding it. */
const MIN_TARGET_PX = 24;

/**
 * Tailwind's own theme defaults, which is where `--spacing` is declared.
 *
 * Two literal paths rather than one built from the runner's cwd, matching `test/cssTokens.ts`:
 * `security/detect-non-literal-fs-filename` is on, and the suite runs from the repo root or from
 * `apps/portal` depending on how it was started. The package is hoisted, so it is only ever at the
 * root of the workspace.
 */
function tailwindTheme(): string {
  try {
    return readFileSync('node_modules/tailwindcss/theme.css', 'utf8');
  } catch {
    return readFileSync('../../node_modules/tailwindcss/theme.css', 'utf8');
  }
}

/** CSS with its comments removed, so prose about a value is not read as the value. */
function withoutComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

/**
 * Source with its comments removed, matching `lib/colourLiterals.test.ts`.
 *
 * Not tidiness — correctness, and the sweep FAILED OPEN without it. An apostrophe in a comment
 * ("SC 2.5.8's minimum") reads as an opening quote to the attribute scanner below, which then
 * treats the class string that follows as being inside it and finds no classes at all. Two of the
 * controls in the register were invisible until this was added.
 *
 * A `//` preceded by `:` is left alone — that is the `https://` in a URL, and cutting there would
 * drop the rest of a real line of code with it.
 */
function code(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1');
}

/**
 * The root font size the app sets, in px.
 *
 * @throws Error when `index.css` no longer states it in px — at which point every number below is
 *   wrong and a thrown error is the only honest outcome.
 */
function rootFontSizePx(): number {
  const found = /html\s*\{[^{}]*font-size:\s*([\d.]+)px/.exec(withoutComments(readCss()));
  if (!found) throw new Error('index.css declares no `html { font-size: …px }` — the spacing scale cannot be resolved');
  return Number(found[1]);
}

/**
 * One step of the spacing scale, in px.
 *
 * Read from Tailwind's declaration and multiplied by the app's root, rather than written down: a
 * hard-coded 3.5 agrees with today and hides the model, and the model is the whole point — the
 * scale is authored in rem and the threshold is in px, so the two only meet through the root.
 *
 * @throws Error when the declaration cannot be read, or when the app has taken the value over.
 */
function spacingStepPx(): number {
  const declared = /--spacing:\s*([\d.]+)rem;/.exec(tailwindTheme());
  if (!declared) throw new Error('tailwindcss/theme.css declares no `--spacing` in rem');
  if (/--spacing:/.test(withoutComments(readCss()))) {
    throw new Error(
      'index.css now declares its own `--spacing` — read the step from there, not from the vendor default'
    );
  }
  return Number(declared[1]) * rootFontSizePx();
}

const STEP_PX = spacingStepPx();

// A `h-*` / `w-*` / `size-*` utility, and only where the whole class is one. The lookbehind is what
// keeps `min-h-6` and `max-w-4` out: both are FLOORS or CEILINGS rather than the height, so a
// padded control carrying one may well be taller than the number says and the sweep cannot tell.
// The lookahead keeps the fraction utilities out for the same reason — `w-1/2` is a proportion.
const SIZE_CLASS = /(?<![\w-])(?:h|w|size)-(\[[^\]]*]|[\d.]+|px)(?![\w\-/])/g;

/**
 * What a size class resolves to in CSS px, or `null` when it names no px value at all.
 *
 * Three forms, and the middle one is the reason this is a function rather than a table: an
 * arbitrary value is emitted literally by Tailwind, so `h-[24px]` is 24px under any root while
 * `h-7` is 24.5px under this one and 21px under a 12px one. A class encoding an accessibility
 * threshold should use the form that cannot drift.
 *
 * @param value - The part after `h-` / `w-` / `size-`.
 * @returns The resolved px, or `null` for a value this cannot read (a rem or `%` arbitrary value).
 */
function sizeClassPx(value: string): number | null {
  if (value === 'px') return 1;
  if (value.startsWith('[')) {
    const arbitrary = /^\[([\d.]+)px]$/.exec(value);
    return arbitrary ? Number(arbitrary[1]) : null;
  }
  return Number(value) * STEP_PX;
}

const NATIVE_CONTROL = /^(?:button|a|input|select|textarea|summary)$/;

/** Components that render a native control and take a `className` straight through to it. */
const CONTROL_COMPONENT = /^(?:Link|NavLink|IconButton|Button)$/;

const INTERACTIVE_ROLE = /role=['"](?:button|link|tab|switch|checkbox|radio|menuitem|option)['"]/;

/**
 * The text of one JSX opening tag's attributes, from `start` to the `>` that closes it.
 *
 * Scanned character by character rather than up to the first `>`, because `onClick={() => …}`
 * carries one and stopping there would cut the tag in half — dropping every attribute after the
 * first handler, `className` included, which is most of them.
 *
 * @param source - The whole file.
 * @param start - The index just past the tag name.
 * @returns The attribute text, or `null` when the tag never closes.
 */
function attributesFrom(source: string, start: number): string | null {
  let depth = 0;
  let quote: string | null = null;
  for (let i = start; i < source.length; i += 1) {
    const c = source[i];
    if (quote) {
      if (c === quote && source[i - 1] !== '\\') quote = null;
    } else if (c === "'" || c === '"' || c === '`') quote = c;
    else if (c === '{') depth += 1;
    else if (c === '}') depth -= 1;
    else if (c === '>' && depth === 0) return source.slice(start, i);
  }
  return null;
}

/**
 * The tag's OWN `className` value — the first one in its attributes.
 *
 * First rather than all: a prop holding a JSX element (`trigger={<Icon className="h-4 w-4" />}`)
 * puts a second `className` inside the same attribute region, and reading both reports the
 * decorative icon's size as the control's.
 *
 * @param attributes - One tag's attribute text.
 * @returns The class string, expression braces and all, or `''` when the tag sets none.
 */
function ownClassName(attributes: string): string {
  const at = /class(?:Name)?=/.exec(attributes);
  if (!at) return '';
  const i = at.index + at[0].length;
  const opener = attributes[i];
  if (opener === '"' || opener === "'") {
    const end = attributes.indexOf(opener, i + 1);
    return end === -1 ? '' : attributes.slice(i + 1, end);
  }
  if (opener !== '{') return '';
  let depth = 0;
  for (let j = i; j < attributes.length; j += 1) {
    if (attributes[j] === '{') depth += 1;
    else if (attributes[j] === '}') {
      depth -= 1;
      if (depth === 0) return attributes.slice(i + 1, j);
    }
  }
  return '';
}

/**
 * Every interactive tag in `source` whose own size classes put it under the floor.
 *
 * A tag counts as interactive when it is a native control, carries an interactive `role`, is one
 * of the components above, or is a plain element with an `onClick` — the last of which is how the
 * two tab strips' close controls are seen at all.
 *
 * @param source - One `.tsx` file, or a fragment of one.
 * @returns One entry per offending tag, naming the tag, the class and what it measures.
 */
function undersizedControls(source: string): string[] {
  const offences: string[] = [];
  const scanned = code(source);
  const tag = /<([A-Za-z][A-Za-z0-9._]*)/g;
  let opening: RegExpExecArray | null;
  while ((opening = tag.exec(scanned)) !== null) {
    const attributes = attributesFrom(scanned, tag.lastIndex);
    if (attributes === null) continue;
    const name = opening[1];
    const interactive =
      NATIVE_CONTROL.test(name) ||
      CONTROL_COMPONENT.test(name) ||
      INTERACTIVE_ROLE.test(attributes) ||
      (/onClick=/.test(attributes) && /^[a-z]/.test(name));
    if (!interactive) continue;
    for (const [whole, cls] of ownClassName(attributes).matchAll(SIZE_CLASS)) {
      const px = sizeClassPx(cls);
      if (px !== null && px < MIN_TARGET_PX) offences.push(`<${name}> ${whole} = ${px}px`);
    }
  }
  return offences;
}

/**
 * Every control under the floor today, and what it is.
 *
 * A tripwire, not a clean bill of health: each of these is a CANDIDATE that the spacing exception
 * may or may not cover, and the geometry has not been measured in a browser for any of them. The
 * notes say what a control is and where it sits, never that it conforms. Revisit the decision —
 * measure them and move them out — rather than deleting the entry.
 *
 * A new entry is a deliberate edit, which is the point.
 */
const ACCEPTED_UNDERSIZED: Record<string, string> = {
  '/src/components/Chip.tsx':
    'the chip remove button, 21×21, in a wrapping row of chips. The one whose geometry has been worked out — 42px between adjacent remove buttons, 29.75px between wrapped rows, both computed from the source values and neither measured',
  '/src/components/Toast.tsx':
    'the toast dismiss button, 21×21, beside an optional underlined text action in the same bar',
  '/src/features/data-explorer/ColumnFilterMenu.tsx':
    'the column sort/filter menu trigger, 21px tall with its width coming from padding, one per column header',
  '/src/features/data-explorer/ExplorationTabStrip.tsx':
    'the tab close control, 21×21, inside the tab it closes and next to the neighbouring tab. It is a span with an onClick and role="presentation", so it is also unreachable by keyboard — a separate defect, recorded here because this is where it was found',
  '/src/features/file-browser/FileListRowMobile.tsx':
    'the row selection checkbox, 14×14, centred in a fixed-width cell at the row edge',
  '/src/features/file-browser/FileListTable.tsx':
    'the select-all header checkbox and the per-row selection checkbox, both 14×14, stacked one per row',
  '/src/features/file-browser/SelectionToolbar.tsx': 'the select-all checkbox in the selection toolbar, 14×14',
  '/src/features/file-send/SendFilesDialog.tsx': 'the recipient-kind radios, 14×14, each inside its own label',
  '/src/features/query/QueryTabStrip.tsx':
    'the tab close control, 21×21 — the same shape as the Data Explorer strip above, including the role',
  '/src/features/query/TableActionsMenu.tsx':
    'the table row actions menu trigger, 21×21, at the end of a schema rail row',
  '/src/features/table-builder/RefreshTableDialog.tsx': 'the "allow removals" checkbox, 14×14, alone in its row',
  '/src/features/table-share/TableShareDialog.tsx': 'the share-kind radios, 14×14, each inside its own label'
};

const offenders: Record<string, string[]> = {};
for (const [path, source] of Object.entries(SOURCES)) {
  if (NOT_APP_CODE.test(path)) continue;
  const found = undersizedControls(source);
  if (found.length) offenders[path] = found;
}

describe('a control sized from the spacing scale reaches the target floor', () => {
  it('takes its threshold from the root font size and the spacing scale, not from a number', () => {
    // The scale is authored in rem and the floor is in px, so the root is the only thing joining
    // them — and it is 14px here, not the 16 every Tailwind example assumes. Both steps either
    // side of the floor are named, because the gap between them is where this goes wrong: `h-6`
    // misses by 3px and `h-7` clears by half of one.
    expect(rootFontSizePx()).toBe(14);
    expect(STEP_PX).toBe(3.5);
    expect(sizeClassPx('6')).toBeLessThan(MIN_TARGET_PX);
    expect(sizeClassPx('7')).toBeGreaterThanOrEqual(MIN_TARGET_PX);
    expect(sizeClassPx('7')).toBe(24.5);
  });

  it('reads a size class the way the browser will, and reads no other class', () => {
    // The positive control for everything below: without it every assertion here passes by
    // finding nothing, which is exactly the failure this file exists to remove.
    expect(Object.keys(SOURCES).length).toBeGreaterThan(50);
    expect(undersizedControls('<button className="grid h-6 w-6 flex-none">x</button>')).toEqual([
      '<button> h-6 = 21px',
      '<button> w-6 = 21px'
    ]);
    expect(undersizedControls('<button className="h-7 w-7" />')).toEqual([]);

    // An arbitrary px value is emitted literally, so it is read literally — and it is the form
    // that stays 24px if the root ever moves.
    expect(undersizedControls('<button className="h-[24px] w-[24px]" />')).toEqual([]);
    expect(undersizedControls('<button className="h-[20px]" />')).toEqual(['<button> h-[20px] = 20px']);

    // Three classes that look like the ones above and mean something else. A floor and a ceiling
    // do not fix a height; a fraction is a proportion of the parent.
    expect(undersizedControls('<button className="min-h-6 max-w-4 w-1/2">x</button>')).toEqual([]);

    // …and a decorative icon passed as a prop is not the control's own size.
    expect(undersizedControls('<button className="h-8 w-8" title={<Icon className="h-4 w-4" />}>x</button>')).toEqual(
      []
    );

    // The apostrophe that made this sweep fail open. Comments are stripped before the scan; if
    // they stop being, this control disappears and the whole file goes quiet rather than red.
    expect(undersizedControls("<button\n  // SC 2.5.8's floor\n  className='h-6'>x</button>")).toEqual([
      '<button> h-6 = 21px'
    ]);
  });

  it('flags an undersized interactive control that carries no accepted entry', () => {
    const unaccepted = Object.fromEntries(Object.entries(offenders).filter(([path]) => !(path in ACCEPTED_UNDERSIZED)));
    expect(unaccepted).toEqual({});
  });

  it('holds no accepted entry for a control that has stopped being undersized', () => {
    // This fires on a CORRECT change — resize one of the controls above and its entry goes stale.
    // The message is the whole mitigation: delete the entry in the same commit as the resize.
    const stale = Object.keys(ACCEPTED_UNDERSIZED).filter((path) => !(path in offenders));
    expect(stale, 'these now clear the floor — delete their ACCEPTED_UNDERSIZED entries here').toEqual([]);
    for (const [path, why] of Object.entries(ACCEPTED_UNDERSIZED)) expect(why.length, path).toBeGreaterThan(20);
  });

  it('keeps the shared icon button clear of the floor at its smallest size', () => {
    // The one primitive already sized around this rule, and the reason most icon controls in the
    // app are not in the register above. Its `sm` sits one step over the floor, so a tidy-up that
    // normalised it down a step would cost every one of its call sites at once.
    const sizes = /const SIZES = \{[^}]*}/.exec(SOURCES['/src/components/IconButton.tsx'])?.[0] ?? '';
    const measured = [...sizes.matchAll(SIZE_CLASS)].map(([size, cls]) => ({size, px: sizeClassPx(cls)}));

    // The map holds two sizes, a height and a width each. Counted before anything is filtered,
    // because an empty list satisfies every assertion made about one.
    expect(measured, 'the SIZES map was not read — the check below would pass on nothing').toHaveLength(4);
    expect(measured.filter((size) => size.px === null || size.px < MIN_TARGET_PX)).toEqual([]);
  });

  it('cannot see a control whose height comes from its text, and does not pretend to', () => {
    // Both of these are invisible here, and only one of them is fine: the link is a ~15.5px
    // content-area box and the menu row is 32px, separated by padding alone. A rule that demanded
    // a height class from either would fire on the correct one. Pinned so that the silence below
    // is read as a known gap rather than as a pass — a browser is the only thing that settles it.
    expect(
      undersizedControls('<a href="/guides" className="text-sm text-accent-text">Open the full guide</a>')
    ).toEqual([]);
    expect(undersizedControls('<button className="w-full px-3 py-2 text-left text-sm">Rename</button>')).toEqual([]);
  });
});

describe('axe cannot decide target size in jsdom, and says otherwise', () => {
  const runTargetSize = configureAxe({runOnly: {type: 'rule', values: ['target-size']}});

  it('reports a pass for two adjacent 10×10 buttons, on a rect it never measured', async () => {
    const host = document.createElement('div');
    host.innerHTML =
      '<button style="width:10px;height:10px">a</button><button style="width:10px;height:10px">b</button>';
    document.body.appendChild(host);
    try {
      // The cause, asserted first so a failure below is readable: jsdom lays nothing out, so the
      // rects axe reads are all zero.
      const rect = host.firstElementChild?.getBoundingClientRect();
      expect([rect?.width, rect?.height]).toEqual([0, 0]);

      const results = (await runTargetSize(host)) as {violations: unknown[]; passes: unknown[]};
      expect(
        results.violations,
        'jsdom now lays out — re-enable `target-size` in test/axe.ts and delete this tripwire'
      ).toEqual([]);
      expect(results.passes.length).toBeGreaterThan(0);
    } finally {
      host.remove();
    }
  });

  it('carries the undecidable rules into every options bag', () => {
    // The bags deep-merge over the base rather than replacing it, so this is belt to that braces —
    // and it is the half that catches a bag added later which spells its own rules and forgets one.
    for (const rule of Object.keys(RULES_JSDOM_CANNOT_DECIDE)) {
      expect(ROUTE_AXE_OPTIONS.rules?.[rule], rule).toEqual({enabled: false});
      expect(COMPONENT_AXE_OPTIONS.rules?.[rule], rule).toEqual({enabled: false});
    }
  });
});
