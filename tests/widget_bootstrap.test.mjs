// The widget bootstrap used to await config, then contact, then history — three
// sequential round trips before the first paint. These checks pin the structure
// that makes them parallel, and the ordering guarantee that keeps the contact
// gate correct (history is fetched early but painted only after the gate).
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
  const start = source.indexOf(`async function ${name}(`);
  const offset = start === -1 ? source.indexOf(`function ${name}(`) : start;
  if (offset === -1) throw new Error(`widget.js: function ${name} not found`);
  return extractFrom(offset);
}

function body(fnSource) {
  return fnSource.slice(fnSource.indexOf('{') + 1);
}

const init = body(extractFn('init'));
const fetchHistory = body(extractFn('fetchServerHistory'));
const renderHistory = extractFn('renderServerHistory');
const loadConfig = body(extractFn('loadServerConfig'));
const loadContact = body(extractFn('loadServerContact'));

// --- parallelism ------------------------------------------------------------
check('init issues one Promise.all', (init.match(/Promise\.all\(/g) || []).length === 1, init);

const allMatch = init.match(/Promise\.all\(\[([\s\S]*?)\]\)/);
const group = allMatch ? allMatch[1] : '';
check(
  'the config request is started once, before the group',
  (init.match(/loadServerConfig\(\)/g) || []).length === 1 &&
    init.indexOf('const configRequest = loadServerConfig();') !== -1,
  init,
);
check(
  'the parallel group awaits that same config request',
  group.includes('configRequest'),
  group,
);
check(
  'the parallel group starts the contact request',
  group.includes('loadServerContact()'),
  group,
);
check(
  'the parallel group starts the history request',
  group.includes('fetchServerHistory()'),
  group,
);

// The old shape awaited config on its own line before anything else.
check(
  'config is not awaited before the other bootstrap requests',
  !/^\s*await\s+loadServerConfig\(\);/m.test(init),
  init,
);
check(
  'contact is not awaited on its own line',
  !/^\s*(const \w+ = )?await\s+loadServerContact\(\);/m.test(init),
  init,
);
check(
  'history is not awaited on its own line',
  !/^\s*(const \w+ = )?await\s+loadServerHistory\(\);/m.test(init),
  init,
);

// K4: the session token is chained off the config request and both reads wait
// for it, without adding a sequential round trip to the bootstrap.
check(
  'the session token is minted after config, inside the group',
  /sessionTokenReady = configRequest\.then\(\(\) => ensureSessionToken\(\)\)/.test(init) &&
    group.includes('sessionTokenReady'),
  init,
);
check(
  'both session reads wait for the token',
  /await sessionTokenReady;/.test(body(extractFn('loadServerContact'))) &&
    /await sessionTokenReady;/.test(fetchHistory),
  { loadContact, fetchHistory },
);
// V3 F4 added the optional `X-Embed-Token` beside the session token, so both
// reads merge the two header helpers; the retry path is covered behaviourally in
// `widget_embed_token.test.mjs`.
const SESSION_READ_HEADERS =
  /headers: Object\.assign\(embedTokenHeaders\(\), sessionTokenHeaders\(\)\)/;
check(
  'session reads send the token header',
  SESSION_READ_HEADERS.test(fetchHistory) &&
    SESSION_READ_HEADERS.test(body(extractFn('loadServerContact'))),
  { loadContact, fetchHistory },
);

// K4: a session whose token chain is past its absolute lifetime can never be
// claimed again. The widget must start over instead of retrying a dead id for
// ever, and must not turn that into an unbounded loop.
const ensureToken = body(extractFn('ensureSessionToken'));
check(
  'a 403 from mint starts a new session',
  /if \(res\.status === 403\) \{/.test(ensureToken) &&
    /sessionId = newSession\(\);/.test(ensureToken),
  ensureToken,
);
check(
  'the new session is minted again exactly once',
  (ensureToken.match(/await mintSessionToken\(\)/g) || []).length === 2,
  ensureToken,
);
check(
  'a second failure gives up rather than looping',
  /if \(!res\.ok\) return '';/.test(ensureToken) &&
    !/while\s*\(|for\s*\(/.test(ensureToken),
  ensureToken,
);
check(
  'the new-session reset clears the stale token and history',
  /localStorage\.removeItem\('chat_widget_session_token'\)/.test(
    body(extractFn('newSession')),
  ) &&
    /localStorage\.removeItem\('chat_widget_history'\)/.test(
      body(extractFn('newSession')),
    ),
  extractFn('newSession'),
);
check(
  'the adopted token is stored under the widget key',
  body(extractFn('adoptSessionToken')).includes(
    "localStorage.setItem(SESSION_TOKEN_KEY, sessionToken)",
  ),
  extractFn('adoptSessionToken'),
);
check(
  'a tokenless mint still leaves the widget working',
  /return '';/.test(ensureToken) && /catch \(e\)/.test(ensureToken),
  ensureToken,
);

// --- behaviour preserved ----------------------------------------------------
check(
  'the contact form still short-circuits the bootstrap',
  /if \(contactRequired && !restoredContact\) \{\s*showContactForm\(\);\s*return;/.test(
    init,
  ),
  init,
);
check(
  'the chat input is only revealed after the contact gate',
  init.indexOf('setChatInputVisible(true)') > init.indexOf('showContactForm'),
  init,
);
check(
  'the contact request is skipped when the visitor already gave details',
  /contactRequired \? loadServerContact\(\)/.test(init),
  init,
);
check(
  'server history is painted only after the gate',
  init.indexOf('renderServerHistory(history ? history.items : null)') >
    init.indexOf('showContactForm'),
  init,
);
check(
  'the local history fallback is kept',
  /if \(!loadedFromServer\) loadHistory\(\);/.test(init),
  init,
);
check(
  'the greeting/local fallback path is unchanged',
  init.includes("localStorage.setItem('chat_widget_initialized', 'true')") &&
    init.includes('renderSuggestions();'),
  init,
);

// Starting the history request early is only safe if it never touches the DOM:
// the contact form clears the message list.
check(
  'fetchServerHistory does not paint messages',
  !/addMessage|innerHTML|appendChild/.test(fetchHistory),
  fetchHistory,
);
check(
  'renderServerHistory does the painting',
  /items\.forEach\(\(m\) => addMessage\(m\.message, m\.role, false, true\)\)/.test(
    renderHistory,
  ),
  renderHistory,
);
check(
  'renderServerHistory is a no-op without items',
  /if \(!Array\.isArray\(items\) \|\| !items\.length\) return false;/.test(renderHistory),
  renderHistory,
);
check(
  'history keeps its enable/website/api guards',
  fetchHistory.includes('!config.enableHistory') &&
    fetchHistory.includes('!hasWebsiteId') &&
    fetchHistory.includes('!config.apiUrl'),
  fetchHistory,
);
check(
  'config and contact requests keep their own guards',
  loadConfig.includes('hasWebsiteId') &&
    loadConfig.includes('config.apiUrl') &&
    loadContact.includes('hasWebsiteId'),
  { loadConfig, loadContact },
);

if (failures > 0) {
  console.error(`\n${failures} check(s) failed, ${passed} passed`);
  process.exit(1);
}
console.log(`\n${passed} checks passed`);
