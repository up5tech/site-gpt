// V3 F4: the optional embed token has to ride along with every public widget
// request, without changing any request that does not configure one.
//
// The widget's real source is evaluated here (same technique as
// `widget_session_token.test.mjs`), so a call site that forgets the header — or
// a retry path that drops it — fails instead of being pattern-matched.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { buildWidgetSnippet } from '../frontend/src/utils/widgetSnippet.ts';

const source = readFileSync(
  new URL('../src/site_gpt/app/scripts/widget.js', import.meta.url),
  'utf8',
);

/** The function's own source, found by brace matching (comments included). */
function extractFunction(name) {
  const match = new RegExp(`(?:async )?function ${name}\\(`).exec(source);
  assert.ok(match, `${name} is missing from widget.js`);
  const start = match.index;
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    else if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`unbalanced braces in ${name}`);
}

// --- the header helper -------------------------------------------------------

function headersFor(embedToken) {
  const factory = new Function(
    'config',
    `${extractFunction('embedTokenHeaders')}\nreturn embedTokenHeaders();`,
  );
  return factory({ embedToken });
}

test('no configured token sends no header at all', () => {
  assert.deepEqual(headersFor(''), {});
  assert.deepEqual(headersFor(undefined), {});
});

test('a configured token becomes X-Embed-Token', () => {
  assert.deepEqual(headersFor('emb_abc123'), {
    'X-Embed-Token': 'emb_abc123',
  });
});

// --- a real request: the session-token mint ---------------------------------

async function runMint(embedToken) {
  const calls = [];
  const fetchStub = async (url, init) => {
    calls.push({ url, init });
    return { status: 201, ok: true, json: async () => ({ token: 'sst_1' }) };
  };
  const factory = new Function(
    'config',
    'sessionId',
    'fetch',
    `${extractFunction('embedTokenHeaders')}
${extractFunction('mintSessionToken')}
return mintSessionToken();`,
  );
  await factory(
    { apiUrl: 'https://api.test/', website_id: 'site-1', embedToken },
    'sid-1',
    fetchStub,
  );
  return calls;
}

test('a tokenless mint keeps the V2.1 request shape exactly', async () => {
  const [call] = await runMint('');

  assert.equal(call.url, 'https://api.test/api/session-token');
  assert.equal(call.init.method, 'POST');
  assert.deepEqual(call.init.headers, { 'Content-Type': 'application/json' });
  assert.deepEqual(JSON.parse(call.init.body), {
    website_id: 'site-1',
    session_id: 'sid-1',
  });
});

test('a configured token is added to the mint request and nothing else changes', async () => {
  const [call] = await runMint('emb_abc123');

  assert.deepEqual(call.init.headers, {
    'Content-Type': 'application/json',
    'X-Embed-Token': 'emb_abc123',
  });
  assert.deepEqual(JSON.parse(call.init.body), {
    website_id: 'site-1',
    session_id: 'sid-1',
  });
});

// --- the retry path: history read after a 403 -------------------------------

async function runHistory(embedToken) {
  const calls = [];
  const fetchStub = async (url, init) => {
    calls.push({ url, init });
    const status = calls.length === 1 ? 403 : 200;
    return { status, ok: status === 200, json: async () => ({ items: [] }) };
  };
  const factory = new Function(
    'config',
    'initialToken',
    'fetch',
    `let sessionToken = initialToken;
const sessionId = 'sid-1';
const hasWebsiteId = true;
${extractFunction('embedTokenHeaders')}
function sessionTokenHeaders() {
  return sessionToken ? { 'X-Session-Token': sessionToken } : {};
}
function clearSessionToken() { sessionToken = ''; }
const sessionTokenReady = Promise.resolve(sessionToken);
${extractFunction('fetchServerHistory')}
return fetchServerHistory();`,
  );
  await factory(
    {
      apiUrl: 'https://api.test',
      website_id: 'site-1',
      enableHistory: true,
      embedToken,
    },
    'sst_1',
    fetchStub,
  );
  return calls;
}

test('the history retry drops the stale session token but keeps the embed token', async () => {
  const calls = await runHistory('emb_abc123');

  assert.equal(calls.length, 2, 'one retry after the 403');
  assert.equal(calls[0].url, calls[1].url, 'the retry hits the same URL');
  assert.deepEqual(calls[0].init.headers, {
    'X-Embed-Token': 'emb_abc123',
    'X-Session-Token': 'sst_1',
  });
  assert.deepEqual(
    calls[1].init.headers,
    { 'X-Embed-Token': 'emb_abc123' },
    'the embed token is not a session credential and must survive the reset',
  );
});

test('without an embed token the retry sends no headers', async () => {
  const calls = await runHistory('');

  assert.deepEqual(calls[1].init.headers, {});
});

// --- the install snippet ----------------------------------------------------

const LEGACY_SNIPPET = `<!-- Site GPT Chat Widget -->
<script>
  window.ChatWidgetConfig = {
    website_id: 'w1',
    apiUrl: 'https://api.test'
  };
</script>
<script src="https://api.test/widget.js?v=abc" async></script>`;

test('a snippet without a token is byte-for-byte the V2.1 snippet', () => {
  assert.equal(
    buildWidgetSnippet({ websiteId: 'w1', apiUrl: 'https://api.test', version: 'abc' }),
    LEGACY_SNIPPET,
  );
});

test('a snippet with a token carries it inside ChatWidgetConfig', () => {
  const snippet = buildWidgetSnippet({
    websiteId: 'w1',
    apiUrl: 'https://api.test',
    version: 'abc',
    embedToken: 'emb_abc123',
  });

  assert.ok(
    snippet.includes("embedToken: 'emb_abc123'"),
    `missing embedToken line:\n${snippet}`,
  );
  assert.ok(snippet.includes("website_id: 'w1'"));
  assert.ok(snippet.includes('/widget.js?v=abc'));
});

test('a tampered token cannot break out of the snippet string', () => {
  const snippet = buildWidgetSnippet({
    websiteId: 'w1',
    apiUrl: 'https://api.test',
    version: 'abc',
    embedToken: "emb_ab'};alert(1)//",
  });

  assert.ok(!snippet.includes('alert(1)'), snippet);
  assert.ok(!snippet.includes("embedToken: 'emb_ab'"), snippet);
  assert.ok(snippet.includes("embedToken: 'emb_abalert1'"), snippet);
});
