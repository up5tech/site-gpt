// Widget live agent replies (V3-43).
//
// The reply is already stored server-side; the widget's job is to notice it,
// show it once, and resume from a cursor after a reconnect. That logic is pure
// enough to run for real here: the functions are extracted from widget.js and
// evaluated with no DOM, so the dedupe/cursor rules are executed rather than
// pattern-matched.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(
  new URL('../src/site_gpt/app/scripts/widget.js', import.meta.url),
  'utf8',
);

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} is missing from widget.js`);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    else if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`unbalanced braces in ${name}`);
}

function helpers() {
  const factory = new Function(`
    ${extractFunction('agentCursorOf')}
    ${extractFunction('agentMessagesToShow')}
    ${extractFunction('parseAgentFrame')}
    ${extractFunction('agentEngaged')}
    ${extractFunction('parseAgentState')}
    return {
      agentCursorOf,
      agentMessagesToShow,
      parseAgentFrame,
      agentEngaged,
      parseAgentState,
    };
  `);
  return factory();
}

function row(id, role, message, minute) {
  return {
    id,
    role,
    message,
    created_at: `2026-11-19T12:0${minute}:00+00:00`,
  };
}

test('only agent rows are shown, but every row moves the cursor', () => {
  const { agentMessagesToShow } = helpers();
  const items = [
    row('a', 'user', 'where is my order?', 1),
    row('b', 'agent', 'checking now', 2),
    row('c', 'assistant', 'shipping today', 3),
    row('d', 'agent', 'shipped!', 4),
  ];

  const result = agentMessagesToShow(items, '');

  assert.deepEqual(result.messages, ['checking now', 'shipped!']);
  assert.equal(result.cursor, `2026-11-19T12:04:00+00:00|d`);
});

test('rows at or below the cursor are not shown again after a reconnect', () => {
  const { agentMessagesToShow } = helpers();
  const seen = `2026-11-19T12:02:00+00:00|b`;
  const items = [
    row('a', 'agent', 'old reply', 1),
    row('b', 'agent', 'already seen', 2),
    row('c', 'agent', 'new reply', 3),
  ];

  const result = agentMessagesToShow(items, seen);

  assert.deepEqual(result.messages, ['new reply']);
  assert.equal(result.cursor, '2026-11-19T12:03:00+00:00|c');
});

test('a live frame newer than the cursor is shown, an older one is dropped', () => {
  const { agentMessagesToShow } = helpers();
  const cursor = `2026-11-19T12:05:00+00:00|e`;

  assert.deepEqual(agentMessagesToShow([row('f', 'agent', 'later', 6)], cursor).messages, [
    'later',
  ]);
  assert.deepEqual(agentMessagesToShow([row('a', 'agent', 'replay', 1)], cursor).messages, []);
});

test('malformed rows cannot move the cursor or render', () => {
  const { agentMessagesToShow } = helpers();
  const items = [
    { role: 'agent', message: 'no id' },
    { id: 'x', role: 'agent', message: 'no timestamp' },
    null,
    row('y', 'agent', 'fine', 7),
  ];

  const result = agentMessagesToShow(items, '');

  assert.deepEqual(result.messages, ['fine']);
  assert.equal(result.cursor, '2026-11-19T12:07:00+00:00|y');
});

test('an agent row without text is skipped but still advances', () => {
  const { agentMessagesToShow } = helpers();
  const items = [row('a', 'agent', '', 1), row('b', 'user', 'hi', 2)];

  const result = agentMessagesToShow(items, '');

  assert.deepEqual(result.messages, []);
  assert.equal(result.cursor, '2026-11-19T12:02:00+00:00|b');
});

test('an SSE message frame is parsed and other frames are ignored', () => {
  const { parseAgentFrame } = helpers();
  const payload = {
    id: 'msg-1',
    role: 'agent',
    message: 'hello there',
    created_at: '2026-11-19T12:01:00+00:00',
  };

  const parsed = parseAgentFrame(
    `id: msg-1\nevent: message\ndata: ${JSON.stringify(payload)}`,
  );
  assert.deepEqual(parsed, payload);

  assert.equal(parseAgentFrame(': heartbeat 2026-11-19T12:01:00+00:00'), null);
  assert.equal(parseAgentFrame('retry: 3000'), null);
  assert.equal(parseAgentFrame('event: error\ndata: {"event":"x"}'), null);
  assert.equal(parseAgentFrame('event: message\ndata: not json'), null);
  assert.equal(parseAgentFrame(`event: message\ndata: ${JSON.stringify({ role: 'agent' })}`), null);
});

test('the widget streams with fetch and keeps a polling fallback', () => {
  // `EventSource` cannot send `X-Session-Token`, so the live path must be a
  // fetch body reader; the cursor endpoint is what runs when that fails.
  assert.equal(source.includes('EventSource'), false);
  assert.ok(source.includes('/api/chat/messages/stream?'));
  assert.ok(source.includes('/api/chat/messages?'));
  assert.ok(source.includes('scheduleAgentPoll('));
  // Both tokens go on the request: the session token identifies the visitor,
  // the embed token lets the owner revoke a deployed snippet.
  assert.ok(source.includes('embedTokenHeaders(), sessionTokenHeaders()'));
});

test('a new session forgets the previous transcript cursor', () => {
  const start = source.indexOf('function newSession(');
  const end = source.indexOf('return id;', start);
  assert.ok(start !== -1 && end !== -1);
  assert.ok(source.slice(start, end).includes('chat_widget_agent_cursor'));
});

test('agent replies restore from history and are saved with their role', () => {
  // A reloaded page renders the stored transcript (including agent rows) and a
  // reply received live is written to history, so the two paths agree.
  assert.ok(source.includes("addMessage(text, 'agent')"));
  assert.ok(source.includes("saveHistory('agent', text)"));
  assert.ok(source.includes('rememberAgentCursor(newest)'));
});

test('live stays off unless a teammate is queued for or answering', () => {
  const { agentEngaged } = helpers();

  assert.equal(agentEngaged('waiting'), true);
  assert.equal(agentEngaged('human'), true);
  for (const state of ['bot', 'closed', '', null, undefined]) {
    assert.equal(agentEngaged(state), false, `state ${state}`);
  }
});

test('a state frame is parsed and a malformed one is ignored', () => {
  const { parseAgentState } = helpers();

  assert.equal(
    parseAgentState('event: state\ndata: {"event":"state","state":"closed"}'),
    'closed',
  );
  assert.equal(parseAgentState('event: state\ndata: not json'), null);
  assert.equal(parseAgentState('event: state\ndata: {"state":7}'), null);
  assert.equal(parseAgentState('event: message\ndata: {"id":"x"}'), null);
  assert.equal(parseAgentState(': heartbeat'), null);
});

test('the widget only starts its live path for an engaged session', () => {
  // A plain bot chat opens no stream and sends no poll: init starts live only
  // when the restored session is queued/held, and a queued reply or a handoff
  // starts it. The old unconditional call at the end of init is gone.
  assert.ok(
    source.includes('if (history && agentEngaged(history.state)) startAgentLive();'),
  );
  assert.ok(source.includes('if (queuedReply) startAgentLive();'));
  const handoff = source.slice(
    source.indexOf('async function requestHandoff('),
    source.indexOf('handoffBtn.onclick'),
  );
  assert.ok(handoff.includes('startAgentLive()'));
  assert.equal(source.includes('\n    startAgentLive();\n'), false);
});

test('a closed or released session stops the stream and the poll', () => {
  assert.ok(source.includes('function stopAgentLive() {'));
  assert.ok(source.includes('clearTimeout(agentPollTimer)'));
  assert.ok(source.includes('agentLiveAbort.abort()'));
  assert.ok(source.includes('if (res.status === 409)'));
  assert.ok(source.includes('if (!agentLive) return;'));
  assert.ok(source.includes('if (agentLive) scheduleAgentPoll();'));
  // Both reads carry the state, so a missed notification still stops the widget.
  assert.ok(source.includes('if (!applyAgentState(data.state)) return true;'));
  assert.ok(source.includes("startsWith('event: state')"));
});
