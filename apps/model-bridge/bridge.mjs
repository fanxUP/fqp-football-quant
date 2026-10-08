/** Server-only Pi adapter. Secrets use pipes, never argv or credential files. */
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';
import { createModels, createProvider, cleanupSessionResources } from '@earendil-works/pi-ai';
import { builtinModels } from '@earendil-works/pi-ai/providers/all';
import { openAICompletionsApi } from '@earendil-works/pi-ai/api/openai-completions.lazy';
import { openAIResponsesApi } from '@earendil-works/pi-ai/api/openai-responses.lazy';
import { anthropicMessagesApi } from '@earendil-works/pi-ai/api/anthropic-messages.lazy';
import { googleGenerativeAIApi } from '@earendil-works/pi-ai/api/google-generative-ai.lazy';

export const APIS = {
  'openai-completions': openAICompletionsApi,
  'openai-responses': openAIResponsesApi,
  'anthropic-messages': anthropicMessagesApi,
  'google-generative-ai': googleGenerativeAIApi,
};

export function memoryCredentials(providerId, initial) {
  let credential = initial;
  let pending = Promise.resolve();
  return {
    async read(id) { return id === providerId ? credential : undefined; },
    async list() { return credential ? [{ providerId, type: credential.type }] : []; },
    modify(id, fn) {
      const operation = pending.then(async () => {
        if (id !== providerId) throw new Error('Credential provider mismatch');
        const next = await fn(credential);
        if (next !== undefined) credential = next;
        return credential;
      });
      pending = operation.catch(() => {});
      return operation;
    },
    async delete(id) { await pending; if (id === providerId) credential = undefined; },
  };
}

const noAmbientAuth = { async env() { return undefined; }, async fileExists() { return false; } };

export function catalog() {
  return builtinModels({ authContext: noAmbientAuth }).getProviders().map((p) => ({
    id: p.id, name: p.name, baseUrl: p.baseUrl ?? '',
    authMethods: [p.auth.apiKey?.login ? 'api_key' : null, p.auth.oauth ? 'oauth' : null].filter(Boolean),
    oauthLabel: p.auth.oauth?.loginLabel ?? p.auth.oauth?.name ?? null,
    models: p.getModels().map((m) => ({
      id: m.id, name: m.name, api: m.api, baseUrl: m.baseUrl,
      input: m.input, reasoning: m.reasoning, contextWindow: m.contextWindow,
      maxTokens: m.maxTokens, cost: m.cost,
    })),
  }));
}

export function buildModel(request, collection) {
  const known = collection.getModel(request.providerId, request.model);
  if (request.credential?.type === 'oauth') {
    if (!known) throw new Error('Unknown OAuth model');
    // OAuth derives the upstream endpoint and protocol from the provider.
    return known;
  }
  const api = request.api || known?.api || 'openai-completions';
  const requestedBase = request.baseUrl || known?.baseUrl;
  // Anthropic SDK appends /v1/messages; old Python configs already included /v1.
  const baseUrl = api === 'anthropic-messages' ? requestedBase?.replace(/\/v1\/?$/, '') : requestedBase;
  if (!APIS[api] && !known) throw new Error('Unsupported custom API');
  if (known && api === known.api) return { ...known, baseUrl };
  return {
    ...(known ?? {}), id: request.model, name: request.model, provider: request.providerId,
    api, baseUrl, input: known?.input ?? ['text'],
    reasoning: known?.reasoning ?? false, contextWindow: known?.contextWindow ?? 32768,
    maxTokens: known?.maxTokens ?? 4096,
    cost: known?.cost ?? { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  };
}

export async function complete(request) {
  const credentials = memoryCredentials(request.providerId, request.credential);
  let models = builtinModels({ credentials, authContext: noAmbientAuth });
  const model = buildModel(request, models);
  const builtin = models.getProvider(request.providerId);
  const builtinModel = builtin?.getModels().find((m) => m.id === request.model);
  if (request.credential?.type !== 'oauth' && (!builtinModel || model.api !== builtinModel.api)) {
    if (!APIS[model.api]) throw new Error('Unsupported custom API');
    const key = request.credential?.key || (request.keyless ? 'local' : undefined);
    if (!key) throw new Error('Missing API key');
    models = createModels({ credentials, authContext: noAmbientAuth });
    models.setProvider(createProvider({
      id: request.providerId, models: [model], api: APIS[model.api](),
      auth: { apiKey: { name: 'FQP credential', async resolve() { return { auth: { apiKey: key } }; } } },
    }));
  }
  let httpStatus = null;
  const originalFetch = globalThis.fetch;
  // One request per subprocess. Reject redirects before credentials can be forwarded.
  globalThis.fetch = async (input, options) => {
    const response = await originalFetch(input, { ...options, redirect: 'error' });
    httpStatus = response.status;
    return response;
  };
  const signal = AbortSignal.timeout(Math.min(request.timeoutMs ?? 30000, 60000));
  try {
    const reply = await models.completeSimple(model, {
      messages: [
        { role: 'system', content: request.system, timestamp: Date.now() },
        { role: 'user', content: request.prompt, timestamp: Date.now() },
      ],
    }, {
      signal, timeoutMs: request.timeoutMs ?? 30000, maxRetries: 0,
      maxRetryDelayMs: 1000, maxTokens: request.maxTokens ?? 800,
      transport: 'sse', cacheRetention: 'none',
      onResponse(response) { httpStatus = response.status; },
    });
    const credential = await credentials.read(request.providerId);
    if (reply.stopReason === 'error' || reply.stopReason === 'aborted') {
      return { ok: false, status: httpStatus, code: signal.aborted ? 'MODEL_TIMEOUT' : 'MODEL_CALL_FAILED', credential };
    }
    const content = reply.content.filter((c) => c.type === 'text').map((c) => c.text).join('\n').trim();
    return { ok: Boolean(content), content: content.slice(0, 12000), code: content ? null : 'MODEL_EMPTY_RESPONSE', credential };
  } catch (error) {
    return { ok: false, code: signal.aborted ? 'MODEL_TIMEOUT' : error?.code === 'oauth' ? 'MODEL_AUTH_FAILED' : 'MODEL_CALL_FAILED', credential: await credentials.read(request.providerId) };
  } finally {
    globalThis.fetch = originalFetch;
    cleanupSessionResources();
  }
}

export async function login(request, lines, emit, createCollection = builtinModels) {
  const credentials = memoryCredentials(request.providerId);
  const models = createCollection({ credentials, authContext: noAmbientAuth });
  if (!models.getProvider(request.providerId)?.auth.oauth) throw new Error('OAuth unavailable');
  const signal = AbortSignal.timeout(300000);
  let counter = 0;
  const credential = await models.login(request.providerId, 'oauth', {
    signal,
    notify(event) { emit({ kind: 'event', event }); },
    async prompt(prompt) {
      const promptId = String(++counter);
      const { signal: promptSignal, ...publicPrompt } = prompt;
      emit({ kind: 'prompt', promptId, prompt: publicPrompt });
      const input = lines.next();
      const abort = new Promise((_, reject) => {
        const abortInput = () => reject(new Error('Login cancelled'));
        signal.addEventListener('abort', abortInput, { once: true });
        promptSignal?.addEventListener('abort', abortInput, { once: true });
      });
      const result = await Promise.race([input, abort]);
      if (result.done) throw new Error('Login input closed');
      const reply = JSON.parse(result.value);
      if (reply.promptId !== promptId || typeof reply.value !== 'string' || reply.value.length > 4096) throw new Error('Invalid login input');
      return reply.value;
    },
  }, { agentName: 'FQP', getDeviceId: () => request.deviceId });
  emit({ kind: 'credential', credential });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for (const method of ['log', 'info', 'warn', 'error', 'debug']) console[method] = () => {};
  const reader = createInterface({ input: process.stdin, crlfDelay: Infinity });
  const lines = reader[Symbol.asyncIterator]();
  const emit = (value) => process.stdout.write(`${JSON.stringify(value)}\n`);
  try {
    const first = await lines.next();
    if (first.done || first.value.length > 65536) throw new Error('Invalid request');
    const request = JSON.parse(first.value);
    if (request.operation === 'catalog') emit({ ok: true, providers: catalog() });
    else if (request.operation === 'complete') emit(await complete(request));
    else if (request.operation === 'login') await login(request, lines, emit);
    else throw new Error('Unsupported operation');
  } catch {
    // Never echo upstream exception messages: they may contain tokens or request bodies.
    emit({ ok: false, kind: 'error', code: 'PI_BRIDGE_FAILED' });
    process.exitCode = 1;
  } finally { reader.close(); }
}
