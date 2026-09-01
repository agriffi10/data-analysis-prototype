import {readFileSync} from 'node:fs';

/**
 * The token stylesheet, from whichever directory the runner was started in.
 *
 * Two literal paths rather than a loop over a list: `security/detect-non-literal-fs-filename`
 * is on, and a constructed path is exactly what it exists to flag — even here, where the only
 * inputs are these two constants.
 *
 * Read from disk rather than imported. Vitest does not process CSS, so both `import '…?raw'`
 * and a raw `import.meta.glob` of a stylesheet resolve to an empty string — measured, not
 * assumed — and an empty string makes a check that reads it pass by finding nothing.
 *
 * @returns The contents of `src/index.css`.
 */
export function readCss(): string {
  try {
    return readFileSync('src/index.css', 'utf8');
  } catch {
    return readFileSync('apps/portal/src/index.css', 'utf8');
  }
}

/**
 * The body of the first block whose selector `opener` matches, with comments removed.
 *
 * Comments come out FIRST, before the braces are counted. Stripping afterwards leaves the scan
 * reading punctuation inside prose: a `}` in a comment truncates the block, and — the only case
 * that fails open rather than loudly — a selector mentioned in a comment with no real block
 * returns the NEXT block's body as though it were the one asked for.
 *
 * @param css - The whole stylesheet.
 * @param opener - Matches the selector and its opening brace.
 * @param label - How to name the block if it is missing or unclosed.
 * @returns The block's body, comments stripped.
 * @throws Error when the block is absent or never closes.
 */
export function blockBody(css: string, opener: RegExp, label: string): string {
  const source = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const found = source.match(opener);
  if (found?.index === undefined) throw new Error(`index.css declares no ${label} block`);
  const start = found.index + found[0].length - 1;

  let depth = 0;
  for (let i = start; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    else if (source[i] === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(start + 1, i);
    }
  }
  throw new Error(`index.css has no closed ${label} block`);
}

/**
 * The `@theme` block — the light palette.
 *
 * Scoped to the block rather than matched across the whole file, because a whole-file scan
 * reads every `--color-*` anywhere in the stylesheet: the dark block would overwrite these
 * values with its own, and every light assertion would go on passing while measuring a palette
 * the light theme never paints.
 *
 * @param css - The whole stylesheet.
 * @returns The block's body.
 */
export function themeBlock(css: string): string {
  return blockBody(css, /@theme\s*\{/, '@theme');
}

/**
 * The `:root[data-theme='dark']` block — the dark palette.
 *
 * @param css - The whole stylesheet.
 * @returns The block's body.
 */
export function darkBlock(css: string): string {
  return blockBody(css, /:root\[data-theme='dark']\s*\{/, "dark :root[data-theme='dark']");
}

/**
 * The bare `:root` block — the shadow tints and the fixed landing surface.
 *
 * `:root\s*\{` cannot match `:root[data-theme='dark'] {`, because a `[` follows the selector
 * there rather than a brace. That is what keeps the two apart.
 *
 * @param css - The whole stylesheet.
 * @returns The block's body.
 */
export function rootBlock(css: string): string {
  return blockBody(css, /:root\s*\{/, 'bare :root');
}

/**
 * The `--color-*` declarations in a block body, as name → hex.
 *
 * @param body - A block body from one of the readers above.
 * @returns Each token's declared value, keyed without the `--color-` prefix.
 */
export function declaredTokens(body: string): Map<string, string> {
  return declaredVars(body, 'color');
}

/**
 * The `--<prefix>-*` declarations in a block body, as name → value.
 *
 * @param body - A block body from one of the readers above.
 * @param prefix - The custom-property namespace, without dashes.
 * @returns Each declaration's value, keyed without the `--<prefix>-` prefix.
 */
export function declaredVars(body: string, prefix: string): Map<string, string> {
  const declared = new Map<string, string>();
  const pattern = new RegExp(`--${prefix}-([a-z0-9-]+):\\s*([^;]+);`, 'g');
  for (const [, name, value] of body.matchAll(pattern)) declared.set(name, value.trim());
  return declared;
}
