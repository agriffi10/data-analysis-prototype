import {Fragment, type ReactNode} from 'react';

// Authored guide steps carry light inline markup: <b>Upload</b> for UI labels,
// <kbd>Cmd/Ctrl + Enter</kbd> for shortcuts, <code>.sql</code> for literal text
// and <i>new</i> for emphasis. Parse to real elements rather than injecting
// HTML, so there's no dangerouslySetInnerHTML.
type InlineTag = 'b' | 'kbd' | 'code' | 'i';

const ELEMENTS: Record<InlineTag, (inner: string, key: number) => ReactNode> = {
  b: (inner, key) => (
    <strong
      key={key}
      className="font-semibold text-text">
      {inner}
    </strong>
  ),
  kbd: (inner, key) => (
    <kbd
      key={key}
      className="rounded border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-text-2">
      {inner}
    </kbd>
  ),
  code: (inner, key) => (
    <code
      key={key}
      className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-text-2">
      {inner}
    </code>
  ),
  i: (inner, key) => <em key={key}>{inner}</em>
};

// The alternation must list exactly the InlineTag names: a tag missing here reaches the reader raw.
const TOKEN = /<(b|kbd|code|i)>([\s\S]*?)<\/\1>/g;

/**
 * Renders a guide string, converting `<b>` → `<strong>`, `<kbd>` → a styled key,
 * `<code>` → inline monospace and `<i>` → `<em>`. Any other tag is left as text.
 */
export function renderInline(text: string): ReactNode {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;
  for (let match = TOKEN.exec(text); match !== null; match = TOKEN.exec(text)) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    const [, tag, inner] = match;
    nodes.push(ELEMENTS[tag as InlineTag](inner, key++));
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return <Fragment>{nodes}</Fragment>;
}
