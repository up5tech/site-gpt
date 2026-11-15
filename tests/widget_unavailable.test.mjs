// A disabled website answers with 403. The widget used to show its generic
// 'Error!' bubble there (and could ask for contact details first). These checks
// pin the clear message, the skipped contact form, and that every other error
// path is untouched.
import { readFileSync } from 'node:fs';

const source = readFileSync(
  new URL('../src/site_gpt/app/scripts/widget.js', import.meta.url),
  'utf8',
);

let passed = 0;
let failures = 0;

function check(name, condition, detail) {
  if (condition) {
    passed++;
    console.log(`ok - ${name}`);
    return;
  }
  failures++;
  console.error(`FAIL - ${name}\n  ${detail ?? ''}`);
}

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
  const asyncStart = source.indexOf(`async function ${name}(`);
  const start = asyncStart === -1 ? source.indexOf(`function ${name}(`) : asyncStart;
  if (start === -1) throw new Error(`widget.js: function ${name} not found`);
  return extractFrom(start);
}

function body(fnSource) {
  return fnSource.slice(fnSource.indexOf('{') + 1);
}

const init = body(extractFn('init'));
const send = body(extractFn('sendMessage'));
const config = body(extractFn('loadServerConfig'));
const mark = extractFn('markUnavailable');
const contactForm = body(extractFn('showContactForm'));

// --- the message itself -----------------------------------------------------
const messageConst = source.match(/const UNAVAILABLE_MESSAGE =\s*([\s\S]*?);\n/);
check('UNAVAILABLE_MESSAGE is defined', Boolean(messageConst), messageConst?.[1]);
check(
  'the message says the assistant is temporarily unavailable',
  /temporarily unavailable/i.test(messageConst?.[1] || ''),
  messageConst?.[1],
);

check('the widget tracks a disabled state', /let siteDisabled = false;/.test(source));

// --- bootstrap --------------------------------------------------------------
check(
  'widget-config 403 marks the site disabled',
  /if \(res\.status === 403\) \{\s*siteDisabled = true;\s*return;/.test(config),
  config,
);
check(
  'init returns before the contact form when disabled',
  /if \(siteDisabled\) \{\s*markUnavailable\(null\);\s*return;\s*\}/.test(init),
  init,
);
check(
  'the disabled check comes before the contact gate',
  init.indexOf('if (siteDisabled)') !== -1 &&
    init.indexOf('if (siteDisabled)') < init.indexOf('showContactForm'),
  init,
);
check(
  'history is not painted for a disabled site',
  init.indexOf('renderServerHistory(historyItems)') > init.indexOf('if (siteDisabled)'),
  init,
);

// --- the notice -------------------------------------------------------------
check(
  'markUnavailable hides the chat input',
  /setChatInputVisible\(false\)/.test(mark),
  mark,
);
check(
  'markUnavailable writes the message as text, not HTML',
  /bubble\.textContent = UNAVAILABLE_MESSAGE;/.test(mark) &&
    !/bubble\.innerHTML/.test(mark),
  mark,
);
check(
  'markUnavailable clears the thinking state',
  /classList\.remove\('thinking'\)/.test(mark),
  mark,
);

// --- chat 403 ---------------------------------------------------------------
const forbiddenIdx = send.indexOf('res.status === 403');
check('sendMessage handles a 403 response', forbiddenIdx !== -1, send);
check(
  'chat 403 shows the unavailable notice in the pending bubble',
  /if \(res\.status === 403\) \{[\s\S]*?markUnavailable\(thinkingRow\);[\s\S]*?return;/.test(
    send,
  ),
  send,
);
check(
  'chat 403 re-enables the input before returning',
  /markUnavailable\(thinkingRow\);[\s\S]*?inputEl\.disabled = false;[\s\S]*?sendBtn\.disabled = false;[\s\S]*?return;/.test(
    send,
  ),
  send,
);

// --- other errors are unchanged --------------------------------------------
check(
  'generic failures still throw into the Error! path',
  /if \(!res\.ok \|\| !res\.body\) \{\s*throw new Error\('chat request failed'\);/.test(
    send,
  ),
  send,
);
// Comments mention the old bubble too, so count only executable code.
const code = source.replace(/^\s*\/\/.*$/gm, '');
const errorBubbles = (code.match(/'Error!'/g) || []).length;
check("'Error!' is still the fallback, exactly once", errorBubbles === 1, errorBubbles);
const sendCode = send.replace(/^\s*\/\/.*$/gm, '');
const catchIdx = sendCode.indexOf('} catch (err) {');
check(
  "'Error!' is only in the catch block",
  catchIdx !== -1 && sendCode.indexOf("'Error!'") > catchIdx,
  sendCode,
);
check(
  'contact form keeps its generic failure text',
  contactForm.includes('Could not save. Please try again.'),
  contactForm,
);

// --- contact form 403 -------------------------------------------------------
check(
  'a contact save refused with 403 shows the notice instead of an error',
  /if \(res\.status === 403\) \{\s*markUnavailable\(null\);\s*return;/.test(contactForm),
  contactForm,
);

if (failures > 0) {
  console.error(`\n${failures} check(s) failed, ${passed} passed`);
  process.exit(1);
}
console.log(`\n${passed} checks passed`);
