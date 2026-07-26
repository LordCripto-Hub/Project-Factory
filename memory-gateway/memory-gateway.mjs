#!/usr/bin/env node
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { fileURLToPath } from 'node:url';

const PROJECT_SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const ENV_NAME = /^[A-Z][A-Z0-9_]{1,63}$/;
const INPUT_KEYS = new Set([
  'serverUrl',
  'projectSlug',
  'question',
  'topK',
  'hops',
  'timeoutSeconds',
  'credentialEnv',
  'maxChars',
]);
const PUBLIC_ERRORS = new Set([
  'unauthorized',
  'timeout',
  'project_mismatch',
  'invalid_response',
  'budget_exceeded',
  'unavailable',
]);

export class GatewayError extends Error {
  constructor(code) {
    super(code);
    this.name = 'GatewayError';
    this.code = code;
  }
}

function invalid(code = 'invalid_response') {
  throw new GatewayError(code);
}

export function validateInput(value, {allowHttpLoopback = false} = {}) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalid();
  if (Object.keys(value).some(key => !INPUT_KEYS.has(key))) invalid();
  const request = {...value};
  if (typeof request.serverUrl !== 'string') invalid();
  let url;
  try {
    url = new URL(request.serverUrl);
  } catch {
    invalid();
  }
  if (url.username || url.password || url.search || url.hash) invalid();
  const loopback = url.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(url.hostname);
  const internalCanary = (
    request.serverUrl === 'http://memory-gate-b:18443/mcp' &&
    process.env.MYPEOPLE_MEMORY_CANARY_URL === request.serverUrl &&
    request.projectSlug === 'project-factory'
  );
  if (url.protocol !== 'https:' && !(allowHttpLoopback && loopback) && !internalCanary) invalid();
  if (!PROJECT_SLUG.test(request.projectSlug || '') || request.projectSlug.length > 64) invalid();
  if (typeof request.question !== 'string') invalid();
  request.question = request.question.trim();
  if (!request.question || request.question.length > 500) invalid();
  if (!Number.isInteger(request.topK) || request.topK < 1 || request.topK > 3) invalid();
  if (request.hops !== 0) invalid();
  if (typeof request.timeoutSeconds !== 'number' || request.timeoutSeconds < 0.01 || request.timeoutSeconds > 15) invalid();
  if (!ENV_NAME.test(request.credentialEnv || '')) invalid();
  if (!Number.isInteger(request.maxChars) || request.maxChars < 256 || request.maxChars > 20000) invalid();
  request.serverUrl = url.toString();
  return request;
}

function normalizeAiUsage(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return 'not_measured';
  const entries = Object.entries(value);
  if (entries.length > 16) return 'not_measured';
  const clean = {};
  for (const [key, amount] of entries) {
    if (!/^[A-Za-z][A-Za-z0-9_]{0,31}$/.test(key)) continue;
    if (typeof amount !== 'number' || !Number.isFinite(amount) || amount < 0 || amount > 1e15) continue;
    clean[key] = amount;
  }
  return Object.keys(clean).length ? clean : 'not_measured';
}

export function normalizeClaims(rawClaims, request, rawAiUsage) {
  if (!Array.isArray(rawClaims) || rawClaims.length > request.topK) invalid();
  const claims = [];
  let responseChars = 0;
  let truncated = false;
  for (const raw of rawClaims) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) invalid();
    for (const field of ['id', 'projectSlug', 'content', 'sourceUri', 'sourceType']) {
      if (typeof raw[field] !== 'string' || !raw[field].trim()) invalid();
    }
    if (raw.projectSlug !== request.projectSlug) invalid('project_mismatch');
    if (responseChars >= request.maxChars) {
      truncated = true;
      break;
    }
    const claim = {
      id: raw.id,
      projectSlug: raw.projectSlug,
      content: raw.content,
      sourceUri: raw.sourceUri,
      sourceType: raw.sourceType,
    };
    for (const field of ['createdAt', 'updatedAt']) {
      if (raw[field] !== undefined) {
        if (typeof raw[field] !== 'number' || !Number.isFinite(raw[field]) || raw[field] < 0) invalid();
        claim[field] = raw[field];
      }
    }
    if (raw.status !== undefined) {
      if (typeof raw.status !== 'string' || !raw.status.trim() || raw.status.length > 64) invalid();
      claim.status = raw.status.trim();
    }
    const remaining = request.maxChars - responseChars;
    if (claim.content.length > remaining) {
      claim.content = claim.content.slice(0, remaining);
      truncated = true;
    }
    responseChars += claim.content.length;
    claims.push(claim);
    if (truncated) break;
  }
  return {claims, truncated, responseChars, aiUsage: normalizeAiUsage(rawAiUsage)};
}

function classifyTransportError(error) {
  const candidates = [error?.status, error?.statusCode, error?.code, error?.response?.status];
  const status = candidates.find(value => Number.isInteger(value));
  return status === 401 || status === 403 ? 'unauthorized' : 'unavailable';
}

function realClientFactory(request, token) {
  const transport = new StreamableHTTPClientTransport(new URL(request.serverUrl), {
    requestInit: {headers: {Authorization: `Bearer ${token}`}},
  });
  const client = new Client({name: 'mypeople-memory-gateway', version: '0.1.0'});
  return {
    connect: () => client.connect(transport),
    callTool: payload => client.callTool(payload),
    close: () => client.close(),
  };
}

export async function executeRecall(value, options = {}) {
  const request = validateInput(value, {allowHttpLoopback: options.allowHttpLoopback === true});
  const token = options.token || process.env[request.credentialEnv];
  if (!token) invalid('unauthorized');
  const factory = options.clientFactory || realClientFactory;
  const client = factory(request, token);
  let timer;
  try {
    await client.connect();
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => reject(new GatewayError('timeout')), request.timeoutSeconds * 1000);
    });
    const response = await Promise.race([
      client.callTool({
        name: 'recall',
        arguments: {
          projectSlug: request.projectSlug,
          query: request.question,
          limit: request.topK,
          hops: request.hops,
        },
      }),
      timeout,
    ]);
    if (response?.isError === true) invalid('invalid_response');
    const claims = response?.structuredContent?.claims;
    return normalizeClaims(claims, request, response?.structuredContent?.aiUsage);
  } catch (error) {
    if (error instanceof GatewayError) throw error;
    invalid(classifyTransportError(error));
  } finally {
    if (timer) clearTimeout(timer);
    try {
      await client.close();
    } catch {
      // Closing is best-effort after the typed operation result is known.
    }
  }
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const text = Buffer.concat(chunks).toString('utf8').trim();
  if (!text) invalid();
  try {
    return JSON.parse(text);
  } catch {
    invalid();
  }
}

export async function main() {
  const request = await readStdin();
  const result = await executeRecall(request);
  process.stdout.write(`${JSON.stringify({ok: true, ...result})}\n`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch(error => {
    const code = PUBLIC_ERRORS.has(error?.code) ? error.code : 'unavailable';
    process.stdout.write(`${JSON.stringify({ok: false, error: code})}\n`);
    process.exitCode = 1;
  });
}
