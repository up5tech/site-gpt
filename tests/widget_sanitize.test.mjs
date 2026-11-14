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

// Slice out a block starting at `start` and ending at its matching brace.
// Throws (failing the run) if the block is missing or unbalanced, so a rename
// or a syntax change in widget.js can never make the checks silently pass.
function extractFrom(start, trailing = 0) {
  let depth = 0;
  for (let i = source.indexOf('{', start); i !== -1 && i < source.length; i++) {
    if (source[i] === '{') depth++;
    else if (source[i] === '}' && --depth === 0) {
      return source.slice(start, i + 1 + trailing);
    }
  }
  throw new Error(`widget.js: unbalanced braces from offset ${start}`);
}

function extractFn(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start === -1) throw new Error(`widget.js: function ${name} not found`);
  return extractFrom(start);
}

function extractConst(name) {
  const start = source.indexOf(`const ${name} = `);
  if (start === -1) throw new Error(`widget.js: const ${name} not found`);
  return extractFrom(start, 1); // include the trailing ';'
}

function extractSection(title) {
  const marker = `// ================= ${title} =================`;
  const start = source.indexOf(marker);
  if (start === -1) throw new Error(`widget.js: section ${title} not found`);
  const next = source.indexOf('// =================', start + marker.length);
  return source.slice(start, next === -1 ? source.length : next);
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
    `refuses ${JSON.stringify(scheme)}: no link and label kept as text`,
    !/<a/i.test(out) && !/javascript:/i.test(out) && out.includes('click me'),
    out,
  );
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

// --- Structural invariant: nothing but our own tags can come out ------------
// Rather than trusting a payload list, assert the property on every sample:
// the output may only contain the five tags renderMarkdown emits, and every
// href it emits must be absolute http(s).
const ALLOWED_TAGS = new Set(['a', 'b', 'code', 'pre', 'br']);

for (const payload of [
  '<img src=x onerror="alert(1)">',
  '"><script>alert(1)</script>',
  '<a href="javascript:alert(1)">x</a>',
  '<<script>script>alert(1)<</script>/script>',
  '&#60;script&#62;alert(1)&#60;/script&#62;',
  '[<img src=x onerror="alert(1)">](https://example.com)',
  '[x](javascript:alert(1))',
  '[x](https://a.test/" onmouseover="alert(1))',
  '**<svg/onload=alert(1)>**',
  '`<iframe src=//evil.test>`',
  '```\n<iframe src=//evil.test>\n```',
  '[x](https://a.test/?q=<img src=x onerror=1>)',
  '[x](https://a.test)\n\n<img src=x onerror=1>',
]) {
  const html = renderMarkdown(payload);
  const unexpected = [...html.matchAll(/<\/?([a-zA-Z0-9]+)/g)]
    .map((m) => m[1].toLowerCase())
    .filter((tag) => !ALLOWED_TAGS.has(tag));
  const badHrefs = [...html.matchAll(/href="([^"]*)"/g)]
    .map((m) => m[1])
    .filter((href) => !/^https?:\/\//i.test(href));

  check(
    `payload neutralised: ${JSON.stringify(payload)}`,
    unexpected.length === 0 && badHrefs.length === 0,
    { html, unexpected, badHrefs },
  );
}

// --- Owner-supplied config values ------------------------------------------
// botName / placeholder / colours / dimensions are interpolated into
// shadow.innerHTML and a form template, and into CSS.
const sanitizer = new Function(
  `${extractConst('DEFAULT_CONFIG')}\n${extractSection('SANITIZE CONFIG')}\n` +
    'return { sanitizeConfig, safeColor, safeDimension, safeText };',
)();

const { sanitizeConfig, safeColor, safeDimension, safeText } = sanitizer;
const DEFAULT_PRIMARY = '#4c74af';

for (const payload of [
  'red;} .x { color: red }',
  'expression(alert(1))',
  'url(javascript:alert(1))',
  'url(//attacker.example.net/leak.png)',
  '#fff;}body{display:none',
  '" onmouseover="alert(1)',
  'javascript:alert(1)',
]) {
  const out = safeColor(payload, DEFAULT_PRIMARY);
  check(`rejects unsafe colour ${JSON.stringify(payload)}`, out === DEFAULT_PRIMARY, out);
}

for (const ok of ['#fff', '#4c74af', '#4c74afcc', 'rgb(1, 2, 3)', 'rgba(1,2,3,0.5)', 'hsl(210, 50%, 40%)']) {
  check(`accepts colour ${ok}`, safeColor(ok, DEFAULT_PRIMARY) === ok, safeColor(ok, DEFAULT_PRIMARY));
}

for (const payload of [
  '1px;} body { display: none }',
  '360px" onload="alert(1)',
  '99999px',
  'calc(100% - 2px)',
  '1e9px',
  '',
]) {
  check(`rejects unsafe dimension ${JSON.stringify(payload)}`, safeDimension(payload, '360px') === '360px');
}

for (const ok of ['360px', '480px', '20rem', '100%', '90vw']) {
  check(`accepts dimension ${ok}`, safeDimension(ok, '360px') === ok);
}

check('safeText trims and caps length', safeText('  hi  ', 'x') === 'hi');
check('safeText caps at the max length', safeText('a'.repeat(50), 'x', 10).length === 10);
check('safeText falls back for empty input', safeText('   ', 'fallback') === 'fallback');
check('safeText falls back for non-strings', safeText(42, 'fallback') === 'fallback');

const maliciousConfig = sanitizeConfig({
  botName: '<img src=x onerror="alert(1)">',
  placeholder: '" onfocus="alert(1)',
  width: '360px"><script>alert(1)</script>',
  height: '1px;} body { display: none }',
  footerColor: 'red; background: url(//attacker.example.net/leak.png)',
  position: 'somewhere-else',
  theme: {
    primaryColor: 'red;} .chat-box { display: none }',
    backgroundColor: 'url(//attacker.example.net/leak.png)',
  },
});

check('malicious primary colour falls back', maliciousConfig.theme.primaryColor === DEFAULT_PRIMARY, maliciousConfig.theme.primaryColor);
check('malicious background colour falls back', maliciousConfig.theme.backgroundColor === '#ffffff', maliciousConfig.theme.backgroundColor);
check('malicious footer colour falls back', maliciousConfig.footerColor === DEFAULT_PRIMARY, maliciousConfig.footerColor);
check('malicious width falls back', maliciousConfig.width === '360px', maliciousConfig.width);
check('malicious height falls back', maliciousConfig.height === '480px', maliciousConfig.height);
check('unknown position falls back', maliciousConfig.position === 'bottom-right', maliciousConfig.position);
check(
  'injected botName cannot become markup once escaped',
  !/<img/i.test(escapeHtml(maliciousConfig.botName)),
  escapeHtml(maliciousConfig.botName),
);
check(
  'injected placeholder cannot break out of the attribute',
  !/"\s*onfocus/i.test(escapeHtml(maliciousConfig.placeholder)),
  escapeHtml(maliciousConfig.placeholder),
);

const legitConfig = sanitizeConfig({
  botName: 'Acme Support',
  placeholder: 'Ask about pricing',
  welcomeMessage: 'Hi! How can I help?',
  width: '400px',
  height: '600px',
  position: 'bottom-left',
  footerColor: 'rgb(20, 30, 40)',
  theme: { primaryColor: '#123456', backgroundColor: '#fafafa' },
});
check(
  'legitimate config is left unchanged',
  legitConfig.botName === 'Acme Support' &&
    legitConfig.placeholder === 'Ask about pricing' &&
    legitConfig.welcomeMessage === 'Hi! How can I help?' &&
    legitConfig.width === '400px' &&
    legitConfig.height === '600px' &&
    legitConfig.position === 'bottom-left' &&
    legitConfig.footerColor === 'rgb(20, 30, 40)' &&
    legitConfig.theme.primaryColor === '#123456' &&
    legitConfig.theme.backgroundColor === '#fafafa',
  JSON.stringify(legitConfig),
);

// --- The sinks and interpolation sites themselves --------------------------
// The helpers above could stay perfect while widget.js stops calling them, so
// assert the call sites too: both message bubbles render through
// renderMarkdown, source citations never go through innerHTML, and only values
// that sanitizeConfig validated are interpolated into markup.
check(
  'escapeHtml runs before the markdown replacements',
  extractFn('renderMarkdown').indexOf('escapeHtml(') <
    extractFn('renderMarkdown').indexOf('<pre>'),
);
check(
  'chat bubbles render through renderMarkdown',
  /bubble\.innerHTML\s*=\s*renderMarkdown\(/.test(source),
);
check(
  'streamed replies render through renderMarkdown',
  /thinkingMsg\.innerHTML\s*=\s*renderMarkdown\(/.test(source),
);
check('source citations never use innerHTML', !/src\.innerHTML/.test(source));
check('source links are validated with safeUrl', /safeUrl\(s\.url\)/.test(source));
check(
  'template escapes botName',
  source.includes('${escapeHtml(config.botName)}'),
);
check(
  'template escapes the placeholder',
  source.includes('placeholder="${escapeHtml(config.placeholder)}"'),
);
check(
  'contact form escapes botName',
  source.includes('<b>${escapeHtml(config.botName)}</b>'),
);

const rawConfigInterpolations = [
  ...source.matchAll(/\$\{config\.([A-Za-z0-9_.]+)\}/g),
].map((m) => m[1]);
const SANITISED_CONFIG_VALUES = new Set([
  'width',
  'height',
  'footerColor',
  'theme.primaryColor',
  'theme.backgroundColor',
]);
check(
  'only sanitised config values are interpolated raw',
  rawConfigInterpolations.length > 0 &&
    rawConfigInterpolations.every((name) => SANITISED_CONFIG_VALUES.has(name)),
  rawConfigInterpolations,
);

if (failures > 0) {
  console.error(`\n${failures} check(s) failed, ${passed} passed`);
  process.exit(1);
}
console.log(`\n${passed} checks passed`);
