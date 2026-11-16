// Runtime checks for the widget's session-token bootstrap.
//
// `widget_bootstrap.test.mjs` pins the *shape* of `ensureSessionToken` (it reads
// like a pattern match). This file runs the real function: the source is taken
// from `widget.js` and evaluated with the few globals it closes over, so the
// reset-and-mint-once behaviour is exercised rather than searched for.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(
  new URL('../src/site_gpt/app/scripts/widget.js', import.meta.url),
  'utf8',
);

/** The function's own source, found by brace matching (comments included). */
function extractFunction(name) {
  const start = source.indexOf(`async function ${name}(`);
  assert.notEqual(start, -1, `${name} is missing from widget.js`);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    else if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`unbalanced braces in ${name}`);
}

// Everything `ensureSessionToken` closes over, plus a `mintSessionToken` that
// answers from a scripted list of statuses and records the session id it was
// called with — that id is the whole point of the 403 branch.
const PRELUDE = [
  "let sessionToken = '';",
  "let sessionId = storage.get('chat_widget_session');",
  'const hasWebsiteId = true;',
  "const config = { apiUrl: 'http://api.test', website_id: 'site-1' };",
  "const SESSION_TOKEN_KEY = 'chat_widget_session_token';",
  'function newSession() {',
  "  const id = 'new-' + (calls.length + 1);",
  "  storage.set('chat_widget_session', id);",
  "  storage.delete('chat_widget_history');",
  "  storage.delete('chat_widget_session_token');",
  '  return id;',
  '}',
  'async function mintSessionToken() {',
  '  calls.push(sessionId);',
  '  if (throwOnFirstMint && calls.length === 1) throw new Error("offline");',
  '  const next = responses[Math.min(calls.length - 1, responses.length - 1)];',
  '  return {',
  '    status: next,',
  '    ok: next >= 200 && next < 300,',
  "    json: async () => ({ token: 'sst_new' }),",
  '  };',
  '}',
  'function adoptSessionToken(data) {',
  '  if (!data || typeof data.token !== "string" || !data.token) return "";',
  '  sessionToken = data.token;',
  '  storage.set(SESSION_TOKEN_KEY, sessionToken);',
  '  return sessionToken;',
  '}',
  'return ensureSessionToken();',
].join('\n');

async function run(responses, options = {}) {
  const calls = [];
  const storage = new Map([
    ['chat_widget_session', 'old-session'],
    ['chat_widget_history', '[{"role":"user","message":"hi"}]'],
  ]);
  const factory = new Function(
    'storage',
    'calls',
    'responses',
    'throwOnFirstMint',
    `const ensureSessionToken = ${extractFunction('ensureSessionToken')};\n${PRELUDE}`,
  );
  const token = await factory(storage, calls, responses, options.throwOnFirstMint ?? false);
  return {
    token,
    calls,
    sessionId: storage.get('chat_widget_session'),
    stored: storage.get('chat_widget_session_token'),
    history: storage.get('chat_widget_history'),
  };
}

test('a 403 restarts the session and mints once more', async () => {
  const result = await run([403, 200]);

  assert.equal(result.token, 'sst_new');
  assert.equal(result.calls.length, 2, 'the dead id must not be retried for ever');
  assert.equal(result.calls[0], 'old-session');
  assert.notEqual(
    result.calls[1],
    'old-session',
    'the retry has to use the new session id, not the dead one',
  );
  assert.equal(result.sessionId, result.calls[1]);
  assert.equal(result.stored, 'sst_new', 'the new token is persisted');
  assert.equal(result.history, undefined, 'the old local history is cleared');
});

test('a second 403 gives up instead of looping', async () => {
  const result = await run([403, 403]);

  assert.equal(result.token, '');
  assert.equal(result.calls.length, 2, 'one retry only');
  assert.notEqual(result.calls[1], 'old-session');
  assert.equal(result.stored, undefined);
});

test('a 200 on the first try mints once and keeps the session', async () => {
  const result = await run([200]);

  assert.equal(result.token, 'sst_new');
  assert.equal(result.calls.length, 1);
  assert.equal(result.calls[0], 'old-session');
  assert.equal(result.sessionId, 'old-session', 'no reset without a 403');
});

test('an offline mint leaves the widget working without a token', async () => {
  const result = await run([200], { throwOnFirstMint: true });

  assert.equal(result.token, '');
  assert.equal(result.calls.length, 1);
  assert.equal(result.sessionId, 'old-session');
});
