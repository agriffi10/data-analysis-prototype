import {describe, expect, it} from 'vitest';
import {
  resolveUrl,
  templateRefusal,
  URL_NOT_A_URL,
  URL_NOT_HTTPS,
  URL_PLACEHOLDER,
  URL_TEMPLATE_REFUSAL
} from './urlTransformer';
import {transformCell} from './formatting';

// SPEC-184 FR-006. The template is the user's; the value substituted into it is the
// TABLE's — so every case below is a value doing something the template's author did not
// intend, which is the only threat model this module has.

describe('the URL transformer only ever produces an https link', () => {
  it('refuses every other scheme, judged on the RESOLVED url', () => {
    // The case that matters: the template is inert and the CELL carries the scheme. It is
    // reachable only because a leading placeholder substitutes RAW — encode it and every
    // one of these fails as "not a url" instead, which refuses the right rows for the
    // wrong reason and takes every legitimate link in the column down with it.
    for (const scheme of ['javascript:alert(1)', 'data:text/html,<script>', 'vbscript:msgbox', 'file:///etc/passwd']) {
      expect(resolveUrl(URL_PLACEHOLDER, scheme)).toEqual({reason: URL_NOT_HTTPS});
    }

    // …and a template that carries the scheme itself, which is the same check one layer up.
    expect(resolveUrl(`javascript:${URL_PLACEHOLDER}`, 'alert(1)')).toEqual({reason: URL_NOT_HTTPS});
    expect(resolveUrl(`http://example.com/${URL_PLACEHOLDER}`, 'x')).toEqual({reason: URL_NOT_HTTPS});
  });

  it('resolves an ordinary https template', () => {
    expect(resolveUrl(`https://example.com/orders/${URL_PLACEHOLDER}`, '42')).toEqual({
      href: 'https://example.com/orders/42'
    });
  });

  it('percent-encodes the value for the position it lands in', () => {
    // A path segment: the value must not be able to climb out of it, add a query or graft
    // a fragment on the end.
    expect(resolveUrl(`https://example.com/${URL_PLACEHOLDER}`, '../admin?x=1#f').href).toBe(
      'https://example.com/..%2Fadmin%3Fx%3D1%23f'
    );
    // A query value: the same encoding stops a second parameter being smuggled in.
    expect(resolveUrl(`https://example.com/s?q=${URL_PLACEHOLDER}`, 'a&admin=1').href).toBe(
      'https://example.com/s?q=a%26admin%3D1'
    );
    // The host cannot be replaced from a path position either.
    expect(resolveUrl(`https://example.com/${URL_PLACEHOLDER}`, '/evil.example').href).toBe(
      'https://example.com/%2Fevil.example'
    );
  });

  it('substitutes the value literally, not as a replacement pattern', () => {
    // `String.replace` reads `$&`, `$'` and backtick-dollar in its REPLACEMENT, so a cell
    // holding one would be expanded into part of the URL before anything parsed it. The
    // part-by-part assembly in the module is what makes this a plain substitution.
    // `'` is one of the few characters `encodeURIComponent` leaves alone; it carries no
    // structural meaning in a URL, and `$` and `&` — which do — are both escaped.
    expect(resolveUrl(`https://example.com/${URL_PLACEHOLDER}`, "$&$'").href).toBe("https://example.com/%24%26%24'");
  });

  it('substitutes at every occurrence of the placeholder', () => {
    expect(resolveUrl(`https://example.com/${URL_PLACEHOLDER}/${URL_PLACEHOLDER}`, 'x').href).toBe(
      'https://example.com/x/x'
    );
  });

  it('refuses a template with no placeholder, at entry', () => {
    // Otherwise every row in the column links to the same static page, which looks like a
    // working transformer and is not one.
    expect(templateRefusal('https://example.com/')).toBe(URL_TEMPLATE_REFUSAL);
    expect(templateRefusal(`https://example.com/${URL_PLACEHOLDER}`)).toBeNull();
    expect(resolveUrl('https://example.com/', 'x')).toEqual({reason: URL_TEMPLATE_REFUSAL});
  });

  it('refuses a template that does not make an absolute url', () => {
    expect(resolveUrl(`/reports/${URL_PLACEHOLDER}`, 'x')).toEqual({reason: URL_NOT_A_URL});
    // A bare placeholder over a column that does NOT hold urls: the value supplies the
    // whole address, and `42` is not one.
    expect(resolveUrl(URL_PLACEHOLDER, '42')).toEqual({reason: URL_NOT_A_URL});
  });

  it('links a column that already holds urls, which is what the leading position is for', () => {
    expect(resolveUrl(URL_PLACEHOLDER, 'https://example.com/a?b=1').href).toBe('https://example.com/a?b=1');
    expect(resolveUrl(`${URL_PLACEHOLDER}/details`, 'https://example.com/a').href).toBe(
      'https://example.com/a/details'
    );
  });
});

describe('the transformed cell keeps the raw value as its text', () => {
  it('links the value the user recognises, never the url', () => {
    const rendering = transformCell('42', {kind: 'url', template: `https://example.com/${URL_PLACEHOLDER}`});
    expect(rendering).toEqual({text: '42', href: 'https://example.com/42', reason: undefined});
  });

  it('carries the reason when there is no link', () => {
    const rendering = transformCell('javascript:alert(1)', {kind: 'url', template: URL_PLACEHOLDER});
    expect(rendering?.href).toBeUndefined();
    expect(rendering?.reason).toBe(URL_NOT_HTTPS);
    expect(rendering?.text).toBe('javascript:alert(1)');
  });
});
