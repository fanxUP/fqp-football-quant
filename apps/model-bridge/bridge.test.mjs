import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import { createModels, createProvider } from '@earendil-works/pi-ai';
import { openAICompletionsApi } from '@earendil-works/pi-ai/api/openai-completions.lazy';
import { builtinModels } from '@earendil-works/pi-ai/providers/all';
import { buildModel, catalog, complete, memoryCredentials, login } from './bridge.mjs';

test('official Pi catalog exposes models and actual OAuth capabilities without secrets', () => {
  const providers = catalog();
  assert.ok(providers.length > 30);
  const openai = providers.find((p) => p.id === 'openai');
  assert.ok(openai.authMethods.includes('oauth'));
  assert.ok(openai.models.some((m) => m.contextWindow > 0));
  assert.ok(!providers.find((p) => p.id === 'deepseek').authMethods.includes('oauth'));
  assert.ok(!JSON.stringify(providers).includes('credential'));
});

test('OAuth uses the provider endpoint and API even when custom overrides are supplied', () => {
  const models = builtinModels();
  const known = models.getModels('openai')[0];
  const selected = buildModel({ providerId: 'openai', model: known.id, credential: { type: 'oauth' }, baseUrl: 'https://untrusted.test', api: 'openai-completions' }, models);
  assert.equal(selected.baseUrl, known.baseUrl);
  assert.equal(selected.api, known.api);
  assert.throws(() => buildModel({ providerId: 'openai', model: 'unknown', credential: { type: 'oauth' } }, models));
});

test('custom endpoints preserve explicit protocol and API credentials', () => {
  const model = buildModel({ providerId: 'custom', model: 'local', baseUrl: 'http://127.0.0.1/v1', api: 'anthropic-messages' }, builtinModels());
  assert.equal(model.api, 'anthropic-messages');
  assert.equal(model.provider, 'custom');
  assert.equal(model.maxTokens, 4096);
});

test('credential modifications serialize concurrent refreshes', async () => {
  const store = memoryCredentials('provider', { type: 'oauth', generation: 0 });
  const update = () => store.modify('provider', async (current) => {
    await new Promise((resolve) => setTimeout(resolve, 10));
    return { ...current, generation: current.generation + 1 };
  });
  await Promise.all([update(), update(), update()]);
  assert.equal((await store.read('provider')).generation, 3);
  assert.deepEqual(await store.list(), [{ providerId: 'provider', type: 'oauth' }]);
  await assert.rejects(store.modify('wrong', async () => ({})));
});

async function endpoint(handler, run) {
  const server = createServer(handler);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try { await run(`http://127.0.0.1:${server.address().port}/v1`); }
  finally { server.closeAllConnections(); await new Promise((resolve) => server.close(resolve)); }
}
// A fresh Python invocation launches a fresh Node process. Lazy SDK imports count
// against its deadline too; protocol success must not depend on a 1s cold import.
// Keep this below the production 20s connectivity / 30s completion budgets.
const request = (baseUrl) => ({ providerId: 'custom', model: 'unit-model', baseUrl, api: 'openai-completions', credential: { type: 'api_key', key: 'unit-secret' }, prompt: 'task', system: 'fixed boundary', maxTokens: 64, timeoutMs: 10000 });

function streamFixture(api, text = 'OK') {
  if (api === 'openai-completions') {
    return `data: ${JSON.stringify({ id: 'test', model: 'unit-model', choices: [{ index: 0, delta: { role: 'assistant', content: text }, finish_reason: 'stop' }] })}\n\ndata: [DONE]\n\n`;
  }
  if (api === 'google-generative-ai') {
    return `data: ${JSON.stringify({ candidates: [{ content: { role: 'model', parts: [{ text }] }, finishReason: 'STOP' }], usageMetadata: { promptTokenCount: 1, candidatesTokenCount: 1, totalTokenCount: 2 } })}\n\n`;
  }
  const events = [
    { type: 'message_start', message: { id: 'test', type: 'message', role: 'assistant', content: [], model: 'unit-model', stop_reason: null, usage: { input_tokens: 1, output_tokens: 0 } } },
    { type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } },
    { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text } },
    { type: 'content_block_stop', index: 0 },
    { type: 'message_delta', delta: { stop_reason: 'end_turn' }, usage: { output_tokens: 1 } },
    { type: 'message_stop' },
  ];
  return events.map((e) => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join('');
}

async function coldComplete(payload) {
  const env = Object.fromEntries(['PATH', 'LANG', 'LC_ALL'].filter((k) => process.env[k]).map((k) => [k, process.env[k]]));
  const child = spawn(process.execPath, [new URL('./bridge.mjs', import.meta.url).pathname], { env, stdio: ['pipe', 'pipe', 'pipe'] });
  let output = '';
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', (chunk) => { output += chunk; });
  // The subprocess contract never exposes upstream stderr to the caller.
  child.stderr.resume();
  try {
    const finished = new Promise((resolve, reject) => {
      child.once('error', reject);
      child.once('close', (code) => code === 0 ? resolve() : reject(new Error(`Bridge exited ${code}`)));
    });
    const timer = setTimeout(() => child.kill('SIGKILL'), 15000);
    try {
      child.stdin.end(`${JSON.stringify({ ...payload, operation: 'complete' })}\n`);
      await finished;
      return JSON.parse(output);
    } finally { clearTimeout(timer); }
  } finally { if (child.exitCode === null) child.kill('SIGKILL'); }
}

test('real Pi completion forwards system boundary to compatible SSE endpoint', async () => {
  let body, authorization;
  await endpoint(async (req, res) => {
    let raw = ''; for await (const chunk of req) raw += chunk;
    body = JSON.parse(raw); authorization = req.headers.authorization;
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    res.end(streamFixture('openai-completions'));
  }, async (baseUrl) => {
    const result = await complete(request(baseUrl));
    assert.equal(result.ok, true); assert.equal(result.content, 'OK');
  });
  assert.equal(authorization, 'Bearer unit-secret');
  assert.equal(body.messages[0].content, 'fixed boundary');
  assert.equal(body.messages[1].content, 'task');
  assert.equal(body.stream, true);
  assert.equal(body.max_tokens ?? body.max_completion_tokens, 64);
});

test('upstream errors redact tokens and provider response bodies', async () => {
  await endpoint((_req, res) => {
    res.writeHead(401, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: { message: 'private-provider-message unit-secret', type: 'auth' } }));
  }, async (baseUrl) => {
    const result = await complete(request(baseUrl));
    assert.equal(result.ok, false); assert.equal(result.status, 401);
    assert.ok(!JSON.stringify({ ...result, credential: undefined }).includes('private-provider-message'));
    assert.ok(!JSON.stringify({ ...result, credential: undefined }).includes('unit-secret'));
  });
});

test('timeout aborts the upstream request without automatic retry', async () => {
  await import('@earendil-works/pi-ai/api/openai-completions');
  let calls = 0;
  await endpoint(() => { calls++; }, async (baseUrl) => {
    const result = await complete({ ...request(baseUrl), timeoutMs: 50 });
    assert.equal(result.ok, false); assert.equal(result.code, 'MODEL_TIMEOUT');
  });
  assert.equal(calls, 1);
});


test('Pi login relays device codes and sequential prompts and emits credential only to server', async () => {
  const events = [];
  const factory = (options) => {
    const models = createModels(options);
    models.setProvider(createProvider({ id: 'fake-login', models: [], api: openAICompletionsApi(), auth: { oauth: {
      name: 'Test OAuth',
      async login(interaction) {
        interaction.notify({ type: 'device_code', userCode: 'ABCD', verificationUri: 'https://example.test/device' });
        assert.equal(await interaction.prompt({ type: 'select', message: 'Account', options: [{ id: 'personal', label: 'Personal' }] }), 'personal');
        assert.equal(await interaction.prompt({ type: 'manual_code', message: 'Callback' }), 'callback');
        return { type: 'oauth', access: 'unit-access', refresh: 'unit-refresh', expires: 9999999999999 };
      }, async refresh(credential) { return credential; }, async toAuth() { return {}; },
    } } }));
    return models;
  };
  async function* lines() {
    yield JSON.stringify({ promptId: '1', value: 'personal' });
    yield JSON.stringify({ promptId: '2', value: 'callback' });
  }
  await login({ providerId: 'fake-login' }, lines(), (event) => events.push(event), factory);
  assert.equal(events[0].kind, 'event');
  assert.equal(events[1].prompt.type, 'select');
  assert.equal(events.at(-1).kind, 'credential');
  assert.equal(events.at(-1).credential.access, 'unit-access');
  assert.ok(!JSON.stringify(events.slice(0, -1)).includes('unit-access'));
});


test('legacy Anthropic /v1 endpoint is normalized and Pi messages stream works', async () => {
  let path, payload;
  await endpoint(async (req, res) => {
    path = req.url;
    let raw = ''; for await (const chunk of req) raw += chunk; payload = JSON.parse(raw);
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    res.end(streamFixture('anthropic-messages'));
  }, async (baseUrl) => {
    const result = await complete({ ...request(baseUrl), api: 'anthropic-messages' });
    assert.equal(result.ok, true); assert.equal(result.content, 'OK');
  });
  assert.equal(path.split('?')[0], '/v1/messages');
  assert.equal(payload.system[0].text, 'fixed boundary');
});

test('Pi Google adapter preserves the version path and unified text content', async () => {
  let path, payload;
  await endpoint(async (req, res) => {
    path = req.url;
    let raw = ''; for await (const chunk of req) raw += chunk; payload = JSON.parse(raw);
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    res.end(streamFixture('google-generative-ai'));
  }, async (baseUrl) => {
    const result = await complete({ ...request(baseUrl.replace('/v1', '/v1beta')), api: 'google-generative-ai' });
    assert.equal(result.ok, true); assert.equal(result.content, 'OK');
  });
  assert.ok(path.startsWith('/v1beta/models/unit-model:streamGenerateContent'));
  assert.equal(payload.systemInstruction.parts[0].text, 'fixed boundary');
});

for (const api of ['openai-completions', 'anthropic-messages', 'google-generative-ai']) {
  test(`${api}: cold subprocess parses fragmented UTF-8 SSE within its own budget`, async () => {
    let calls = 0;
    await endpoint(async (req, res) => {
      calls++;
      for await (const _chunk of req) { /* consume the request before streaming */ }
      res.writeHead(200, { 'Content-Type': 'text/event-stream' });
      const bytes = Buffer.from(streamFixture(api, '足球 OK'));
      const split = bytes.indexOf(Buffer.from('足')) + 1;
      // Split both SSE framing and a multi-byte character across socket writes.
      for (const part of [bytes.subarray(0, 3), bytes.subarray(3, split), bytes.subarray(split, split + 1), bytes.subarray(split + 1)]) {
        res.write(part);
        await delay(5);
      }
      res.end();
    }, async (baseUrl) => {
      const result = await coldComplete({ ...request(baseUrl), api });
      assert.equal(result.ok, true, result.code);
      assert.equal(result.content, '足球 OK');
    });
    assert.equal(calls, 1);
  });

  if (api !== 'openai-completions') {
    test(`${api}: warmed request timeout does not retry`, async () => {
      await import(`@earendil-works/pi-ai/api/${api}`);
      let calls = 0;
      await endpoint(() => { calls++; }, async (baseUrl) => {
        const result = await complete({ ...request(baseUrl), api, timeoutMs: 50 });
        assert.equal(result.ok, false);
        assert.equal(result.code, 'MODEL_TIMEOUT');
      });
      assert.equal(calls, 1);
    });
  }

  test(`${api}: stalled response stream is aborted and closed without retry`, async () => {
    await import(`@earendil-works/pi-ai/api/${api}`);
    let calls = 0;
    let peerClosed;
    const closed = new Promise((resolve) => { peerClosed = resolve; });
    await endpoint((req, res) => {
      calls++;
      req.resume();
      res.once('close', peerClosed);
      res.writeHead(200, { 'Content-Type': 'text/event-stream' });
      // No terminal event: an HTTP200 alone must not complete the inference.
      res.write(': partial stream\n\n');
    }, async (baseUrl) => {
      const result = await complete({ ...request(baseUrl), api, timeoutMs: 150 });
      assert.equal(result.ok, false);
      assert.equal(result.code, 'MODEL_TIMEOUT');
      assert.equal(await Promise.race([closed.then(() => true), delay(1000).then(() => false)]), true);
    });
    assert.equal(calls, 1);
  });

  test(`${api}: retryable HTTP503 is reported once without leaking its body`, async () => {
    let calls = 0;
    await endpoint((req, res) => {
      calls++;
      req.resume();
      res.writeHead(503, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: { message: 'private-provider-message unit-secret', type: 'unavailable' } }));
    }, async (baseUrl) => {
      const result = await complete({ ...request(baseUrl), api });
      assert.equal(result.ok, false);
      assert.equal(result.status, 503);
      assert.equal(result.code, 'MODEL_CALL_FAILED');
      assert.ok(!JSON.stringify({ ...result, credential: undefined }).includes('private-provider-message'));
      assert.ok(!JSON.stringify({ ...result, credential: undefined }).includes('unit-secret'));
    });
    assert.equal(calls, 1);
  });
}
