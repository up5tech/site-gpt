// Regression tests for the widget's V2 additions: the i18n catalogue, logo
// sanitisation, the handoff button and the consent checkbox (F9).
//
// widget.js is a plain browser script, so the tests extract the pure pieces and
// the guards around them. Structural assertions are used where the code only
// makes sense with a DOM (the contact form template): they fail loudly if the
// guard or the conditional body disappears.
// Run: node --test tests/widget_consent.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(
  new URL('../src/site_gpt/app/scripts/widget.js', import.meta.url),
  'utf8',
);

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
  return extractFrom(start, 1);
}

/** A single-line `const` such as a regex, which has no braces to match. */
function extractLineConst(name) {
  const start = source.indexOf(`const ${name} = `);
  if (start === -1) throw new Error(`widget.js: const ${name} not found`);
  const end = source.indexOf(';\n', start);
  if (end === -1) throw new Error(`widget.js: const ${name} is not terminated`);
  return source.slice(start, end + 2);
}

const TRANSLATIONS = new Function(`${extractConst('TRANSLATIONS')}\nreturn TRANSLATIONS;`)();

/** `t()` as it ships, bound to a language and a set of owner overrides. */
function makeT(language, overrides = {}) {
  return new Function(
    `${extractConst('TRANSLATIONS')}\n` +
      `let uiLanguage = ${JSON.stringify(language)};\n` +
      `let uiStrings = ${JSON.stringify(overrides)};\n` +
      `${extractFn('t')}\n` +
      'return t;',
  )();
}

const { safeLogoUrl } = new Function(
  `${extractLineConst('LOGO_HTTPS')}\n${extractLineConst('LOGO_DATA')}\n` +
    `${extractFn('safeLogoUrl')}\nreturn { safeLogoUrl };`,
)();

// --- i18n -------------------------------------------------------------------

test('English falls back to the text at the call site', () => {
  const t = makeT('en');
  assert.equal(t('send', 'Send'), 'Send');
  assert.equal(t('someNewKey', 'Fallback'), 'Fallback');
});

test('Vietnamese ships its own labels', () => {
  const t = makeT('vi');
  assert.equal(t('send', 'Send'), 'Gửi');
  assert.equal(t('talkToHuman', 'Talk to a human'), 'Nói chuyện với người thật');
});

test('owner UI strings win over the catalogue', () => {
  const t = makeT('vi', { send: 'Gửi đi' });
  assert.equal(t('send', 'Send'), 'Gửi đi');
  assert.equal(t('clear', 'Clear'), 'Xoá');
});

test('the catalogue has the consent and handoff strings', () => {
  const vi = TRANSLATIONS.vi;
  for (const key of [
    'consentAgree',
    'privacyPolicy',
    'consentRequired',
    'handoffThanks',
    'handoffFailed',
    'talkToHuman',
  ]) {
    assert.equal(typeof vi[key], 'string', `missing vi.${key}`);
    assert.ok(vi[key].length > 0, `empty vi.${key}`);
  }
});

// --- Logo sanitisation ------------------------------------------------------

test('https logo URLs are accepted', () => {
  assert.equal(
    safeLogoUrl('https://cdn.example.com/logo.png'),
    'https://cdn.example.com/logo.png',
  );
});

test('raster data URIs are accepted', () => {
  const png = 'data:image/png;base64,iVBORw0KGgo=';
  assert.equal(safeLogoUrl(png), png);
});

test('script-bearing logo URLs are dropped', () => {
  for (const payload of [
    'javascript:alert(1)',
    'JavaScript:alert(1)',
    'data:text/html,<b>x</b>',
    'data:image/svg+xml;base64,PHN2Zz4=',
    'http://insecure.example.com/logo.png',
    'logo.png',
    '',
    null,
    undefined,
  ]) {
    assert.equal(safeLogoUrl(payload), '', `accepted ${JSON.stringify(payload)}`);
  }
});

// --- Handoff button ---------------------------------------------------------

test('the handoff button follows the setting and its label is sanitised', () => {
  assert.match(source, /handoffBtn\.hidden = !config\.handoffEnabled/);
  assert.match(source, /safeText\(\s*cfg\.handoff_label/);
  assert.match(source, /t\(\s*'talkToHuman'/);
  assert.match(source, /config\.handoffEnabled =\s*String\(cfg\.handoff_enabled\)/);
});

// --- Consent (F9) -----------------------------------------------------------

test('consent is off by default, so a V1 embed is unchanged', () => {
  assert.match(source, /requireConsent: false/);
  assert.match(source, /privacyPolicyUrl: ''/);
});

test('the consent row only renders when the owner turned it on', () => {
  assert.match(source, /const consentRow = config\.requireConsent/);
  assert.match(source, /name="consent" type="checkbox"/);
  assert.match(source, /\$\{consentRow\}/);
});

test('the policy link goes through safeUrl', () => {
  assert.match(source, /const policyUrl = config\.requireConsent\s*\?\s*safeUrl\(config\.privacyPolicyUrl\)/);
  assert.match(source, /rel="noopener noreferrer"/);
});

test('the form cannot submit unchecked', () => {
  assert.match(
    source,
    /if \(config\.requireConsent && !\(form\.consent && form\.consent\.checked\)\)/,
  );
  assert.match(source, /t\(\s*'consentRequired'/);
});

test('consent is only sent when required', () => {
  assert.match(source, /\.\.\.\(config\.requireConsent \? \{ consent: true \} : \{\}\)/);
});

test('the server config supplies both consent values', () => {
  assert.match(source, /cfg\.require_consent !== undefined/);
  assert.match(source, /safeUrl\(cfg\.privacy_policy_url\)/);
});
