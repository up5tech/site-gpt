// Security regression test for the chat widget's markdown renderer.
//
// widget.js is a plain browser script (it attaches a shadow DOM on load), so we
// can't import it here. Instead we extract the pure string helpers — they have
// no DOM dependencies — and run the malicious payloads through exactly the code
// that ships to customers. Run: node tests/widget_sanitize.test.mjs
import { readFileSync } from 'node:fs';

const source = readFileSync(
  new URL('../src/site_gpt/app/scripts/widget.js', import.meta.url),
  'utf8',
);

function extractFn(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start === -1) throw new Error(`widget.js: function ${name} not found`);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    else if (source[i] === '}' && --depth === 0) {
      return source.slice(start, i + 1);
    }
  }
  throw new Error(`widget.js: unbalanced braces around ${name}`);
}

const { escapeHtml, safeUrl, renderMarkdown } = new Function(
  `${extractFn('escapeHtml')}\n${extractFn('safeUrl')}\n${extractFn('renderMarkdown')}\n` +
    'return { escapeHtml, safeUrl, renderMarkdown };',
)();

let passed = 0;
let failures = 0;

function check(name, condition, actual) {
  if (condition) {
    passed++;
    console.log(`ok - ${name}`);
    return;
  }
  failures++;
  console.error(`FAIL - ${name}\n  got: ${JSON.stringify(actual)}`);
}

// --- HTML injection via crawled content / prompt injection -------------------
const imgPayload = renderMarkdown('<img src=x onerror="alert(1)">');
check(
  'escapes an <img onerror> payload',
  !/<img/i.test(imgPayload) && imgPayload.includes('&lt;img'),
  imgPayload,
);
check(
  'escaped payload keeps its quotes inert',
  !/onerror="/.test(imgPayload),
  imgPayload,
);

const scriptPayload = renderMarkdown('<script>alert(1)</script>');
check('escapes a <script> payload', !/<script/i.test(scriptPayload), scriptPayload);

const svgPayload = renderMarkdown('<svg/onload=alert(1)>');
check('escapes an <svg onload> payload', !/<svg/i.test(svgPayload), svgPayload);

const ampPayload = escapeHtml('a & b < c > d " e \' f');
check(
  'escapeHtml covers & < > " and \'',
  ampPayload === 'a &amp; b &lt; c &gt; d &quot; e &#39; f',
  ampPayload,
);

// --- Link scheme restriction ------------------------------------------------
for (const scheme of [
  'javascript:alert(1)',
  'JavaScript:alert(1)',
  '  javascript:alert(1)',
  'data:text/html,<b>x</b>',
  'vbscript:msgbox(1)',
  'file:///etc/passwd',
]) {
  const out = renderMarkdown(`[click me](${scheme})`);
  check(
    `refuses ${JSON.stringify(scheme)} as a link`,
    !/<a/i.test(out) && !/javascript:/i.test(out),
    out,
  );
  check(`keeps the label for ${JSON.stringify(scheme)}`, out.includes('click me'), out);
}

const attrBreak = renderMarkdown('[x](https://evil.test/"onmouseover="alert(1))');
check(
  'cannot break out of the href attribute',
  !/onmouseover="/.test(attrBreak),
  attrBreak,
);

const goodLink = renderMarkdown('[docs](https://example.com/a?b=1&c=2)');
check(
  'renders a plain https link',
  goodLink.includes('<a href="https://example.com/a?b=1&amp;c=2"'),
  goodLink,
);
check('adds rel=noopener noreferrer', goodLink.includes('rel="noopener noreferrer"'), goodLink);
check('adds target=_blank', goodLink.includes('target="_blank"'), goodLink);

check('safeUrl rejects javascript:', safeUrl('javascript:alert(1)') === null);
check('safeUrl accepts https', safeUrl('https://example.com') === 'https://example.com');

// --- Markdown still works for honest content --------------------------------
check('bold still renders', renderMarkdown('**hi**') === '<b>hi</b>');
check('inline code still renders', renderMarkdown('`x`') === '<code>x</code>');
check('fenced code still renders', renderMarkdown('```a\nb```').includes('<pre>'));
check('newlines become <br>', renderMarkdown('a\nb') === 'a<br>b');
check('empty input is tolerated', renderMarkdown(undefined) === '');

if (failures > 0) {
  console.error(`\n${failures} check(s) failed, ${passed} passed`);
  process.exit(1);
}
console.log(`\n${passed} checks passed`);
