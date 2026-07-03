import {Fragment, type ReactNode} from 'react';

// Authored guide steps carry light inline markup for UI labels and keyboard
// shortcuts: <b>Upload</b> and <kbd>Cmd/Ctrl + Enter</kbd>. Parse to real
// elements rather than injecting HTML, so there's no dangerouslySetInnerHTML.
const TOKEN = /<(b|kbd)>([\s\S]*?)<\/\1>/g;

/** Renders a guide step string, converting `<b>` → `<strong>` and `<kbd>` → a styled key. */
export function renderInline(text: string): ReactNode {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;
  for (let match = TOKEN.exec(text); match !== null; match = TOKEN.exec(text)) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    const [, tag, inner] = match;
    nodes.push(
      tag === 'b' ? (
        <strong
          key={key++}
          className="font-semibold text-text">
          {inner}
        </strong>
      ) : (
        <kbd
          key={key++}
          className="rounded border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-text-2">
          {inner}
        </kbd>
      )
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return <Fragment>{nodes}</Fragment>;
}
