// node --test tests/worker.test.mjs : the assistant's server, with the AI service and data sources stubbed.
import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../worker/genie.js';

const env = { ANTHROPIC_API_KEY: 'test-key', SITE_ORIGIN: 'https://example.test', SITE_DATA: 'https://example.test/data/' };

function stub(handlers) {
  const calls = [];
  globalThis.fetch = async (url, opts = {}) => {
    calls.push({ url: String(url), opts });
    for (const [match, fn] of handlers) if (String(url).includes(match)) return fn(String(url), opts);
    return new Response('not found', { status: 404 });
  };
  return calls;
}
const post = body => new Request('https://w.test/ask', { method: 'POST', body: JSON.stringify(body) });

test('runs a tool, then answers, and never sends the key to the data sources', async () => {
  let turn = 0;
  const calls = stub([
    ['api.anthropic.com', async (u, o) => {
      const body = JSON.parse(o.body);
      turn += 1;
      if (turn === 1) {
        assert.equal(body.model, 'claude-haiku-5-5');
        return Response.json({ stop_reason: 'tool_use', usage: { input_tokens: 10, output_tokens: 5 },
          content: [{ type: 'tool_use', id: 't1', name: 'query_dataset', input: { id: 'iahh-g8bj', select: 'count(*) as n' } }] });
      }
      const last = body.messages[body.messages.length - 1];
      assert.equal(last.content[0].type, 'tool_result');
      assert.match(last.content[0].content, /453547/);
      return Response.json({ stop_reason: 'end_turn', usage: { input_tokens: 20, output_tokens: 8 },
        content: [{ type: 'text', text: '453,547 requests (311 Service Requests, iahh-g8bj).' }] });
    }],
    ['data.calgary.ca/resource/iahh-g8bj.json', async () => Response.json([{ n: '453547' }])],
  ]);
  const r = await worker.fetch(post({ messages: [{ role: 'user', content: 'How many 311 requests?' }], city: 'calgary' }), env);
  const d = await r.json();
  assert.equal(r.status, 200);
  assert.match(d.answer, /453,547/);
  assert.deepEqual(d.steps.map(s => s.tool), ['query_dataset']);
  for (const c of calls.filter(c => !c.url.includes('api.anthropic.com'))) {
    assert.ok(!JSON.stringify(c.opts).includes('test-key'), 'key must only go to the AI service');
  }
});

test('access code and limits', async () => {
  stub([]);
  let r = await worker.fetch(post({ messages: [{ role: 'user', content: 'hi' }] }), { ...env, ACCESS_CODE: 'open sesame' });
  assert.equal(r.status, 401);
  const kv = new Map();
  const LIMITS = { get: async k => kv.get(k) ?? null, put: async (k, v) => kv.set(k, v) };
  stub([['api.anthropic.com', async () => Response.json({ stop_reason: 'end_turn', content: [{ type: 'text', text: 'ok' }] })]]);
  const e2 = { ...env, LIMITS, DAILY_LIMIT_IP: '2' };
  for (let i = 0; i < 2; i++) assert.equal((await worker.fetch(post({ messages: [{ role: 'user', content: 'q' }] }), e2)).status, 200);
  assert.equal((await worker.fetch(post({ messages: [{ role: 'user', content: 'q' }] }), e2)).status, 429);
});

test('no key on the server: a clear message, not a crash', async () => {
  const r = await worker.fetch(post({ messages: [{ role: 'user', content: 'q' }] }), { SITE_ORIGIN: '*' });
  assert.equal(r.status, 503);
});

test('calculate only accepts arithmetic', async () => {
  let turn = 0;
  stub([['api.anthropic.com', async (u, o) => {
    turn += 1;
    if (turn === 1) return Response.json({ stop_reason: 'tool_use', content: [
      { type: 'tool_use', id: 'a', name: 'calculate', input: { expression: '1,200 / 4' } },
      { type: 'tool_use', id: 'b', name: 'calculate', input: { expression: 'process.exit()' } }] });
    const res = JSON.parse(o.body).messages.at(-1).content;
    assert.equal(res[0].content, '300');
    assert.match(res[1].content, /Only numbers/);
    return Response.json({ stop_reason: 'end_turn', content: [{ type: 'text', text: 'done' }] });
  }]]);
  const r = await worker.fetch(post({ messages: [{ role: 'user', content: 'q' }] }), env);
  assert.equal(r.status, 200);
});
